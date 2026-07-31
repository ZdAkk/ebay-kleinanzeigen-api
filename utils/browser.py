import asyncio
from typing import List
from playwright.async_api import async_playwright, BrowserContext, Page
from utils.user_agent import get_random_ua


class PlaywrightManager:
    def __init__(self):
        self._playwright = None
        self._browser = None

    async def start(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)

    async def new_context_page(self):
        context = await self._browser.new_context(user_agent=get_random_ua())
        return await context.new_page()

    async def close_page(self, page):
        await page.close()

    async def close(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()


class OptimizedPlaywrightManager:
    def __init__(self, max_contexts: int = 10, max_concurrent: int = 5):
        self._playwright = None
        self._browser = None
        self._context_pool: List[BrowserContext] = []
        self._context_in_use: List[BrowserContext] = []
        # Creation slots reserved by get_context while it runs new_context() I/O
        # OUTSIDE the lock, so the max_contexts ceiling still holds during the
        # unlocked create (see get_context).
        self._pending_creates = 0
        self._max_contexts = max_contexts
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._context_lock = asyncio.Lock()
        # Hard ceiling (seconds) for any single Playwright teardown call, so a
        # hung browser op can never pin the context lock or a semaphore permit.
        self._op_timeout = 10
        # Overall deadline (seconds) for acquiring a context. Genuine pool
        # exhaustion then fails fast (keeping the event loop and health check
        # responsive) instead of the acquire loop spinning forever.
        self._acquire_timeout = 30

        # --- lifetime bounds (memory) ------------------------------------
        # Nothing here used to be retired: the browser process and the pooled
        # contexts lived for the whole container lifetime, so Chromium's memory
        # only ever grew (observed: a 13-day-old browser process at 312 MB plus
        # ~14 live renderers, ~890 MB total, until page loads started timing out
        # against the 1 GB cap). Three bounded lifetimes keep it flat:
        #   1. a context is retired after _max_context_uses acquisitions,
        #   2. only _idle_pool_target contexts are kept warm,
        #   3. the whole browser is relaunched every _max_ops_before_recycle ops.
        self._max_context_uses = 50
        self._idle_pool_target = 3
        self._max_ops_before_recycle = 400
        self._context_uses: dict = {}
        self._ops_since_recycle = 0
        self._recycling = False
        # Under sustained load the pool is never idle, so an "only when idle"
        # recycle would never fire. Once ops reach this (2x) hard limit we stop
        # handing out contexts and let the in-use ones drain, which takes a few
        # seconds at this concurrency and is well inside _acquire_timeout.
        self._force_recycle_at = self._max_ops_before_recycle * 2
        self._draining = False

        # Performance metrics
        self._contexts_created = 0
        self._contexts_reused = 0
        self._contexts_retired = 0
        self._browser_recycles = 0
        self._concurrent_operations = 0
        self._max_concurrent_reached = 0

    @property
    def max_concurrent(self) -> int:
        """The CONFIGURED max concurrency (stable), unlike _semaphore._value,
        which is the current number of FREE permits and drops to 0 under load."""
        return self._max_concurrent

    async def start(self):
        """Initialize the browser and create initial context pool"""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)

        # Pre-create some contexts for the pool
        initial_contexts = min(3, self._max_contexts)
        for _ in range(initial_contexts):
            context = await self._browser.new_context(user_agent=get_random_ua())
            self._context_pool.append(context)
            self._contexts_created += 1

    async def _maybe_recycle_browser(self) -> bool:
        """Relaunch the browser process if it has done enough work and is idle.

        Chromium's browser process grows across thousands of navigations and is
        never freed while it lives, so it is replaced periodically. Only runs
        when NOTHING is in use (no in-use contexts, no pending creates), so no
        caller can be holding a context that is about to be destroyed. All the
        browser I/O happens OUTSIDE _context_lock; the flag reserves the right
        to recycle so concurrent callers wait instead of racing.

        Returns True if a recycle happened.
        """
        async with self._context_lock:
            if self._recycling or self._ops_since_recycle < self._max_ops_before_recycle:
                return False
            if self._context_in_use or self._pending_creates:
                # Busy: wait for an idle moment, unless we're now so far past due
                # that we stop issuing contexts and let the in-use ones drain.
                self._draining = self._ops_since_recycle >= self._force_recycle_at
                return False
            self._recycling = True
            self._draining = False
            stale, self._context_pool = self._context_pool, []

        # --- browser I/O below runs WITHOUT the lock held ---
        try:
            for context in stale:
                try:
                    await asyncio.wait_for(context.close(), timeout=self._op_timeout)
                except Exception:
                    pass
            old_browser = self._browser
            self._browser = None
            if old_browser:
                try:
                    await asyncio.wait_for(old_browser.close(), timeout=self._op_timeout)
                except Exception:
                    pass
            self._browser = await self._playwright.chromium.launch(headless=True)
        finally:
            async with self._context_lock:
                self._context_uses.clear()
                self._ops_since_recycle = 0
                self._browser_recycles += 1
                self._recycling = False
        return True

    async def get_context(self) -> BrowserContext:
        """Get a browser context from the pool or create a new one.

        Context CREATION I/O (new_context) runs OUTSIDE _context_lock, bounded by
        a timeout, exactly like release_context's teardown. A creation slot is
        reserved under the lock (_pending_creates) so the max_contexts ceiling
        still holds while the unlocked I/O runs. The previous version awaited
        new_context WHILE holding the lock with no timeout, so a single hung
        create pinned the lock and froze every other get/release -> full wedge.

        The acquire loop has an overall deadline so genuine pool exhaustion fails
        fast (keeping the event loop and health check responsive) instead of
        spinning forever; and a partially created context is always closed on
        cancellation/timeout so it can't leak.
        """
        deadline = asyncio.get_running_loop().time() + self._acquire_timeout
        await self._maybe_recycle_browser()
        while True:
            # Retry the recycle each pass: while draining, the last release
            # empties _context_in_use and this is what then fires the relaunch.
            if self._draining and not self._recycling:
                await self._maybe_recycle_browser()

            async with self._context_lock:
                # A recycle is in flight, the browser is mid-relaunch, or we're
                # draining for one: wait rather than hand out a context that is
                # about to be destroyed (or that would prolong the drain).
                if self._recycling or self._browser is None or self._draining:
                    creating = False
                elif self._context_pool:
                    context = self._context_pool.pop()
                    self._context_in_use.append(context)
                    self._context_uses[context] = self._context_uses.get(context, 0) + 1
                    self._contexts_reused += 1
                    self._ops_since_recycle += 1
                    return context
                else:
                    # Reserve a creation slot, but do NOT touch the browser here.
                    creating = (
                        len(self._context_in_use) + self._pending_creates
                        < self._max_contexts
                    )
                    if creating:
                        self._pending_creates += 1

            if creating:
                context = None
                registered = False
                try:
                    context = await asyncio.wait_for(
                        self._browser.new_context(user_agent=get_random_ua()),
                        timeout=self._op_timeout,
                    )
                    async with self._context_lock:
                        self._pending_creates -= 1
                        self._context_in_use.append(context)
                        self._context_uses[context] = 1
                        self._contexts_created += 1
                        self._ops_since_recycle += 1
                        registered = True
                    return context
                except BaseException:
                    # Includes Cancelled/Timeout: free the reserved slot and
                    # never leak a partially created context.
                    if not registered:
                        async with self._context_lock:
                            self._pending_creates -= 1
                        if context is not None:
                            try:
                                await asyncio.wait_for(
                                    context.close(), timeout=self._op_timeout
                                )
                            except Exception:
                                pass
                    raise

            # At the limit: wait and retry, but not forever.
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(
                    "get_context: context pool exhausted (no context available "
                    f"within {self._acquire_timeout}s)"
                )
            await asyncio.sleep(0.1)

    async def release_context(self, context: BrowserContext):
        """Return a context to the pool for reuse.

        Playwright teardown (page.close/clear_cookies/context.close) runs
        OUTSIDE _context_lock, each bounded by a timeout. Previously these ran
        WHILE holding the lock, so one hung browser call froze every other
        get/release and wedged the whole service. On any cleanup failure the
        context is dropped rather than returned to the pool.
        """
        async with self._context_lock:
            if context not in self._context_in_use:
                return  # not ours, or a double release
            self._context_in_use.remove(context)
            # Retire a context once it has been reused enough times, and keep
            # only a small warm pool. Each live context costs a Chromium
            # renderer process (~20 MB) that is never reclaimed while pooled, so
            # an unbounded pool of endlessly-reused contexts was a steady leak.
            worn = self._context_uses.get(context, 0) >= self._max_context_uses
            repool = not worn and len(self._context_pool) < self._idle_pool_target
            if not repool:
                self._context_uses.pop(context, None)
                self._contexts_retired += 1

        # --- browser I/O below runs WITHOUT the lock held ---
        try:
            # Close all pages and clear session state so a reused context does
            # not carry Kleinanzeigen tracking cookies into the next request.
            for page in list(context.pages):
                await asyncio.wait_for(page.close(), timeout=self._op_timeout)
            await asyncio.wait_for(context.clear_cookies(), timeout=self._op_timeout)
        except BaseException as exc:
            # Cleanup hung, failed, OR was cancelled mid-teardown: force-close and
            # drop it, never repool (it was already removed from _context_in_use
            # above, so this is the last chance to close it). BaseException so a
            # CancelledError still closes the context; re-raise it afterwards so
            # the caller's cancellation is not swallowed.
            try:
                await asyncio.wait_for(context.close(), timeout=self._op_timeout)
            except Exception:
                pass
            if isinstance(exc, asyncio.CancelledError):
                raise
            return

        if repool:
            async with self._context_lock:
                self._context_pool.append(context)
        else:
            try:
                await asyncio.wait_for(context.close(), timeout=self._op_timeout)
            except Exception:
                pass

    async def execute_with_semaphore(self, coro, timeout: float = None):
        """Execute a coroutine with concurrency control.

        The permit is acquired first (unbounded wait, so requests queue rather
        than fail), then the operation runs under an optional hard timeout. On
        expiry the coroutine is cancelled (its own finally releases the
        page/context) and the permit is freed here, so a stuck op can never pin
        a permit and starve every other endpoint.
        """
        async with self._semaphore:
            self._concurrent_operations += 1
            self._max_concurrent_reached = max(
                self._max_concurrent_reached, self._concurrent_operations
            )
            try:
                if timeout is not None:
                    return await asyncio.wait_for(coro, timeout)
                return await coro
            finally:
                self._concurrent_operations -= 1

    async def new_context_page(self) -> Page:
        """Create a new page using context pooling (backward compatibility)"""
        context = await self.get_context()
        page = await context.new_page()
        # Store context reference on page for cleanup
        page._context_ref = context
        return page

    async def close_page(self, page: Page):
        """Close a page and return its context to the pool"""
        context = getattr(page, "_context_ref", None)
        try:
            await asyncio.wait_for(page.close(), timeout=self._op_timeout)
        except Exception:
            pass
        if context:
            await self.release_context(context)

    def get_performance_metrics(self) -> dict:
        """Get current performance metrics"""
        return {
            "contexts_created": self._contexts_created,
            "contexts_reused": self._contexts_reused,
            "contexts_retired": self._contexts_retired,
            "browser_recycles": self._browser_recycles,
            "ops_since_recycle": self._ops_since_recycle,
            "contexts_in_pool": len(self._context_pool),
            "contexts_in_use": len(self._context_in_use),
            "max_contexts": self._max_contexts,
            "max_concurrent_reached": self._max_concurrent_reached,
            "current_concurrent": self._concurrent_operations,
            "reuse_ratio": self._contexts_reused / max(self._contexts_created, 1),
        }

    async def close(self):
        """Clean up all resources"""
        # Close all contexts in pool
        for context in self._context_pool:
            await context.close()

        # Close all contexts in use
        for context in self._context_in_use:
            await context.close()

        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

        self._context_pool.clear()
        self._context_in_use.clear()

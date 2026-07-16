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
        self._max_contexts = max_contexts
        self._max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._context_lock = asyncio.Lock()
        # Hard ceiling (seconds) for any single Playwright teardown call, so a
        # hung browser op can never pin the context lock or a semaphore permit.
        self._op_timeout = 10

        # Performance metrics
        self._contexts_created = 0
        self._contexts_reused = 0
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

    async def get_context(self) -> BrowserContext:
        """Get a browser context from the pool or create a new one.

        When the pool is empty and we're at max_contexts, wait via a LOOP that
        releases the lock between attempts. The previous version recursed while
        still holding the non-reentrant _context_lock, which self-deadlocked the
        entire manager (every get/release blocks forever) once max_contexts
        were simultaneously in use.
        """
        while True:
            async with self._context_lock:
                if self._context_pool:
                    context = self._context_pool.pop()
                    self._context_in_use.append(context)
                    self._contexts_reused += 1
                    return context

                # Create a new context if the pool is empty and under the limit
                if len(self._context_in_use) < self._max_contexts:
                    context = await self._browser.new_context(
                        user_agent=get_random_ua()
                    )
                    self._context_in_use.append(context)
                    self._contexts_created += 1
                    return context

            # At the limit: release the lock, wait, then retry. Looping (not
            # recursing) means we never try to re-acquire a lock we already hold.
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
            repool = len(self._context_pool) < self._max_contexts // 2

        # --- browser I/O below runs WITHOUT the lock held ---
        try:
            # Close all pages and clear session state so a reused context does
            # not carry Kleinanzeigen tracking cookies into the next request.
            for page in list(context.pages):
                await asyncio.wait_for(page.close(), timeout=self._op_timeout)
            await asyncio.wait_for(context.clear_cookies(), timeout=self._op_timeout)
        except Exception:
            # Cleanup hung or failed: force-close and drop it, never repool.
            try:
                await asyncio.wait_for(context.close(), timeout=self._op_timeout)
            except Exception:
                pass
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

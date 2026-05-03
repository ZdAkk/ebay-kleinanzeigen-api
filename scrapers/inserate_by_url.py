"""
URL-passthrough scraper: takes a full Kleinanzeigen URL and injects page numbers.
Reuses UltraOptimizedScraper for fetching/extraction; only the URL-building differs.
"""

import asyncio
import gc
import re
from typing import Dict, Any, Optional

from utils.browser import OptimizedPlaywrightManager
from utils.performance import PerformanceTracker
from scrapers.inserate_ultra_optimized import create_ultra_optimized_scraper

_TOTAL_RESULTS_SELECTOR = {"breadcrump_summary": ".breadcrump-summary"}


def inject_page(url: str, page_num: int) -> str:
    """
    Strip any existing seite/s-seite segment and inject the requested page number.

    Category URLs: seite:N is inserted at position 2 (after slug and subcategory),
    matching Kleinanzeigen's own pagination format:
      /s-autos/volkswagen/seite:2/klima/k0c216+...
    Generic search URLs (no filter segment): s-seite:N before the query string.
    """
    from urllib.parse import urlparse, urlunparse, unquote

    parsed = urlparse(url)
    path = unquote(parsed.path)

    # Strip any existing page segment
    segments = [s for s in path.strip("/").split("/")
                if s and not re.match(r"^s-seite:\d+$", s) and not re.match(r"^seite:\d+$", s)]

    if page_num > 1:
        has_filter = any(re.match(r"^k?\d*c\d+", s) for s in segments)
        if has_filter:
            # Insert seite:N at position 2 — Kleinanzeigen places it after subcategory
            segments.insert(min(2, len(segments)), f"seite:{page_num}")
        else:
            # Generic search: append s-seite:N before query string
            segments.append(f"s-seite:{page_num}")

    new_path = "/" + "/".join(segments)
    return urlunparse(parsed._replace(path=new_path))


def _parse_total_results(breadcrump_text: str) -> Optional[int]:
    match = re.search(r"von ([\d.]+)", breadcrump_text)
    if match:
        return int(match.group(1).replace(".", ""))
    return None


async def scrape_by_url(
    browser_manager: OptimizedPlaywrightManager,
    base_url: str,
    max_pages: int = 1,
) -> Dict[str, Any]:
    """Scrape up to max_pages pages starting from base_url."""
    scraper = await create_ultra_optimized_scraper(browser_manager)
    tracker = PerformanceTracker()
    tracker.start_request()

    try:
        batch_size = min(8, max_pages)
        all_results = []
        all_metrics = []
        total_results: Optional[int] = None

        # Fetch pages sequentially — Kleinanzeigen blocks concurrent requests
        # from the same IP even with staggered starts.
        for page_num in range(1, max_pages + 1):
            result = await scraper.ultra_optimized_fetch_page(
                inject_page(base_url, page_num), page_num,
                extra_selectors=_TOTAL_RESULTS_SELECTOR if page_num == 1 else None,
            )
            if not isinstance(result, Exception):
                page_results, page_metrics, extras = result
                if total_results is None and "breadcrump_summary" in extras:
                    total_results = _parse_total_results(extras["breadcrump_summary"])
                all_results.extend(page_results)
                all_metrics.append(page_metrics)
                tracker.add_page_metric(page_metrics)
            gc.collect()

        tracker.set_concurrent_level(batch_size)
        browser_metrics = browser_manager.get_performance_metrics()
        tracker.set_browser_contexts_used(
            browser_metrics["contexts_in_use"] + browser_metrics["contexts_in_pool"]
        )
        request_metrics = tracker.get_request_metrics()
        request_metrics_dict = request_metrics.to_dict()

        successful_pages = sum(1 for m in all_metrics if m.success)
        success_rate = (successful_pages / max_pages) * 100 if max_pages > 0 else 0

        response = {
            "success": True,
            "results": all_results,
            "unique_results": len(all_results),
            "time_taken": round(request_metrics.total_time, 3),
            "performance_metrics": {
                "pages_requested": max_pages,
                "pages_successful": successful_pages,
                "success_rate": round(success_rate, 2),
                "average_page_time": round(request_metrics_dict.get("average_page_time", 0), 3),
            },
            "browser_metrics": browser_metrics,
        }

        if total_results is not None:
            response["total_results"] = total_results

        return response
    finally:
        await scraper.cleanup()

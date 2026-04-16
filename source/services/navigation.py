from __future__ import annotations

import asyncio

try:
    from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError
except Exception:  # pragma: no cover - handled gracefully at runtime
    Page = None
    PlaywrightTimeoutError = TimeoutError

from state import NavigationResult


def _is_download_start_error(exc: Exception) -> bool:
    message = str(exc)
    return "Download is starting" in message or "download is starting" in message


async def _goto_with_retry(
    page: Page,
    url: str,
    post_navigation_delay_ms: int = 0,
    max_attempts: int = 3,
) -> tuple[str, str | None]:
    last_error = ""
    last_status = "navigation_failed"

    for attempt in range(1, max_attempts + 1):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            if post_navigation_delay_ms > 0:
                await page.wait_for_timeout(post_navigation_delay_ms)
            return "navigated", None
        except PlaywrightTimeoutError as exc:
            last_status = "navigation_timeout"
            last_error = str(exc)
        except Exception as exc:
            last_status = "navigation_failed"
            last_error = str(exc)
            if _is_download_start_error(exc):
                if attempt < max_attempts:
                    await asyncio.sleep(float(attempt))
                    continue
                return "navigation_download", last_error

            if "ERR_ABORTED" in str(exc) and attempt < max_attempts:
                await asyncio.sleep(float(attempt) * 0.5)
                continue

        if attempt < max_attempts:
            await asyncio.sleep(float(attempt))

    return last_status, last_error

async def navigate_urls(
    page: Page | None,
    agent_index: int,
    tab_handle: str | None,
    urls: list[str],
) -> list[NavigationResult]:
    if page is None:
        return [
            {
                "agent_index": agent_index,
                "handle": tab_handle,
                "url": url,
                "status": "navigation_skipped",
                "current_url": None,
                "error": "Navigation requires an attached Playwright page",
            }
            for url in urls
        ]

    if not urls:
        return [
            {
                "agent_index": agent_index,
                "handle": tab_handle,
                "url": None,
                "status": "idle",
                "current_url": page.url,
                "error": None,
            }
        ]

    results: list[NavigationResult] = []
    for url in urls:
        status, error = await _goto_with_retry(page, url)
        results.append(
            {
                "agent_index": agent_index,
                "handle": tab_handle,
                "url": url,
                "status": status,
                "current_url": page.url if page else None,
                "error": error,
            }
        )

    return results


async def navigate_to_url(
    page: Page | None,
    agent_index: int,
    tab_handle: str | None,
    url: str | None,
    post_navigation_delay_ms: int = 5_000,
) -> NavigationResult:
    if page is None:
        return {
            "agent_index": agent_index,
            "handle": tab_handle,
            "url": url,
            "status": "navigation_skipped",
            "current_url": None,
            "error": f"Navigation requires an attached Playwright page {url}",
        }

    if not url:
        return {
            "agent_index": agent_index,
            "handle": tab_handle,
            "url": None,
            "status": "idle",
            "current_url": page.url,
            "error": None,
        }

    status, error = await _goto_with_retry(page, url, post_navigation_delay_ms=post_navigation_delay_ms)
    if status == "navigated":
        return {
            "agent_index": agent_index,
            "handle": tab_handle,
            "url": url,
            "status": status,
            "current_url": page.url,
            "error": None,
        }
    if status == "navigation_timeout":
        return {
            "agent_index": agent_index,
            "handle": tab_handle,
            "url": url,
            "status": status,
            "current_url": page.url,
            "error": error,
        }
    return {
        "agent_index": agent_index,
        "handle": tab_handle,
        "url": url,
        "status": status,
        "current_url": page.url if page else None,
        "error": error,
    }

from __future__ import annotations

import asyncio
from typing import Any

try:
    from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError
except Exception:  # pragma: no cover - handled gracefully at runtime
    Page = None
    PlaywrightTimeoutError = TimeoutError

from js_helper.job_detail_page_extraction import extract_page_markdown
from services.pipeline_logging import get_logger
from state import ExtractedPageContent

logger = get_logger("content_extraction")


COOKIE_SELECTORS = [
    "button:has-text('Accept all')",
    "button:has-text('Accept All')",
    "button:has-text('Accept cookies')",
    "button:has-text('Accept Cookies')",
    "button:has-text('Allow all')",
    "button:has-text('Allow All')",
    "button:has-text('I agree')",
    "button:has-text('I Accept')",
    "button:has-text('Got it')",
    "button:has-text('OK')",
    "button:has-text('Okay')",
    "button:has-text('Continue')",
    "button:has-text('Agree')",
    "button:has-text('Consent')",
    "button:has-text('Reject all')",
    "button:has-text('Reject All')",
    "button:has-text('Decline')",
    "button:has-text('Only necessary')",
    "button:has-text('Essential only')",
    "[id*='accept-cookies']",
    "[id*='cookie-accept']",
    "[id*='gdpr-accept']",
    "[id*='consent-accept']",
    "[class*='cookie-accept']",
    "[class*='accept-cookie']",
    "[data-testid*='cookie-accept']",
    "[data-testid*='accept-cookies']",
    "#onetrust-accept-btn-handler",
    ".onetrust-accept-btn-handler",
    "#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll",
    "#cookieconsent-button-accept",
    ".cc-accept",
    ".cc-allow",
    ".cc-dismiss",
    "#accept-cookies",
    "#cookie-consent-accept",
    ".cookie-consent-accept",
    "[aria-label='Accept cookies']",
    "[aria-label='Accept all cookies']",
]

POPUP_CLOSE_SELECTORS = [
    "button:has-text('Close')",
    "button:has-text('×')",
    "button:has-text('X')",
    "button:has-text('No thanks')",
    "button:has-text('No, thanks')",
    "button:has-text('Not now')",
    "button:has-text('Maybe later')",
    "button:has-text('Skip')",
    "button:has-text('Dismiss')",
    "[aria-label='Close']",
    "[aria-label='close']",
    "[aria-label='Dismiss']",
    "[title='Close']",
    "[title='close']",
    ".modal-close",
    ".popup-close",
    ".close-button",
    ".close-btn",
    ".dismiss-button",
    "[class*='close-modal']",
    "[class*='modal-close']",
    "[class*='popup-close']",
    "[class*='newsletter-close']",
    "[data-dismiss='modal']",
    "[data-close]",
    "button svg[class*='close']",
    "button[class*='close'] svg",
]

OVERLAY_SELECTORS = [
    "[class*='cookie-banner']",
    "[class*='cookie-notice']",
    "[class*='cookie-consent']",
    "[class*='gdpr-banner']",
    "[class*='newsletter-popup']",
    "[class*='newsletter-modal']",
    "[class*='email-popup']",
    "[class*='subscribe-popup']",
    "[class*='overlay-modal']",
    "[id*='cookie-banner']",
    "[id*='cookie-notice']",
    "[id*='newsletter-popup']",
    "#onetrust-consent-sdk",
    "#CybotCookiebotDialog",
    ".modal-backdrop",
    ".overlay-backdrop",
]


async def _wait_for_page_ready(page: Page) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=10_000)
    except PlaywrightTimeoutError:
        pass

    try:
        await page.wait_for_load_state("networkidle", timeout=5_000)
    except PlaywrightTimeoutError:
        pass


async def _handle_cookie_consent(page: Page) -> bool:
    for selector in COOKIE_SELECTORS:
        try:
            button = page.locator(selector).first
            if await button.is_visible(timeout=500):
                await button.click(timeout=3_000)
                await asyncio.sleep(0.5)
                return True
        except Exception:
            continue
    return False


async def _handle_popups(page: Page) -> int:
    async def _should_click_popup_target(locator) -> bool:
        try:
            return bool(
                await locator.evaluate(
                    """
                    (element) => {
                      if (!(element instanceof Element)) return false;

                      const text = (
                        element.textContent ||
                        element.getAttribute('aria-label') ||
                        element.getAttribute('title') ||
                        ''
                      ).replace(/\\s+/g, ' ').trim().toLowerCase();
                      const className = typeof element.className === 'string' ? element.className.toLowerCase() : '';
                      const id = (element.id || '').toLowerCase();
                      const ariaLabel = (element.getAttribute('aria-label') || '').toLowerCase();

                      const blockedText = new Set([
                        'next', 'previous', 'prev', 'back', 'more', 'load more', 'show more',
                        '1', '2', '3', '4', '5', '6', '7', '8', '9'
                      ]);
                      if (blockedText.has(text)) return false;

                      const paginationLike = /pagination|pager|page-numbers|page-item|paginate|next|previous|prev/;
                      if (
                        paginationLike.test(className) ||
                        paginationLike.test(id) ||
                        paginationLike.test(ariaLabel)
                      ) {
                        return false;
                      }

                      const navLikeAncestor = element.closest('nav, [role="navigation"], .pagination, .pager, .page-numbers, .paginate');
                      if (navLikeAncestor) return false;

                      const modalAncestor = element.closest(
                        [
                          '[role="dialog"]',
                          '[aria-modal="true"]',
                          '.modal',
                          '.popup',
                          '.overlay',
                          '.newsletter',
                          '.cookie',
                          '[class*="modal"]',
                          '[class*="popup"]',
                          '[class*="overlay"]',
                          '[class*="newsletter"]',
                          '[class*="cookie"]',
                          '[id*="modal"]',
                          '[id*="popup"]',
                          '[id*="overlay"]',
                          '[id*="newsletter"]',
                          '[id*="cookie"]'
                        ].join(',')
                      );

                      if (modalAncestor) return true;

                      const fixedAncestor = (() => {
                        let current = element;
                        while (current instanceof Element) {
                          const style = window.getComputedStyle(current);
                          if (style.position === 'fixed' || style.position === 'sticky') {
                            const rect = current.getBoundingClientRect();
                            if (rect.width > window.innerWidth * 0.25 || rect.height > window.innerHeight * 0.15) {
                              return current;
                            }
                          }
                          current = current.parentElement;
                        }
                        return null;
                      })();

                      return Boolean(fixedAncestor);
                    }
                    """
                )
            )
        except Exception:
            return False

    closed_count = 0
    for selector in POPUP_CLOSE_SELECTORS:
        try:
            buttons = page.locator(selector)
            count = await buttons.count()
            for index in range(min(count, 3)):
                try:
                    button = buttons.nth(index)
                    if await button.is_visible(timeout=300) and await _should_click_popup_target(button):
                        await button.click(timeout=2_000)
                        closed_count += 1
                        await asyncio.sleep(0.3)
                except Exception:
                    continue
        except Exception:
            continue
    logger.info("popups_handled closed_count=%s", closed_count)
    return closed_count


async def _remove_overlays(page: Page) -> int:
    removed_count = 0
    for selector in OVERLAY_SELECTORS:
        try:
            count = await page.evaluate(
                """
                (selector) => {
                  const elements = document.querySelectorAll(selector);
                  let removed = 0;
                  elements.forEach((element) => {
                    element.remove();
                    removed += 1;
                  });
                  return removed;
                }
                """,
                selector,
            )
            removed_count += int(count or 0)
        except Exception:
            continue
    return removed_count


async def _scroll_to_load_content(page: Page, scroll_delay: float = 0.5) -> dict[str, int]:
    try:
        scroll_height = await page.evaluate("document.body.scrollHeight")
        viewport_height = await page.evaluate("window.innerHeight")
        current_position = 0
        scroll_count = 0

        while current_position < scroll_height:
            current_position += viewport_height
            await page.evaluate("(position) => window.scrollTo(0, position)", current_position)
            await asyncio.sleep(scroll_delay)
            scroll_count += 1

            new_height = await page.evaluate("document.body.scrollHeight")
            if new_height > scroll_height:
                scroll_height = new_height

        await page.evaluate("window.scrollTo(0, 0)")
        return {"scroll_count": scroll_count, "final_height": int(scroll_height or 0)}
    except Exception:
        return {"scroll_count": 0, "final_height": 0}


async def prepare_page_for_extraction(page: Page | None) -> dict[str, Any]:
    if page is None:
        return {
            "page_ready": False,
            "cookie_handled": False,
            "popups_closed": 0,
            "overlays_removed": 0,
            "scroll_count": 0,
            "final_wait_seconds": 0.0,
        }

    await _wait_for_page_ready(page)
    cookie_handled = await _handle_cookie_consent(page)
    popups_closed = await _handle_popups(page)
    overlays_removed = await _remove_overlays(page)
    scroll_result = await _scroll_to_load_content(page)


    await asyncio.sleep(1.0)

    logger.info(
        "page_prepared cookie_handled=%s popups_closed=%s overlays_removed=%s scroll_count=%s",
        cookie_handled,
        popups_closed,
        overlays_removed,
        scroll_result["scroll_count"],
    )
    return {
        "page_ready": True,
        "cookie_handled": cookie_handled,
        "popups_closed": popups_closed,
        "overlays_removed": overlays_removed,
        "scroll_count": scroll_result["scroll_count"],
        "final_scroll_height": scroll_result["final_height"],
        "final_wait_seconds": 1.0,
    }


async def extract_page_content(
    page: Page | None,
    sections: list[str] | None = None,
    custom_script: str | None = None,
) -> ExtractedPageContent | None:
    if page is None:
        return None

    preparation = await prepare_page_for_extraction(page)
    script = custom_script or await extract_page_markdown()
    extraction_sections = sections or ["body"]
    result: Any = await page.evaluate(script, {"sections": extraction_sections})
    
    if not isinstance(result, dict):
        return None

    title = await page.title()
    page_url = str(result.get("page_url", "") or page.url or "")
    content = str(result.get("content", "") or "")
    selector_map = result.get("selector_map", {})
    logger.info("content_extracted page_url=%s markdown_length=%s", page_url, len(content))
    return {
        "title": title or "",
        "url": page_url,
        "markdown": content,
        "metadata": {
            "sections": extraction_sections,
            "selector_map": dict(selector_map or {}),
            "preparation": preparation,
        },
    }

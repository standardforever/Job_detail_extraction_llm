from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

try:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright
except Exception:  # pragma: no cover - handled gracefully at runtime
    Browser = BrowserContext = Page = Playwright = None
    async_playwright = None

try:
    from selenium import webdriver
    from selenium.common.exceptions import WebDriverException
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.remote.webdriver import WebDriver
except Exception:  # pragma: no cover - handled gracefully at runtime
    webdriver = None
    WebDriverException = Exception
    Options = None
    WebDriver = None


@dataclass(slots=True)
class BrowserSession:
    session_id: str
    cdp_url: str
    playwright: Playwright
    browser: Browser
    context: BrowserContext
    page: Page


@dataclass(slots=True)
class SessionBootstrapResult:
    session_id: str
    cdp_url: str
    reused_existing_session: bool


def _normalize_grid_url(raw_url: str) -> tuple[str, str, str]:
    url = (raw_url or "").strip()
    if not url:
        url = "http://127.0.0.1:4445/wd/hub"
    if not url.startswith(("http://", "https://")):
        url = f"http://{url}"

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid Selenium URL: {raw_url}")

    executor_url = url
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    cdp_host = parsed.netloc
    return executor_url, base_url, f"{ws_scheme}://{cdp_host}"


def _get_active_grid_sessions(base_url: str) -> list:
    try:
        response = requests.get(f"{base_url}/status", timeout=5)
        if response.status_code != 200:
            return []

        nodes = response.json().get("value", {}).get("nodes", [])
        active_sessions = []
        for node in nodes:
            for slot in node.get("slots", []):
                session = slot.get("session")
                if session is not None:
                    active_sessions.append(session.get("sessionId"))

        return active_sessions

    except Exception as e:
        print(f"[create_session] ⚠️ Could not fetch grid sessions: {e}")
        return []


def _build_stealth_options() -> Options:
    if Options is None:
        raise RuntimeError("selenium is not installed")

    options = Options()
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
    return options


def patch_webdriver_flag(driver: WebDriver) -> None:
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """
    })


def create_session(
    grid_url: str | None = None,
) -> SessionBootstrapResult | None:
    raw_grid = grid_url or os.getenv("SELENIUM_REMOTE_URL") or "http://127.0.0.1:4445/wd/hub"

    try:
        executor_url, base_url, cdp_base = _normalize_grid_url(raw_grid)
    except Exception as exc:
        print(f"[create_session] Invalid grid URL {raw_grid}: {exc}")
        return None

    print(f"[create_session] Connecting to Grid: {base_url}")
    existing_sessions = _get_active_grid_sessions(base_url)
    if existing_sessions:
        print(f"[create_session] Active grid sessions detected: {len(existing_sessions)}")
        reused_session_id = str(existing_sessions[0])
        cdp_url = f"{cdp_base}/session/{reused_session_id}/se/cdp"
        print(f"[create_session] Reusing active grid session: {reused_session_id}")
        print(f"[create_session] CDP URL: {cdp_url}")
        return SessionBootstrapResult(
            session_id=reused_session_id,
            cdp_url=cdp_url,
            reused_existing_session=True,
        )

    if webdriver is None:
        print("[create_session] selenium is not installed, cannot create a new session")
        return None

    try:
        driver = webdriver.Remote(
            command_executor=executor_url,
            options=_build_stealth_options(),
        )
        patch_webdriver_flag(driver)
        cdp_url = f"{cdp_base}/session/{driver.session_id}/se/cdp"
        print(f"[create_session] Session created: {driver.session_id}")
        print(f"[create_session] CDP URL: {cdp_url}")
        return SessionBootstrapResult(
            session_id=driver.session_id,
            cdp_url=cdp_url,
            reused_existing_session=False,
        )
    except WebDriverException as exc:
        print(f"[create_session] WebDriverException: {exc}")
        return None
    except Exception as exc:
        print(f"[create_session] Unexpected error: {exc}")
        return None


async def create_session_async(
    grid_url: str | None = None,
) -> SessionBootstrapResult | None:
    try:
        return await asyncio.wait_for(asyncio.to_thread(create_session, grid_url), timeout=45)
    except asyncio.TimeoutError:
        print("[create_session] Timed out while creating or locating a grid session")
        return None


async def attach_playwright_to_cdp(cdp_url: str) -> BrowserSession | None:
    if async_playwright is None:
        print("[browser_session] playwright is not installed")
        return None

    try:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.connect_over_cdp(cdp_url)
        contexts = browser.contexts
        if contexts:
            context = contexts[0]
        else:
            context = await browser.new_context()
        context.set_default_navigation_timeout(30_000)
        context.set_default_timeout(30_000)
        page = await context.new_page()
        await page.bring_to_front()
        return BrowserSession(
            session_id=cdp_url.rstrip("/").split("/")[-3],
            cdp_url=cdp_url,
            playwright=playwright,
            browser=browser,
            context=context,
            page=page,
        )
    except Exception as exc:
        print(f"[browser_session] Unable to attach Playwright over CDP: {exc}")
        return None


async def close_agent_tab(session: BrowserSession | None) -> None:
    if session is None:
        return

    try:
        if not session.page.is_closed():
            await session.page.close()
    except Exception:
        pass

    try:
        await session.playwright.stop()
    except Exception:
        pass

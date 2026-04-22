"""
list_cdp_tabs.py
----------------
Lists all active sessions and their open tabs via Selenium Grid + CDP.
Matches the grid_session.py pattern exactly.

Usage:
    python list_cdp_tabs.py
    python list_cdp_tabs.py --grid-url http://127.0.0.1:4445/wd/hub
"""

from __future__ import annotations

import asyncio
import argparse
import json
import os
from urllib.parse import urlparse

import requests

try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None


# ---------------------------------------------------------------------------
# Helpers (mirrors grid_session.py logic exactly)
# ---------------------------------------------------------------------------

def _normalize_grid_url(raw_url: str) -> tuple[str, str, str]:
    """Return (executor_url, base_url, cdp_base_ws)."""
    url = (raw_url or "").strip()
    if not url:
        url = "http://127.0.0.1:4445/wd/hub"
    if not url.startswith(("http://", "https://")):
        url = f"http://{url}"

    parsed = urlparse(url)
    executor_url = url
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    ws_scheme = "wss" if parsed.scheme == "https" else "ws"
    cdp_base = f"{ws_scheme}://{parsed.netloc}"
    return executor_url, base_url, cdp_base


def _get_all_grid_sessions(base_url: str) -> list[dict]:
    """Return every active session ID from the Selenium Grid /status endpoint."""
    try:
        resp = requests.get(f"{base_url}/status", timeout=5)
        resp.raise_for_status()
        nodes = resp.json().get("value", {}).get("nodes", [])
        sessions = []
        for node in nodes:
            for slot in node.get("slots", []):
                session = slot.get("session")
                if session and session.get("sessionId"):
                    sessions.append({
                        "session_id": session["sessionId"],
                        "stereotype": slot.get("stereotype", {}),
                        "uri":        node.get("uri", ""),
                    })
        return sessions
    except Exception as e:
        print(f"❌ Could not reach grid /status: {e}")
        return []


def _build_cdp_url(cdp_base: str, session_id: str) -> str:
    """Build the CDP WebSocket URL the same way grid_session.py does."""
    return f"{cdp_base}/session/{session_id}/se/cdp"


# ---------------------------------------------------------------------------
# Per-session tab listing via Playwright CDP
# ---------------------------------------------------------------------------

async def _list_tabs_for_session(cdp_url: str) -> list[dict]:
    """Attach Playwright over CDP and return all pages in the session."""
    if async_playwright is None:
        print("  ⚠️  playwright not installed — cannot list individual tabs")
        return []

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(cdp_url)
            tabs = []
            for ctx_index, context in enumerate(browser.contexts):
                for page_index, page in enumerate(context.pages):
                    tabs.append({
                        "context_index": ctx_index,
                        "page_index":    page_index,
                        "url":           page.url,
                        "title":         await page.title(),
                    })
            await browser.close()
            return tabs
    except Exception as e:
        print(f"  ⚠️  Could not attach Playwright to {cdp_url}: {e}")
        return []


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main(grid_url: str) -> None:
    _, base_url, cdp_base = _normalize_grid_url(grid_url)

    print(f"\n🔌 Connecting to Selenium Grid at {base_url} ...\n")

    # 1. Get all active sessions from the grid
    sessions = _get_all_grid_sessions(base_url)

    if not sessions:
        print("⚠️  No active sessions found on the grid.")
        print("   Make sure at least one Selenium session is running.")
        return

    print("=" * 60)
    print(f"ACTIVE GRID SESSIONS  ({len(sessions)} found)")
    print("=" * 60)

    output = {
        "grid_url":      grid_url,
        "base_url":      base_url,
        "session_count": len(sessions),
        "sessions":      [],
    }

    # 2. For each session, build its CDP URL and list all tabs
    for i, sess in enumerate(sessions, start=1):
        session_id = sess["session_id"]
        cdp_url    = _build_cdp_url(cdp_base, session_id)

        print(f"\n[Session {i}]")
        print(f"  Session ID : {session_id}")
        print(f"  Node URI   : {sess['uri']}")
        print(f"  CDP URL    : {cdp_url}")

        tabs = await _list_tabs_for_session(cdp_url)

        if tabs:
            print(f"  Tabs ({len(tabs)}):")
            for tab in tabs:
                print(f"    [{tab['context_index']}:{tab['page_index']}] {tab['title'] or '(no title)'}")
                print(f"           {tab['url']}")
        else:
            print("  Tabs: (none found or Playwright unavailable)")

        output["sessions"].append({
            "index":      i,
            "session_id": session_id,
            "cdp_url":    cdp_url,
            "node_uri":   sess["uri"],
            "tabs":       tabs,
        })

    print("\n" + "=" * 60)

    # 3. Save full result to JSON
    out_path = "cdp_tabs.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    total_tabs = sum(len(s["tabs"]) for s in output["sessions"])
    print(f"\n✅ Done. {len(sessions)} session(s), {total_tabs} tab(s) total.")
    print(f"   Saved to: {out_path}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="List all tabs from Selenium Grid CDP sessions.")
    parser.add_argument(
        "--grid-url",
        default=os.getenv("SELENIUM_REMOTE_URL", "http://127.0.0.1:4445/wd/hub"),
        help="Selenium Grid URL (default: http://127.0.0.1:4445/wd/hub)",
    )
    args = parser.parse_args()
    asyncio.run(main(args.grid_url))
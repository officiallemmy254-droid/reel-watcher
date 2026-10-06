"""Chrome DevTools Protocol (CDP) live saved reels harvester.

Discovers active Instagram tabs in the user's running Chrome browser (CDP port 9222),
attaches via WebSocket (Runtime.evaluate), executes gentle human scroll gestures,
extracts saved reel links, and synchronizes them into the Vault.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import time
from typing import Any

import httpx

from reel_watcher.config import format_status
from reel_watcher.db import Vault


def extract_reel_codes_from_html(html: str) -> list[str]:
    """Extract unique Instagram reel/post shortcodes from HTML markup.

    Preserves document order and deduplicates codes. Matches:
    - /reel/<code/
    - /reels/<code/
    - /p/<code/
    - /share/reel/<code/
    - Absolute URLs: https://www.instagram.com/reel/<code/

    Parameters
    ----------
    html : str
        HTML markup or text containing Instagram anchor links.

    Returns
    -------
    list[str]
        Ordered list of unique extracted shortcodes.
    """
    if not html or not isinstance(html, str):
        return []

    # Regex targeting <a> tag href attributes
    anchor_pattern = re.compile(
        r'<a\b[^>]*?href=["\']([^"\']+)["\']',
        re.IGNORECASE,
    )

    # Regex targeting Instagram reel/post shortcodes
    code_pattern = re.compile(
        r"(?:/(?:reel|reels|p|share/reel)/)([A-Za-z0-9_-]+)",
        re.IGNORECASE,
    )

    codes: list[str] = []
    seen: set[str] = set()

    for match in anchor_pattern.finditer(html):
        href = match.group(1).strip()
        code_match = code_pattern.search(href)
        if code_match:
            code = code_match.group(1)
            if code not in seen:
                seen.add(code)
                codes.append(code)

    # Fallback: if no anchor tags matched, scan plain string for reel paths
    if not codes:
        for code_match in code_pattern.finditer(html):
            code = code_match.group(1)
            if code not in seen:
                seen.add(code)
                codes.append(code)

    return codes


def get_active_instagram_tabs(cdp_base: str = "http://127.0.0.1:9222") -> list[dict]:
    """Query CDP targets list and filter for active Instagram page sessions.

    Parameters
    ----------
    cdp_base : str
        Base HTTP URL of the Chrome DevTools Protocol endpoint.

    Returns
    -------
    list[dict]
        List of target objects representing active Instagram tabs.
    """
    clean_base = cdp_base.rstrip("/")
    endpoint = f"{clean_base}/json"

    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(endpoint)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        print(format_status("warning", f"Unable to reach Chrome CDP at {endpoint}: {exc}"))
        return []

    if not isinstance(data, list):
        print(format_status("warning", f"CDP endpoint {endpoint} returned non-list response: {data}"))
        return []

    instagram_tabs: list[dict] = []
    for target in data:
        if not isinstance(target, dict):
            continue
        # Only inspect page-type targets (ignore background_page, service_worker, etc.)
        target_type = target.get("type", "page")
        if target_type != "page":
            continue
        url = str(target.get("url", ""))
        if "instagram.com" in url.lower():
            instagram_tabs.append(target)

    if instagram_tabs:
        print(format_status("success", f"Discovered {len(instagram_tabs)} active Instagram tab(s)."))
    else:
        print(format_status("info", "No active Instagram tabs found."))

    return instagram_tabs


class CDPSession:
    """Manages a synchronous CDP connection over WebSocket or HTTP."""

    def __init__(self, ws_url: str, timeout: float = 10.0) -> None:
        """Initialize CDP session with target WebSocket or HTTP evaluation URL."""
        self.ws_url = ws_url
        self.timeout = timeout
        self._ws: Any = None
        self._msg_id: int = 0

    def connect(self) -> None:
        """Establish connection to the target."""
        if self.ws_url.startswith(("http://", "https://")):
            return

        import websockets.sync.client

        self._ws = websockets.sync.client.connect(
            self.ws_url,
            open_timeout=self.timeout,
            close_timeout=self.timeout,
        )

    def close(self) -> None:
        """Close connection if open."""
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    def __enter__(self) -> CDPSession:
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        self.close()

    def evaluate(self, expression: str) -> Any:
        """Evaluate JavaScript expression in target page and return the result value."""
        self._msg_id += 1
        call_id = self._msg_id

        payload = {
            "id": call_id,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        }

        # HTTP evaluation fallback / mock path
        if self.ws_url.startswith(("http://", "https://")):
            resp = httpx.post(self.ws_url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            result = data.get("result", {})
            if "exceptionDetails" in result:
                exc_desc = result["exceptionDetails"].get("text", "JS exception")
                raise RuntimeError(f"CDP evaluation exception: {exc_desc}")
            return result.get("result", {}).get("value")

        # WebSocket path
        if self._ws is None:
            self.connect()

        self._ws.send(json.dumps(payload))
        start_time = time.time()
        while time.time() - start_time < self.timeout:
            remaining = max(0.5, self.timeout - (time.time() - start_time))
            raw = self._ws.recv(timeout=remaining)
            data = json.loads(raw)
            if data.get("id") == call_id:
                result = data.get("result", {})
                if "exceptionDetails" in result:
                    exc_desc = result["exceptionDetails"].get("text", "JS exception")
                    raise RuntimeError(f"CDP evaluation exception: {exc_desc}")
                return result.get("result", {}).get("value")

        raise TimeoutError(f"CDP evaluation timed out after {self.timeout}s")


def harvest_saved_reels_via_cdp(
    cdp_base: str = "http://127.0.0.1:9222",
    target_collection: str = "all-posts",
    max_scrolls: int = 5,
    vault: Vault | None = None,
    scroll_delay: float = 0.5,
) -> list[dict]:
    """Discover saved reels from the active Instagram tab via CDP, scroll, and harvest.

    Parameters
    ----------
    cdp_base : str
        CDP base HTTP URL (default: "http://127.0.0.1:9222").
    target_collection : str
        Collection tag for harvested reels (default: "all-posts").
    max_scrolls : int
        Number of scroll operations to perform (default: 5).
    vault : Vault | None
        Optional Vault instance to enqueue harvested reels.
    scroll_delay : float
        Delay in seconds between scrolls to allow content loading (default: 0.5).

    Returns
    -------
    list[dict]
        Harvested reels as [{"code": str, "url": str, "collection": str}].
    """
    print(format_status("info", f"Querying Chrome CDP at {cdp_base} for active Instagram tabs..."))
    tabs = get_active_instagram_tabs(cdp_base=cdp_base)
    if not tabs:
        print(format_status("error", "No active Instagram tab found on CDP port."))
        return []

    # Prioritize tab matching target collection or /saved/
    chosen_tab: dict | None = None
    coll_keyword = (target_collection or "").lower()

    for tab in tabs:
        url_lower = str(tab.get("url", "")).lower()
        if coll_keyword and coll_keyword in url_lower:
            chosen_tab = tab
            break

    if chosen_tab is None:
        for tab in tabs:
            url_lower = str(tab.get("url", "")).lower()
            if "/saved" in url_lower:
                chosen_tab = tab
                break

    if chosen_tab is None:
        chosen_tab = tabs[0]

    title = chosen_tab.get("title", "")
    target_url = chosen_tab.get("url", "")
    print(format_status("success", f"Targeting Instagram tab: '{title}' ({target_url})"))

    ws_url = chosen_tab.get("webSocketDebuggerUrl")
    if not ws_url:
        print(format_status("error", f"Target tab '{chosen_tab.get('id')}' has no webSocketDebuggerUrl."))
        return []

    harvested: list[dict] = []
    seen_codes: set[str] = set()

    try:
        with CDPSession(ws_url) as session:
            # 1. Initial page extraction
            html = session.evaluate(
                "document.documentElement ? document.documentElement.outerHTML : document.body.innerHTML"
            )
            initial_codes = extract_reel_codes_from_html(html or "")
            for code in initial_codes:
                if code not in seen_codes:
                    seen_codes.add(code)
                    item = {
                        "code": code,
                        "url": f"https://www.instagram.com/reel/{code}/",
                        "collection": target_collection,
                    }
                    harvested.append(item)
                    if vault is not None:
                        enqueued = vault.enqueue_url(url=item["url"], collection=target_collection)
                        if enqueued:
                            print(format_status("success", f"Enqueued reel {code} into vault (collection: {target_collection})"))
                        else:
                            print(format_status("info", f"Reel {code} already exists in vault queue or studies"))

            print(format_status("info", f"Initial page inspection found {len(seen_codes)} unique reel(s)."))

            # 2. Emulate gentle scrolling
            scroll_script = (
                "(() => {"
                "  window.scrollBy(0, Math.floor(window.innerHeight * 1.2));"
                "  const m = document.querySelector('main');"
                "  if (m) { m.scrollTop += Math.floor(window.innerHeight * 1.2); }"
                "})()"
            )

            for scroll_idx in range(1, max_scrolls + 1):
                print(format_status("info", f"Emulating human scroll ({scroll_idx}/{max_scrolls})..."))
                try:
                    session.evaluate(scroll_script)
                except Exception as exc:
                    print(format_status("warning", f"Scroll execution warning: {exc}"))

                if scroll_delay > 0:
                    time.sleep(scroll_delay)

                try:
                    html = session.evaluate(
                        "document.documentElement ? document.documentElement.outerHTML : document.body.innerHTML"
                    )
                    new_codes = extract_reel_codes_from_html(html or "")
                    new_count = 0
                    for code in new_codes:
                        if code not in seen_codes:
                            seen_codes.add(code)
                            new_count += 1
                            item = {
                                "code": code,
                                "url": f"https://www.instagram.com/reel/{code}/",
                                "collection": target_collection,
                            }
                            harvested.append(item)
                            if vault is not None:
                                enqueued = vault.enqueue_url(url=item["url"], collection=target_collection)
                                if enqueued:
                                    print(format_status("success", f"Enqueued reel {code} into vault (collection: {target_collection})"))
                                else:
                                    print(format_status("info", f"Reel {code} already exists in vault queue or studies"))

                    print(format_status("info", f"Scroll {scroll_idx}/{max_scrolls}: found {new_count} new reels (total: {len(seen_codes)})"))
                except Exception as exc:
                    print(format_status("warning", f"HTML extraction warning on scroll {scroll_idx}: {exc}"))

    except Exception as exc:
        print(format_status("error", f"CDP session communication failure on {ws_url}: {exc}"))
        return harvested

    print(format_status("success", f"Harvest complete. Harvested {len(harvested)} reel(s) across {max_scrolls} scroll(s)."))
    return harvested

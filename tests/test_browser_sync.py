"""Unit and integration tests for Chrome DevTools Protocol live saved reels harvester."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from reel_watcher.browser_sync import (
    CDPSession,
    extract_reel_codes_from_html,
    get_active_instagram_tabs,
    harvest_saved_reels_via_cdp,
)
from reel_watcher.db import Vault


# ============================================================================
# 1. HTML Reel Code Extraction Tests
# ============================================================================


def test_extract_reel_codes_empty_and_invalid():
    """Verify that empty, None, or non-HTML strings return empty lists."""
    assert extract_reel_codes_from_html("") == []
    assert extract_reel_codes_from_html(None) == []  # type: ignore[arg-type]
    assert extract_reel_codes_from_html("   ") == []
    assert extract_reel_codes_from_html("<div>Hello World no links here</div>") == []


def test_extract_reel_codes_various_formats():
    """Verify extraction across /reel/, /reels/, /p/, /share/reel/, and absolute URLs."""
    html = """
    <html>
      <body>
        <a href="/reel/C_abc123XYZ/">Reel 1</a>
        <a class="x1i10hfl" href="/reels/D_def456UVW/?utm_source=ig_web">Reel 2</a>
        <a href="/p/E_ghi789RST/">Post 3</a>
        <a role="link" href="/share/reel/F_jkl012OPQ/">Share Reel 4</a>
        <a href="https://www.instagram.com/reel/G_mno345LMN/">Full URL Reel 5</a>
        <a href="https://instagram.com/p/H_pqr678IJK/?next=%2F">Full URL Post 6</a>
      </body>
    </html>
    """
    codes = extract_reel_codes_from_html(html)
    assert codes == [
        "C_abc123XYZ",
        "D_def456UVW",
        "E_ghi789RST",
        "F_jkl012OPQ",
        "G_mno345LMN",
        "H_pqr678IJK",
    ]


def test_extract_reel_codes_deduplication_and_order():
    """Verify deduplication preserves first-seen order across different link forms."""
    html = """
    <div>
      <a href="/reel/DUPLICATE_CODE_1/">First occurrence</a>
      <a href="/p/DUPLICATE_CODE_2/">Second code</a>
      <a href="https://www.instagram.com/reel/DUPLICATE_CODE_1/">Duplicate of first</a>
      <a href="/share/reel/DUPLICATE_CODE_2/">Duplicate of second</a>
      <a href="/reel/UNIQUE_CODE_3/">Third code</a>
    </div>
    """
    codes = extract_reel_codes_from_html(html)
    assert codes == ["DUPLICATE_CODE_1", "DUPLICATE_CODE_2", "UNIQUE_CODE_3"]


def test_extract_reel_codes_filters_out_non_reel_links():
    """Verify non-reel anchor tags (explore, direct, settings, external) are ignored."""
    html = """
    <div>
      <a href="/explore/">Explore</a>
      <a href="/direct/inbox/">Messages</a>
      <a href="/my_username/">Profile</a>
      <a href="/accounts/edit/">Settings</a>
      <a href="https://about.instagram.com/">About</a>
      <a href="/reel/VALID_REEL_CODE/">Valid Reel</a>
      <a href="https://facebook.com/watch">Facebook</a>
    </div>
    """
    codes = extract_reel_codes_from_html(html)
    assert codes == ["VALID_REEL_CODE"]


def test_extract_reel_codes_fallback_plain_text():
    """Verify fallback extraction when markup contains plain reel URLs without <a> tags."""
    plain = "Check these out: https://instagram.com/reel/PLAIN_CODE_1/ and /p/PLAIN_CODE_2/"
    codes = extract_reel_codes_from_html(plain)
    assert codes == ["PLAIN_CODE_1", "PLAIN_CODE_2"]


# ============================================================================
# 2. Active Instagram Tabs Discovery Tests
# ============================================================================


def test_get_active_instagram_tabs_success():
    """Verify filtering of active Instagram tabs from CDP /json targets list."""
    mock_targets = [
        {
            "id": "tab1",
            "type": "page",
            "title": "Saved - Instagram",
            "url": "https://www.instagram.com/testuser/saved/all-posts/",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/tab1",
        },
        {
            "id": "tab2",
            "type": "page",
            "title": "GitHub",
            "url": "https://github.com/trending",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/tab2",
        },
        {
            "id": "tab3",
            "type": "background_page",
            "title": "Instagram Extension Background",
            "url": "https://www.instagram.com/bg",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/tab3",
        },
        {
            "id": "tab4",
            "type": "page",
            "title": "Reel - Instagram",
            "url": "https://instagram.com/reel/TEST_CODE/",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/tab4",
        },
    ]

    with patch("httpx.Client.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_targets
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        tabs = get_active_instagram_tabs("http://127.0.0.1:9222")
        assert len(tabs) == 2
        assert tabs[0]["id"] == "tab1"
        assert tabs[1]["id"] == "tab4"
        mock_get.assert_called_once_with("http://127.0.0.1:9222/json")


def test_get_active_instagram_tabs_connection_failure():
    """Verify that CDP connection failures return an empty list gracefully."""
    with patch("httpx.Client.get", side_effect=httpx.ConnectError("Connection refused")):
        tabs = get_active_instagram_tabs("http://127.0.0.1:9222")
        assert tabs == []


def test_get_active_instagram_tabs_unexpected_payload():
    """Verify handling of non-list JSON payloads from CDP."""
    with patch("httpx.Client.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"error": "unsupported"}
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        tabs = get_active_instagram_tabs("http://127.0.0.1:9222")
        assert tabs == []


# ============================================================================
# 3. CDPSession Evaluation Tests
# ============================================================================


def test_cdp_session_evaluate_websocket():
    """Verify CDPSession sends Runtime.evaluate over WebSocket and extracts return value."""
    mock_ws = MagicMock()
    mock_ws.recv.return_value = json.dumps(
        {
            "id": 1,
            "result": {
                "result": {
                    "type": "string",
                    "value": "<a href='/reel/TEST123_'>test</a>",
                }
            },
        }
    )

    with patch("websockets.sync.client.connect", return_value=mock_ws) as mock_connect:
        session = CDPSession("ws://127.0.0.1:9222/devtools/page/test")
        session.connect()

        result = session.evaluate("document.body.innerHTML")
        assert result == "<a href='/reel/TEST123_'>test</a>"

        # Verify sent payload
        sent_raw = mock_ws.send.call_args[0][0]
        sent_json = json.loads(sent_raw)
        assert sent_json["method"] == "Runtime.evaluate"
        assert sent_json["params"]["expression"] == "document.body.innerHTML"

        session.close()
        mock_ws.close.assert_called_once()


def test_cdp_session_evaluate_http():
    """Verify CDPSession sends HTTP POST when ws_url is an HTTP endpoint."""
    with patch("httpx.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "id": 1,
            "result": {
                "result": {
                    "type": "string",
                    "value": "http_result_val",
                }
            },
        }
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        with CDPSession("http://127.0.0.1:9222/json/evaluate") as session:
            val = session.evaluate("1 + 1")
            assert val == "http_result_val"
            mock_post.assert_called_once()


def test_cdp_session_evaluate_js_exception():
    """Verify CDPSession raises RuntimeError if JavaScript execution throws."""
    mock_ws = MagicMock()
    mock_ws.recv.return_value = json.dumps(
        {
            "id": 1,
            "result": {
                "exceptionDetails": {
                    "text": "Uncaught ReferenceError: foo is not defined"
                }
            },
        }
    )

    with patch("websockets.sync.client.connect", return_value=mock_ws):
        with CDPSession("ws://127.0.0.1:9222/devtools/page/test") as session:
            with pytest.raises(RuntimeError, match="Uncaught ReferenceError"):
                session.evaluate("foo.bar()")


# ============================================================================
# 4. Live Saved Reels Harvester Tests
# ============================================================================


def test_harvest_saved_reels_no_active_tabs():
    """Verify that harvest returns empty list when no Instagram tab is open."""
    with patch("reel_watcher.browser_sync.get_active_instagram_tabs", return_value=[]):
        res = harvest_saved_reels_via_cdp("http://127.0.0.1:9222")
        assert res == []


def test_harvest_saved_reels_missing_ws_url():
    """Verify that harvest returns empty list when target tab has no WebSocket URL."""
    fake_tab = [{"id": "tab1", "url": "https://instagram.com", "title": "IG"}]
    with patch("reel_watcher.browser_sync.get_active_instagram_tabs", return_value=fake_tab):
        res = harvest_saved_reels_via_cdp("http://127.0.0.1:9222")
        assert res == []


def test_harvest_saved_reels_scroll_and_deduplicate():
    """Verify scrolling loop extracts new reels and deduplicates across scroll passes."""
    fake_tab = [
        {
            "id": "tab1",
            "url": "https://www.instagram.com/user/saved/all-posts/",
            "title": "Saved Posts",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/tab1",
        }
    ]

    # HTML responses for initial page and 2 subsequent scrolls
    html_step_0 = "<div><a href='/reel/CODE_AAA/'>A</a><a href='/reel/CODE_BBB/'>B</a></div>"
    html_step_1 = "<div><a href='/reel/CODE_BBB/'>B</a><a href='/reel/CODE_CCC/'>C</a></div>"
    html_step_2 = "<div><a href='/reel/CODE_CCC/'>C</a><a href='/reel/CODE_DDD/'>D</a></div>"

    evaluate_responses = [
        html_step_0,  # initial extraction
        None,         # scroll 1 action
        html_step_1,  # scroll 1 extraction
        None,         # scroll 2 action
        html_step_2,  # scroll 2 extraction
    ]

    mock_session = MagicMock()
    mock_session.evaluate.side_effect = evaluate_responses
    mock_session.__enter__.return_value = mock_session

    with patch("reel_watcher.browser_sync.get_active_instagram_tabs", return_value=fake_tab), \
         patch("reel_watcher.browser_sync.CDPSession", return_value=mock_session):
        reels = harvest_saved_reels_via_cdp(
            cdp_base="http://127.0.0.1:9222",
            target_collection="all-posts",
            max_scrolls=2,
            scroll_delay=0.0,
        )

        assert len(reels) == 4
        codes = [r["code"] for r in reels]
        assert codes == ["CODE_AAA", "CODE_BBB", "CODE_CCC", "CODE_DDD"]
        assert all(r["collection"] == "all-posts" for r in reels)
        assert reels[0]["url"] == "https://www.instagram.com/reel/CODE_AAA/"


def test_harvest_saved_reels_with_vault_enqueuing(tmp_path: Path):
    """Verify that harvested reels are automatically enqueued into the Vault."""
    db_path = tmp_path / "test.db"
    vault = Vault(db_path=db_path, out_root=tmp_path)

    fake_tab = [
        {
            "id": "tab1",
            "url": "https://www.instagram.com/user/saved/tech-inspo/",
            "title": "Tech Inspo",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/tab1",
        }
    ]

    html_content = """
    <div>
      <a href='/reel/TECH_REEL_1/'>Tech 1</a>
      <a href='/reel/TECH_REEL_2/'>Tech 2</a>
    </div>
    """

    mock_session = MagicMock()
    mock_session.evaluate.side_effect = [html_content]
    mock_session.__enter__.return_value = mock_session

    with patch("reel_watcher.browser_sync.get_active_instagram_tabs", return_value=fake_tab), \
         patch("reel_watcher.browser_sync.CDPSession", return_value=mock_session):
        reels = harvest_saved_reels_via_cdp(
            cdp_base="http://127.0.0.1:9222",
            target_collection="tech-inspo",
            max_scrolls=0,
            vault=vault,
            scroll_delay=0.0,
        )

        assert len(reels) == 2

        # Check vault queue items
        pending = vault.get_pending_urls(limit=10)
        assert len(pending) == 2
        pending_codes = {item["shortcode"] for item in pending}
        assert pending_codes == {"TECH_REEL_1", "TECH_REEL_2"}
        assert all(item["collection"] == "tech-inspo" for item in pending)


def test_harvest_saved_reels_tab_selection_priority():
    """Verify target tab selection prioritization matching target collection."""
    tabs = [
        {
            "id": "tab_home",
            "url": "https://www.instagram.com/",
            "title": "Instagram Home",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/home",
        },
        {
            "id": "tab_saved_all",
            "url": "https://www.instagram.com/user/saved/all-posts/",
            "title": "All Posts",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/all",
        },
        {
            "id": "tab_saved_design",
            "url": "https://www.instagram.com/user/saved/design-ideas/",
            "title": "Design Ideas",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/design",
        },
    ]

    mock_session = MagicMock()
    mock_session.evaluate.return_value = "<a href='/reel/DESIGN_123/'>Design</a>"
    mock_session.__enter__.return_value = mock_session

    with patch("reel_watcher.browser_sync.get_active_instagram_tabs", return_value=tabs), \
         patch("reel_watcher.browser_sync.CDPSession") as mock_session_cls:
        mock_session_cls.return_value = mock_session

        # When asking for design-ideas
        harvest_saved_reels_via_cdp(
            target_collection="design-ideas",
            max_scrolls=0,
            scroll_delay=0.0,
        )
        mock_session_cls.assert_called_with("ws://127.0.0.1:9222/devtools/page/design")


def test_harvest_saved_reels_connection_error_handling():
    """Verify that WebSocket connection failures during harvest are handled cleanly."""
    fake_tab = [
        {
            "id": "tab1",
            "url": "https://www.instagram.com/user/saved/all-posts/",
            "title": "Saved",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/tab1",
        }
    ]

    with patch("reel_watcher.browser_sync.get_active_instagram_tabs", return_value=fake_tab), \
         patch("websockets.sync.client.connect", side_effect=ConnectionRefusedError("WS Refused")):
        reels = harvest_saved_reels_via_cdp(
            cdp_base="http://127.0.0.1:9222",
            target_collection="all-posts",
            max_scrolls=1,
            scroll_delay=0.0,
        )
        assert reels == []

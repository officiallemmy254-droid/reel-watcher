"""Unit and integration tests for Playbook Web Dashboard and API (`server.py`)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from reel_watcher.cli import build_parser, main
from reel_watcher.db import Vault


@pytest.fixture
def test_vault(tmp_path: Path) -> Vault:
    """Create an isolated test Vault with SQLite db and output root."""
    db_path = tmp_path / "test_vault.db"
    out_root = tmp_path / "vault_out"
    out_root.mkdir(parents=True, exist_ok=True)
    return Vault(db_path=db_path, out_root=out_root)


@pytest.fixture
def sample_studies(test_vault: Vault) -> dict[str, dict]:
    """Populate test vault with sample video and carousel studies."""
    video_study = {
        "code": "VID123",
        "shortcode": "VID123",
        "url": "https://www.instagram.com/reel/VID123/",
        "title": "Scaling Organic Reach With Reels",
        "author": "growth_hacker",
        "collection": "growth",
        "duration": 28.5,
        "media_type": "video",
        "hook_text": "Stop posting reels without this framework",
        "summary": "Video deconstruction analyzing high-retention hook patterns.",
        "framework": "Problem-Agitate-Solve",
        "score": 9.2,
        "cuts": [2.1, 5.4, 10.2],
        "cuts_count": 3,
        "giveaway": {
            "has_giveaway": True,
            "type": "comment_funnel",
            "trigger_words": ["SCALE", "GROWTH"],
            "destination": "DM",
        },
        "visual_analysis": {
            "hook": {"text": "Stop posting reels without this framework"},
            "score": 9.2,
        },
    }

    carousel_study = {
        "code": "CAR456",
        "shortcode": "CAR456",
        "url": "https://www.instagram.com/p/CAR456/",
        "title": "Minimalist Design Systems Blueprint",
        "author": "design_pro",
        "collection": "design",
        "media_type": "carousel",
        "slides_count": 7,
        "slides": ["slide1.jpg", "slide2.jpg"],
        "hook_text": "How Apple designs interfaces that convert",
        "summary": "Carousel teardown of clean visual hierarchies.",
        "framework": "AIDA",
        "score": 8.5,
        "giveaway": {
            "has_giveaway": False,
            "type": "none",
            "trigger_words": [],
            "destination": "",
        },
        "visual_analysis": {
            "hook": {"text": "How Apple designs interfaces that convert"},
            "score": 8.5,
        },
    }

    test_vault.save_study(video_study)
    test_vault.save_study(carousel_study)
    return {"video": video_study, "carousel": carousel_study}


# ==============================================================================
# 1. create_app and Root HTML Endpoint Tests
# ==============================================================================


def test_create_app_initialization(test_vault: Vault) -> None:
    """Verify create_app instantiates a valid FastAPI app with attached vault."""
    from reel_watcher.web.server import create_app

    app = create_app(vault=test_vault)
    assert app is not None
    assert app.title == "Reel-Watcher Playbook API"


def test_get_root_serves_html(test_vault: Vault) -> None:
    """Verify GET / returns 200 and static dashboard HTML content."""
    from reel_watcher.web.server import create_app

    app = create_app(vault=test_vault)
    client = TestClient(app)

    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Reel-Watcher Playbook" in response.text


# ==============================================================================
# 2. /api/studies List and Filter Tests
# ==============================================================================


def test_get_studies_empty(test_vault: Vault) -> None:
    """Verify GET /api/studies returns empty list when no studies exist."""
    from reel_watcher.web.server import create_app

    app = create_app(vault=test_vault)
    client = TestClient(app)

    response = client.get("/api/studies")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 0


def test_get_studies_all(test_vault: Vault, sample_studies: dict[str, dict]) -> None:
    """Verify GET /api/studies returns all populated studies."""
    from reel_watcher.web.server import create_app

    app = create_app(vault=test_vault)
    client = TestClient(app)

    response = client.get("/api/studies")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    codes = {s["code"] for s in data}
    assert codes == {"VID123", "CAR456"}


def test_get_studies_filter_by_query(
    test_vault: Vault, sample_studies: dict[str, dict]
) -> None:
    """Verify GET /api/studies?query= searches across title, hook, author, framework."""
    from reel_watcher.web.server import create_app

    app = create_app(vault=test_vault)
    client = TestClient(app)

    # Search by title keyword
    r1 = client.get("/api/studies?query=Scaling")
    assert r1.status_code == 200
    d1 = r1.json()
    assert len(d1) == 1
    assert d1[0]["code"] == "VID123"

    # Search by author keyword
    r2 = client.get("/api/studies?query=design_pro")
    assert r2.status_code == 200
    d2 = r2.json()
    assert len(d2) == 1
    assert d2[0]["code"] == "CAR456"

    # Search non-matching query
    r3 = client.get("/api/studies?query=nonexistent_xyz")
    assert r3.status_code == 200
    assert len(r3.json()) == 0


def test_get_studies_filter_by_format(
    test_vault: Vault, sample_studies: dict[str, dict]
) -> None:
    """Verify GET /api/studies?format= filters video vs carousel."""
    from reel_watcher.web.server import create_app

    app = create_app(vault=test_vault)
    client = TestClient(app)

    # Video filter
    r_vid = client.get("/api/studies?format=video")
    assert r_vid.status_code == 200
    d_vid = r_vid.json()
    assert len(d_vid) == 1
    assert d_vid[0]["code"] == "VID123"

    # Carousel filter
    r_car = client.get("/api/studies?format=carousel")
    assert r_car.status_code == 200
    d_car = r_car.json()
    assert len(d_car) == 1
    assert d_car[0]["code"] == "CAR456"


def test_get_studies_filter_by_giveaway(
    test_vault: Vault, sample_studies: dict[str, dict]
) -> None:
    """Verify GET /api/studies?giveaway=true/false filters giveaway funnels."""
    from reel_watcher.web.server import create_app

    app = create_app(vault=test_vault)
    client = TestClient(app)

    # Giveaway true
    r_gw_true = client.get("/api/studies?giveaway=true")
    assert r_gw_true.status_code == 200
    d_gw_true = r_gw_true.json()
    assert len(d_gw_true) == 1
    assert d_gw_true[0]["code"] == "VID123"

    # Giveaway false
    r_gw_false = client.get("/api/studies?giveaway=false")
    assert r_gw_false.status_code == 200
    d_gw_false = r_gw_false.json()
    assert len(d_gw_false) == 1
    assert d_gw_false[0]["code"] == "CAR456"


# ==============================================================================
# 3. /api/studies/{code} Single Item Tests
# ==============================================================================


def test_get_study_by_code_success(
    test_vault: Vault, sample_studies: dict[str, dict]
) -> None:
    """Verify GET /api/studies/{code} returns complete record for existing study."""
    from reel_watcher.web.server import create_app

    app = create_app(vault=test_vault)
    client = TestClient(app)

    response = client.get("/api/studies/VID123")
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == "VID123"
    assert data["title"] == "Scaling Organic Reach With Reels"
    assert data["score"] == 9.2
    assert data["framework"] == "Problem-Agitate-Solve"


def test_get_study_by_code_not_found(test_vault: Vault) -> None:
    """Verify GET /api/studies/{code} returns 404 for nonexistent code."""
    from reel_watcher.web.server import create_app

    app = create_app(vault=test_vault)
    client = TestClient(app)

    response = client.get("/api/studies/NONEXISTENT")
    assert response.status_code == 404
    data = response.json()
    assert "not found" in data["detail"].lower()


# ==============================================================================
# 4. /api/enqueue Tests
# ==============================================================================


def test_enqueue_url_success(test_vault: Vault) -> None:
    """Verify POST /api/enqueue enqueues a new reel URL."""
    from reel_watcher.web.server import create_app

    app = create_app(vault=test_vault)
    client = TestClient(app)

    payload = {
        "url": "https://www.instagram.com/reel/ENQUEUE123/",
        "collection": "growth_inbox",
    }
    response = client.post("/api/enqueue", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "enqueued"
    assert data["shortcode"] == "ENQUEUE123"

    # Verify queue in vault
    pending = test_vault.get_pending_urls()
    assert len(pending) == 1
    assert pending[0]["shortcode"] == "ENQUEUE123"
    assert pending[0]["collection"] == "growth_inbox"


def test_enqueue_url_duplicate(test_vault: Vault) -> None:
    """Verify POST /api/enqueue returns skipped status for duplicate URL."""
    from reel_watcher.web.server import create_app

    app = create_app(vault=test_vault)
    client = TestClient(app)

    payload = {"url": "https://www.instagram.com/reel/DUP123/"}
    r1 = client.post("/api/enqueue", json=payload)
    assert r1.status_code == 200
    assert r1.json()["status"] == "enqueued"

    # Enqueue same URL again
    r2 = client.post("/api/enqueue", json=payload)
    assert r2.status_code == 200
    assert r2.json()["status"] == "skipped"


def test_enqueue_url_invalid(test_vault: Vault) -> None:
    """Verify POST /api/enqueue returns 400 when URL is empty or unparsable."""
    from reel_watcher.web.server import create_app

    app = create_app(vault=test_vault)
    client = TestClient(app)

    response = client.post("/api/enqueue", json={"url": "   "})
    assert response.status_code == 400


# ==============================================================================
# 5. /api/stats Endpoint Tests
# ==============================================================================


def test_get_stats(test_vault: Vault, sample_studies: dict[str, dict]) -> None:
    """Verify GET /api/stats computes aggregate analytics."""
    from reel_watcher.web.server import create_app

    # Add a pending item to queue
    test_vault.enqueue_url("https://www.instagram.com/reel/PENDING1/", "growth")

    app = create_app(vault=test_vault)
    client = TestClient(app)

    response = client.get("/api/stats")
    assert response.status_code == 200
    stats = response.json()

    assert stats["total_studies"] == 2
    assert stats["pending_queue"] == 1
    assert stats["giveaway_count"] == 1
    assert stats["video_count"] == 1
    assert stats["carousel_count"] == 1
    assert pytest.approx(stats["avg_score"], rel=1e-2) == 8.85
    assert "Problem-Agitate-Solve" in stats["frameworks"]
    assert "AIDA" in stats["frameworks"]


# ==============================================================================
# 6. Static & Media Routes with Path Traversal Protection
# ==============================================================================


def test_media_route_serves_valid_file(test_vault: Vault) -> None:
    """Verify GET /media/{path} serves files located within vault.out_root."""
    from reel_watcher.web.server import create_app

    media_file = test_vault.out_root / "contact_sheets" / "sheet1.jpg"
    media_file.parent.mkdir(parents=True, exist_ok=True)
    media_file.write_bytes(b"\xff\xd8\xff\xe0dummy_jpeg_bytes")

    app = create_app(vault=test_vault)
    client = TestClient(app)

    response = client.get("/media/contact_sheets/sheet1.jpg")
    assert response.status_code == 200
    assert response.content == b"\xff\xd8\xff\xe0dummy_jpeg_bytes"


def test_media_route_not_found(test_vault: Vault) -> None:
    """Verify GET /media/{path} returns 404 for non-existent media files."""
    from reel_watcher.web.server import create_app

    app = create_app(vault=test_vault)
    client = TestClient(app)

    response = client.get("/media/missing_sheet.jpg")
    assert response.status_code == 404


def test_media_route_path_traversal_protection(test_vault: Vault, tmp_path: Path) -> None:
    """Verify GET /media/{path} rejects path traversal attempts."""
    from reel_watcher.web.server import create_app

    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("SUPER_SECRET_TOKEN")

    app = create_app(vault=test_vault)
    client = TestClient(app)

    # Attempting to escape out_root
    r1 = client.get("/media/../secret.txt")
    assert r1.status_code in (403, 404)
    assert "SUPER_SECRET_TOKEN" not in r1.text

    r2 = client.get("/media/../../secret.txt")
    assert r2.status_code in (403, 404)
    assert "SUPER_SECRET_TOKEN" not in r2.text


def test_static_route_serves_valid_file(test_vault: Vault) -> None:
    """Verify GET /static/{path} serves files within static directory."""
    from reel_watcher.web.server import create_app

    app = create_app(vault=test_vault)
    client = TestClient(app)

    response = client.get("/static/index.html")
    assert response.status_code == 200
    assert "Reel-Watcher Playbook" in response.text


def test_static_route_path_traversal_protection(test_vault: Vault) -> None:
    """Verify GET /static/{path} rejects traversal attempts."""
    from reel_watcher.web.server import create_app

    app = create_app(vault=test_vault)
    client = TestClient(app)

    r1 = client.get("/static/../server.py")
    assert r1.status_code in (403, 404)

    r2 = client.get("/static/../../__init__.py")
    assert r2.status_code in (403, 404)


# ==============================================================================
# 7. run_server and CLI Integration Tests
# ==============================================================================


def test_run_server_invokes_uvicorn(test_vault: Vault) -> None:
    """Verify run_server passes proper config to uvicorn.run."""
    from reel_watcher.web.server import run_server

    with patch("uvicorn.run") as mock_uvicorn:
        run_server(port=8440, host="127.0.0.1", vault=test_vault)
        mock_uvicorn.assert_called_once()
        call_kwargs = mock_uvicorn.call_args[1]
        assert call_kwargs["port"] == 8440
        assert call_kwargs["host"] == "127.0.0.1"


def test_cli_serve_parser_options() -> None:
    """Verify CLI parser parses serve arguments."""
    parser = build_parser()
    args = parser.parse_args(["serve", "--port", "8445", "--host", "0.0.0.0"])
    assert args.port == 8445
    assert args.host == "0.0.0.0"


def test_cli_serve_command_execution(tmp_path: Path) -> None:
    """Verify CLI main dispatch to cmd_serve."""
    db_file = tmp_path / "cli_test.db"
    with patch("reel_watcher.web.server.run_server") as mock_run:
        exit_code = main(["serve", "--port", "8440", "--db", str(db_file)])
        assert exit_code == 0
        mock_run.assert_called_once()
        assert mock_run.call_args[1]["port"] == 8440

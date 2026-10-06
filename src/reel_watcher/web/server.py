"""Interactive Web Playbook Dashboard & REST API (`server.py`).

Provides a FastAPI backend server and embedded dark-mode dashboard for exploring,
filtering, and inspecting multimodal video and carousel study deconstructions.
Includes secure media serving with path-traversal protection and queue ingestion.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
import uvicorn

from reel_watcher.config import Config, format_status, load_config
from reel_watcher.db import Vault, extract_shortcode


class EnqueueRequest(BaseModel):
    """Payload model for reel URL queue ingestion."""

    url: str = Field(..., description="Target Reel, TikTok, or Shorts URL.")
    collection: str = Field(default="", description="Optional collection or category tag.")


def create_app(vault: Vault | None = None) -> FastAPI:
    """Create and configure FastAPI application for Reel-Watcher Playbook.

    Parameters
    ----------
    vault : Vault | None, optional
        Target Vault persistence instance. If None, loaded from active configuration.

    Returns
    -------
    FastAPI
        Configured FastAPI application instance.
    """
    if vault is None:
        cfg = load_config()
        vault = Vault(db_path=cfg.db_path, out_root=cfg.vault_dir)

    static_dir = Path(__file__).resolve().parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    index_html_path = static_dir / "index.html"

    app = FastAPI(
        title="Reel-Watcher Playbook API",
        description="Multimodal short-form video harvester, deconstructor, and intelligence engine.",
        version="0.1.0",
    )

    # Attach vault to app state for convenience
    app.state.vault = vault

    # ==========================================================================
    # Dashboard HTML & Static Routes
    # ==========================================================================

    @app.get("/", response_class=FileResponse, summary="Serve Interactive Playbook Dashboard")
    def get_dashboard() -> FileResponse:
        """Serve the primary dark-mode Playbook web interface."""
        if not index_html_path.is_file():
            raise HTTPException(
                status_code=404,
                detail="Dashboard index.html not found. Please ensure static assets are built.",
            )
        return FileResponse(index_html_path, media_type="text/html")

    @app.get("/static/{file_path:path}", summary="Serve Static Web Assets")
    def get_static_file(file_path: str) -> FileResponse:
        """Serve static files with strict path traversal protection."""
        resolved_base = static_dir.resolve()
        target_path = (resolved_base / file_path).resolve()

        if not target_path.is_relative_to(resolved_base):
            raise HTTPException(status_code=403, detail="Forbidden: static path traversal detected")

        if not target_path.is_file():
            raise HTTPException(status_code=404, detail="Static asset not found")

        return FileResponse(target_path)

    @app.get("/media/{file_path:path}", summary="Serve Vault Media & Contact Sheets")
    def get_media_file(file_path: str) -> FileResponse:
        """Serve generated media files (contact sheets, frames) from vault root with path traversal protection."""
        resolved_base = vault.out_root.resolve()
        target_path = (resolved_base / file_path).resolve()

        if not target_path.is_relative_to(resolved_base):
            raise HTTPException(status_code=403, detail="Forbidden: media path traversal detected")

        if not target_path.is_file():
            raise HTTPException(status_code=404, detail="Media file not found")

        return FileResponse(target_path)

    # ==========================================================================
    # Playbook REST API Endpoints
    # ==========================================================================

    @app.get("/api/studies", summary="List and Filter Study Deconstructions")
    def list_studies(
        query: str = Query(default="", description="Search query matching title, hook, author, framework, or code"),
        q: str = Query(default="", description="Alias for search query"),
        format: str = Query(default="", description="Format filter: 'video' or 'carousel'"),
        giveaway: bool | None = Query(default=None, description="Filter by giveaway/lead magnet presence"),
        limit: int = Query(default=100, ge=1, le=1000, description="Max records to return"),
        offset: int = Query(default=0, ge=0, description="Records offset for pagination"),
    ) -> list[dict[str, Any]]:
        """Retrieve deconstructed studies with flexible full-text, format, and giveaway filters."""
        search_term = (query or q).strip()
        all_studies = vault.list_studies(limit=5000, query=search_term)

        filtered: list[dict[str, Any]] = []
        for s in all_studies:
            # Format filtering
            if format.strip():
                fmt = format.strip().lower()
                is_carousel = (
                    s.get("media_type") == "carousel"
                    or s.get("format") == "carousel"
                    or bool(s.get("slides"))
                    or (s.get("slides_count", 0) > 0)
                )
                if fmt == "carousel" and not is_carousel:
                    continue
                if fmt == "video" and is_carousel:
                    continue

            # Giveaway filtering
            if giveaway is not None:
                has_giveaway = (
                    s.get("giveaway", {}).get("has_giveaway") is True
                    or bool(s.get("visual_analysis", {}).get("cta", {}).get("action"))
                )
                if giveaway and not has_giveaway:
                    continue
                if not giveaway and has_giveaway:
                    continue

            filtered.append(s)

        # Apply offset and limit
        return filtered[offset : offset + limit]

    @app.get("/api/studies/{code}", summary="Get Single Study Deconstruction")
    def get_study(code: str) -> dict[str, Any]:
        """Fetch complete deconstruction data for a single study by its shortcode identifier."""
        study_data = vault.get_study(code.strip())
        if not study_data:
            raise HTTPException(
                status_code=404,
                detail=f"Study with shortcode '{code}' not found.",
            )
        return study_data

    @app.post("/api/enqueue", summary="Enqueue Reel URL for Harvesting")
    def enqueue_reel(payload: EnqueueRequest) -> dict[str, Any]:
        """Enqueue a new reel URL into the harvesting queue."""
        clean_url = payload.url.strip()
        if not clean_url:
            raise HTTPException(status_code=400, detail="Target URL cannot be empty.")

        shortcode = extract_shortcode(clean_url)
        if not shortcode:
            raise HTTPException(status_code=400, detail="Unable to extract video shortcode from URL.")

        collection = payload.collection.strip()
        enqueued = vault.enqueue_url(clean_url, collection=collection)

        if enqueued:
            return {
                "status": "enqueued",
                "shortcode": shortcode,
                "url": clean_url,
                "collection": collection,
                "message": f"URL successfully added to queue with shortcode '{shortcode}'.",
            }
        else:
            return {
                "status": "skipped",
                "shortcode": shortcode,
                "url": clean_url,
                "collection": collection,
                "message": "URL already exists in pending queue or has already been studied.",
            }

    @app.get("/api/stats", summary="Get Vault Analytics & Metrics")
    def get_stats() -> dict[str, Any]:
        """Compute aggregate intelligence statistics from vault studies and pending queue."""
        studies = vault.list_studies(limit=10000)
        pending = vault.get_pending_urls(limit=10000)

        total_studies = len(studies)
        scores = [
            float(s.get("score", 0.0))
            for s in studies
            if s.get("score") is not None and float(s.get("score", 0.0)) > 0
        ]
        avg_score = round(sum(scores) / len(scores), 2) if scores else 0.0

        giveaway_count = sum(
            1
            for s in studies
            if s.get("giveaway", {}).get("has_giveaway")
            or s.get("visual_analysis", {}).get("cta", {}).get("action")
        )

        carousel_count = sum(
            1
            for s in studies
            if s.get("media_type") == "carousel"
            or s.get("format") == "carousel"
            or bool(s.get("slides"))
            or (s.get("slides_count", 0) > 0)
        )
        video_count = total_studies - carousel_count

        frameworks: dict[str, int] = {}
        for s in studies:
            fw = str(s.get("framework") or "").strip()
            if fw:
                frameworks[fw] = frameworks.get(fw, 0) + 1

        collections: dict[str, int] = {}
        for s in studies:
            col = str(s.get("collection") or "general").strip()
            collections[col] = collections.get(col, 0) + 1

        return {
            "total_studies": total_studies,
            "pending_queue": len(pending),
            "avg_score": avg_score,
            "giveaway_count": giveaway_count,
            "video_count": video_count,
            "carousel_count": carousel_count,
            "frameworks": frameworks,
            "collections": collections,
        }

    return app


def run_server(
    port: int = 8440,
    host: str = "127.0.0.1",
    vault: Vault | None = None,
) -> None:
    """Run the interactive Playbook web server with Uvicorn.

    Parameters
    ----------
    port : int, optional
        Port number to bind HTTP server (default: 8440).
    host : str, optional
        Host network interface to bind (default: '127.0.0.1').
    vault : Vault | None, optional
        Vault instance. If None, initialized from default configuration.
    """
    app = create_app(vault=vault)

    print(format_status("info", f"Starting Playbook Web Dashboard on http://{host}:{port}..."))
    print(format_status("success", f"Dashboard UI live at http://{host}:{port}/"))
    print(format_status("info", f"REST API documentation available at http://{host}:{port}/docs"))

    uvicorn.run(app, host=host, port=port)

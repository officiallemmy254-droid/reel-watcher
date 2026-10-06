"""Unit and integration tests for Reel-Watcher CLI dispatcher (`cli.py`)."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from reel_watcher.cli import build_parser, main
from reel_watcher.db import Vault


def test_build_parser_structure() -> None:
    """Ensure parser is properly structured with expected subcommands and flags."""
    parser = build_parser()
    assert isinstance(parser, argparse.ArgumentParser)

    # Subcommands check via parsing commands
    subparsers_actions = [
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    ]
    assert len(subparsers_actions) == 1
    subcommands = subparsers_actions[0].choices.keys()

    for cmd in ["preflight", "enqueue", "harvest", "export-parse", "download", "study", "advice", "list"]:
        assert cmd in subcommands


def test_cli_no_args_displays_help(capsys: pytest.CaptureFixture[str]) -> None:
    """Invoking CLI with no arguments should display help and return code 0."""
    exit_code = main([])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "usage:" in captured.out.lower() or "reel-watcher" in captured.out.lower()


def test_cli_preflight_success(capsys: pytest.CaptureFixture[str]) -> None:
    """Test preflight command when all binaries are present."""
    with patch(
        "reel_watcher.cli.preflight",
        return_value={"ffmpeg": True, "ffprobe": True, "yt_dlp": True, "ocr": True},
    ):
        exit_code = main(["preflight"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "[+]" in captured.out
        assert "All core media tools operational" in captured.out


def test_cli_preflight_failure(capsys: pytest.CaptureFixture[str]) -> None:
    """Test preflight command when critical binaries (e.g. ffmpeg) are missing."""
    with patch(
        "reel_watcher.cli.preflight",
        return_value={"ffmpeg": False, "ffprobe": True, "yt_dlp": True, "ocr": False},
    ):
        exit_code = main(["preflight"])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "[-]" in captured.out or "[!]" in captured.out


def test_cli_enqueue_url(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test enqueuing single or multiple URLs into Vault."""
    db_path = tmp_path / "vault" / "reels.db"
    out_root = tmp_path / "vault"

    args = [
        "enqueue",
        "https://www.instagram.com/reel/CXYZ1234/",
        "--collection",
        "growth",
        "--db",
        str(db_path),
        "--out-root",
        str(out_root),
    ]

    exit_code = main(args)
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "[+]" in captured.out
    assert "CXYZ1234" in captured.out

    # Verify directly in SQLite vault
    vault = Vault(db_path=db_path, out_root=out_root)
    pending = vault.get_pending_urls()
    assert len(pending) == 1
    assert pending[0]["shortcode"] == "CXYZ1234"
    assert pending[0]["collection"] == "growth"


def test_cli_enqueue_from_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test enqueuing batch URLs from text file."""
    urls_file = tmp_path / "urls.txt"
    urls_file.write_text(
        "https://www.instagram.com/reel/REEL001/\n"
        "# comment line\n"
        "https://www.instagram.com/reel/REEL002/\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "vault" / "reels.db"
    out_root = tmp_path / "vault"

    args = [
        "enqueue",
        "--file",
        str(urls_file),
        "--db",
        str(db_path),
        "--out-root",
        str(out_root),
    ]

    exit_code = main(args)
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "[+]" in captured.out
    assert "2 url(s) enqueued" in captured.out.lower() or "enqueued" in captured.out.lower()

    vault = Vault(db_path=db_path, out_root=out_root)
    pending = vault.get_pending_urls()
    assert len(pending) == 2


def test_cli_harvest_cdp(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test CDP live session harvester subcommand."""
    db_path = tmp_path / "vault" / "reels.db"
    out_root = tmp_path / "vault"

    with patch(
        "reel_watcher.cli.harvest_saved_reels_via_cdp",
        return_value=["CDP_REEL_1", "CDP_REEL_2"],
    ) as mock_harvest:
        args = [
            "harvest",
            "--cdp-url",
            "http://127.0.0.1:9222",
            "--collection",
            "saved_feed",
            "--db",
            str(db_path),
            "--out-root",
            str(out_root),
        ]
        exit_code = main(args)
        assert exit_code == 0
        mock_harvest.assert_called_once()
        captured = capsys.readouterr()
        assert "[+]" in captured.out
        assert "CDP_REEL_1" in captured.out

        vault = Vault(db_path=db_path, out_root=out_root)
        pending = vault.get_pending_urls()
        assert len(pending) == 2


def test_cli_export_parse(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test Instagram export parser subcommand to TSV and enqueue."""
    db_path = tmp_path / "vault" / "reels.db"
    out_root = tmp_path / "vault"
    tsv_out = tmp_path / "exported.tsv"

    with (
        patch(
            "reel_watcher.cli.extract_urls_from_export",
            return_value=[("https://instagram.com/reel/EXP1/", "saved")],
        ) as mock_extract,
        patch("reel_watcher.cli.export_to_tsv") as mock_export_tsv,
    ):
        fake_export = tmp_path / "saved_posts.json"
        fake_export.touch()

        args = [
            "export-parse",
            str(fake_export),
            "--tsv",
            str(tsv_out),
            "--enqueue",
            "--db",
            str(db_path),
            "--out-root",
            str(out_root),
        ]
        exit_code = main(args)
        assert exit_code == 0
        mock_extract.assert_called_once()
        mock_export_tsv.assert_called_once()

        vault = Vault(db_path=db_path, out_root=out_root)
        pending = vault.get_pending_urls()
        assert len(pending) == 1
        assert pending[0]["shortcode"] == "EXP1"


def test_cli_download_single_url(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test downloading a single URL with download subcommand."""
    out_dir = tmp_path / "downloads"

    with patch("reel_watcher.cli.download_media", return_value=out_dir / "CXYZ.mp4") as mock_dl:
        args = [
            "download",
            "https://www.instagram.com/reel/CXYZ/",
            "--out-dir",
            str(out_dir),
            "--browser",
            "chrome",
        ]
        exit_code = main(args)
        assert exit_code == 0
        mock_dl.assert_called_once()
        captured = capsys.readouterr()
        assert "[+]" in captured.out


def test_cli_download_pending_queue(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test batch downloading pending queue items."""
    db_path = tmp_path / "vault" / "reels.db"
    out_root = tmp_path / "vault"
    out_dir = tmp_path / "downloads"

    vault = Vault(db_path=db_path, out_root=out_root)
    vault.enqueue_url("https://www.instagram.com/reel/PENDING1/")
    vault.enqueue_url("https://www.instagram.com/reel/PENDING2/")

    with patch(
        "reel_watcher.cli.download_media",
        side_effect=lambda url, **kw: out_dir / f"{Path(url).name}.mp4",
    ):
        args = [
            "download",
            "--pending",
            "--limit",
            "10",
            "--out-dir",
            str(out_dir),
            "--db",
            str(db_path),
            "--out-root",
            str(out_root),
        ]
        exit_code = main(args)
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "[+]" in captured.out
        assert "Downloaded 2/2" in captured.out or "2 item" in captured.out.lower()


def test_cli_study_single_video(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test analyzing a single video file through study subcommand."""
    db_path = tmp_path / "vault" / "reels.db"
    out_root = tmp_path / "vault"

    dummy_video = tmp_path / "sample_video.mp4"
    dummy_video.write_bytes(b"dummy")

    fake_study = {
        "code": "sample_video",
        "shortcode": "sample_video",
        "url": "https://instagram.com/reel/sample_video/",
        "title": "Sample Reel Study",
        "score": 9.0,
        "framework": "PAS",
        "hook_text": "Watch this now",
    }

    with patch("reel_watcher.cli.analyze_video_study", return_value=fake_study) as mock_analyze:
        args = [
            "study",
            str(dummy_video),
            "--provider",
            "fake",
            "--fast",
            "--db",
            str(db_path),
            "--out-root",
            str(out_root),
        ]
        exit_code = main(args)
        assert exit_code == 0
        mock_analyze.assert_called_once()
        captured = capsys.readouterr()
        assert "[+]" in captured.out

        # Verify saved in vault
        vault = Vault(db_path=db_path, out_root=out_root)
        saved = vault.get_study("sample_video")
        assert saved is not None
        assert saved["title"] == "Sample Reel Study"


def test_cli_advice_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test generating advice library HTML via advice subcommand."""
    db_path = tmp_path / "vault" / "reels.db"
    out_root = tmp_path / "vault"
    html_out = tmp_path / "custom_advice.html"

    vault = Vault(db_path=db_path, out_root=out_root)
    vault.save_study(
        {
            "code": "REEL999",
            "title": "Viral Hook Breakdown",
            "score": 8.7,
            "framework": "AIDA",
        }
    )

    args = [
        "advice",
        "--out",
        str(html_out),
        "--title",
        "My Custom Library",
        "--db",
        str(db_path),
        "--out-root",
        str(out_root),
    ]

    exit_code = main(args)
    assert exit_code == 0
    assert html_out.is_file()
    captured = capsys.readouterr()
    assert "[+]" in captured.out
    assert "Advice Library HTML rendered to" in captured.out or "[+]" in captured.out


def test_cli_list_studies_and_queue(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Test listing studies and queue items via list subcommand."""
    db_path = tmp_path / "vault" / "reels.db"
    out_root = tmp_path / "vault"

    vault = Vault(db_path=db_path, out_root=out_root)
    vault.enqueue_url("https://instagram.com/reel/QUEUE01/", collection="alpha")
    vault.save_study({"code": "STUDY01", "title": "First Study", "score": 9.5})

    # List studies
    exit_code = main(["list", "--db", str(db_path), "--out-root", str(out_root)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "STUDY01" in captured.out
    assert "First Study" in captured.out

    # List queue
    exit_code = main(["list", "--queue", "--db", str(db_path), "--out-root", str(out_root)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "QUEUE01" in captured.out
    assert "alpha" in captured.out


def test_cli_ascii_output_safety(capsys: pytest.CaptureFixture[str]) -> None:
    """Ensure all CLI output strictly conforms to ASCII bracket indicators without raw Unicode emojis."""
    main(["preflight"])
    captured = capsys.readouterr()

    # Must be encodeable as pure ASCII
    captured.out.encode("ascii")
    captured.err.encode("ascii")

"""Unit and integration tests for Multi-Provider Vision Client (`vision.py`)."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image
import pytest

from reel_watcher.vision import VisionClient, extract_json_from_text


@pytest.fixture
def dummy_image_path(tmp_path: Path) -> Path:
    """Create a temporary dummy JPEG image for vision testing."""
    img_path = tmp_path / "test_sheet.jpg"
    img = Image.new("RGB", (100, 100), color=(200, 100, 50))
    img.save(img_path, "JPEG")
    return img_path


# ==============================================================================
# 1. extract_json_from_text Tests
# ==============================================================================


def test_extract_json_direct() -> None:
    raw = '{"hook": {"text": "How to scale", "rating": 9.0}, "score": 8.5}'
    res = extract_json_from_text(raw)
    assert res["hook"]["text"] == "How to scale"
    assert res["score"] == 8.5


def test_extract_json_markdown_fence() -> None:
    raw = """Here is your deconstruction:
```json
{
  "hook": {"text": "Stop scrolling"},
  "summary": "AI marketing breakdown",
  "score": 9.2
}
```
Hope this helps!"""
    res = extract_json_from_text(raw)
    assert res["hook"]["text"] == "Stop scrolling"
    assert res["score"] == 9.2


def test_extract_json_fence_without_json_tag() -> None:
    raw = """```
{
  "framework": "Problem-Agitate-Solve",
  "score": 7.8
}
```"""
    res = extract_json_from_text(raw)
    assert res["framework"] == "Problem-Agitate-Solve"
    assert res["score"] == 7.8


def test_extract_json_deepseek_r1_think_tag() -> None:
    raw = """<think>
The user wants an analysis of the contact sheet.
Tile 1 shows a bold hook. The rating should be 9.
</think>
```json
{
  "hook": {"text": "Crazy AI trick"},
  "score": 9.0
}
```"""
    res = extract_json_from_text(raw)
    assert res["hook"]["text"] == "Crazy AI trick"
    assert res["score"] == 9.0


def test_extract_json_trailing_commas() -> None:
    raw = """
{
  "items": ["one", "two", ],
  "meta": {"a": 1, },
}
"""
    res = extract_json_from_text(raw)
    assert res["items"] == ["one", "two"]
    assert res["meta"]["a"] == 1


def test_extract_json_invalid_raises_value_error() -> None:
    raw = "This is just conversational text with no JSON anywhere."
    with pytest.raises(ValueError, match="Could not extract valid JSON"):
        extract_json_from_text(raw)


# ==============================================================================
# 2. VisionClient Initialization & Normalization Tests
# ==============================================================================


def test_vision_client_init_defaults() -> None:
    client = VisionClient()
    assert client.provider == "gemini"
    assert client.model is not None


def test_vision_client_provider_normalization() -> None:
    client1 = VisionClient(provider="GEMINI")
    assert client1.provider == "gemini"

    client2 = VisionClient(provider=" OpenRouter ")
    assert client2.provider == "openrouter"

    with pytest.raises(ValueError, match="Unsupported vision provider"):
        VisionClient(provider="unsupported_provider")


# ==============================================================================
# 3. Fake Provider Tests (Offline & Mock Mode)
# ==============================================================================


def test_vision_client_fake_missing_file(tmp_path: Path) -> None:
    client = VisionClient(provider="fake")
    missing = tmp_path / "nonexistent.jpg"
    with pytest.raises(FileNotFoundError):
        client.ask_contact_sheet(missing)


def test_vision_client_fake_default_response(dummy_image_path: Path) -> None:
    client = VisionClient(provider="fake")
    res = client.ask_contact_sheet(dummy_image_path)
    assert isinstance(res, dict)
    assert "hook" in res
    assert "summary" in res
    assert "framework" in res
    assert "cta" in res
    assert "score" in res
    assert isinstance(res["score"], (int, float))


def test_vision_client_fake_custom_response(dummy_image_path: Path) -> None:
    custom = {
        "hook": {"text": "Custom Hook"},
        "summary": "Custom summary",
        "score": 9.9,
    }
    client = VisionClient(provider="fake", mock_response=custom)
    res = client.ask_contact_sheet(dummy_image_path)
    assert res["hook"]["text"] == "Custom Hook"
    assert res["score"] == 9.9


# ==============================================================================
# 4. API Key Validation Tests
# ==============================================================================


def test_vision_client_missing_api_key_raises(dummy_image_path: Path) -> None:
    client = VisionClient(provider="gemini", api_key="")
    with pytest.raises(ValueError, match="Gemini API key is required"):
        client.ask_contact_sheet(dummy_image_path)

    client_or = VisionClient(provider="openrouter", api_key="")
    with pytest.raises(ValueError, match="OpenRouter API key is required"):
        client_or.ask_contact_sheet(dummy_image_path)

    client_oa = VisionClient(provider="openai", api_key="")
    with pytest.raises(ValueError, match="OpenAI API key is required"):
        client_oa.ask_contact_sheet(dummy_image_path)


# ==============================================================================
# 5. Gemini Provider Mock API Call
# ==============================================================================


def test_vision_client_gemini_api_call(dummy_image_path: Path) -> None:
    mock_payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "hook": {"text": "Scale with AI"},
                                    "summary": "Gemini deconstruction",
                                    "score": 8.7,
                                }
                            )
                        }
                    ]
                }
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_payload

    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        client = VisionClient(
            provider="gemini",
            api_key="test_gemini_key",
            model="gemini-2.5-flash",
        )
        res = client.ask_contact_sheet(
            dummy_image_path, context_prompt="Test Context"
        )

        assert mock_post.called
        call_url = mock_post.call_args[0][0]
        assert "key=test_gemini_key" in call_url
        assert "gemini-2.5-flash" in call_url

        call_json = mock_post.call_args[1]["json"]
        assert "contents" in call_json
        parts = call_json["contents"][0]["parts"]
        assert any("inline_data" in p for p in parts)

        assert res["hook"]["text"] == "Scale with AI"
        assert res["score"] == 8.7


def test_vision_client_gemini_error_handling(dummy_image_path: Path) -> None:
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"

    with patch("httpx.Client.post", return_value=mock_resp):
        client = VisionClient(provider="gemini", api_key="valid_key")
        with pytest.raises(RuntimeError, match="Gemini API error"):
            client.ask_contact_sheet(dummy_image_path)


# ==============================================================================
# 6. OpenRouter Provider Mock API Call
# ==============================================================================


def test_vision_client_openrouter_api_call(dummy_image_path: Path) -> None:
    mock_payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "hook": {"text": "Stop Doing This"},
                            "summary": "OpenRouter breakdown",
                            "score": 9.1,
                        }
                    )
                }
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_payload

    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        client = VisionClient(
            provider="openrouter",
            api_key="test_openrouter_key",
            model="google/gemini-2.5-pro",
        )
        res = client.ask_contact_sheet(dummy_image_path)

        assert mock_post.called
        call_headers = mock_post.call_args[1]["headers"]
        assert "Bearer test_openrouter_key" in call_headers["Authorization"]

        call_json = mock_post.call_args[1]["json"]
        assert call_json["model"] == "google/gemini-2.5-pro"
        messages = call_json["messages"]
        assert messages[0]["role"] == "user"

        assert res["hook"]["text"] == "Stop Doing This"
        assert res["score"] == 9.1


# ==============================================================================
# 7. OpenAI Provider Mock API Call
# ==============================================================================


def test_vision_client_openai_api_call(dummy_image_path: Path) -> None:
    mock_payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "hook": {"text": "OpenAI Hook"},
                            "summary": "OpenAI summary",
                            "score": 8.0,
                        }
                    )
                }
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_payload

    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        client = VisionClient(
            provider="openai",
            api_key="test_openai_key",
            model="gpt-4o",
        )
        res = client.ask_contact_sheet(dummy_image_path)

        assert mock_post.called
        call_headers = mock_post.call_args[1]["headers"]
        assert "Bearer test_openai_key" in call_headers["Authorization"]
        assert res["hook"]["text"] == "OpenAI Hook"


# ==============================================================================
# 8. Ollama Provider Mock API Call
# ==============================================================================


def test_vision_client_ollama_api_call(dummy_image_path: Path) -> None:
    mock_payload = {
        "message": {
            "content": json.dumps(
                {
                    "hook": {"text": "Local Vision Hook"},
                    "summary": "Ollama summary",
                    "score": 7.5,
                }
            )
        }
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_payload

    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        client = VisionClient(
            provider="ollama",
            model="llama3.2-vision",
            base_url="http://localhost:11434",
        )
        res = client.ask_contact_sheet(dummy_image_path)

        assert mock_post.called
        call_url = mock_post.call_args[0][0]
        assert "http://localhost:11434/api/chat" in call_url

        call_json = mock_post.call_args[1]["json"]
        assert call_json["model"] == "llama3.2-vision"
        assert "images" in call_json["messages"][0]
        assert res["hook"]["text"] == "Local Vision Hook"

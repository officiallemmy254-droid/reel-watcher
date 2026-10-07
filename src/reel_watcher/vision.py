"""Multi-Provider Vision & Multimodal Analysis Client (`vision.py`).

Provides universal visual deconstruction of contact sheets across:
- Google Gemini 2.5 Flash
- OpenRouter (Gemini Pro, Claude, etc.)
- OpenAI (GPT-4o)
- Ollama (Local Vision LLMs)
- Fake / Offline Mode (for zero-cost local testing and air-gapped workflows)
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
from pathlib import Path
import re
from typing import Any

import httpx

from reel_watcher.config import format_status, load_config

DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
DEFAULT_OPENROUTER_MODEL = "google/gemini-2.5-pro"
DEFAULT_OPENAI_MODEL = "gpt-4o"
DEFAULT_OLLAMA_MODEL = "llama3.2-vision"

SUPPORTED_PROVIDERS = {"gemini", "openrouter", "openai", "ollama", "fake"}

VISION_SYSTEM_PROMPT = """You are an elite short-form video deconstructor, content strategist, and virality analyst.
Analyze the provided labeled contact sheet (tiles #1 to #9) of sequential frames or carousel slides.
Deconstruct the content structure, retention mechanics, and conversion funnel into valid JSON:
{
  "hook": {
    "text": "verbatim or visual hook text",
    "visual_style": "talking head / b-roll / screen recording / typography card",
    "strength": 9.0,
    "rating": 9.0
  },
  "summary": "2-3 sentence overview of the topic, narrative arc, and core value proposition",
  "framework": "content framework (e.g. Problem-Agitate-Solve, Hook-Story-Offer, Listicle, Step-by-Step, Before-After, Teardown)",
  "pacing": {
    "style": "fast / medium / slow",
    "energy": "high / moderate / calm"
  },
  "cta": {
    "action": "comment / dm / link_in_bio / none",
    "keyword": "trigger word if applicable (e.g. 'GUIDE', 'SYSTEM', 'PROMPT')",
    "offer": "lead magnet or offer description (e.g. 'Free AI Playbook')"
  },
  "score": 8.5,
  "scenes": [
    {"tile": 1, "description": "hook visual composition and text overlay"},
    {"tile": 2, "description": "core content breakdown and transition"}
  ],
  "strengths": ["visual contrast", "clear hook"],
  "weaknesses": ["quiet background"]
}

CRITICAL: Return valid JSON ONLY. Do not enclose in markdown explanation or conversational text."""

DEFAULT_MOCK_RESPONSE: dict[str, Any] = {
    "hook": {
        "text": "How to scale to $100k/mo with AI",
        "visual_style": "talking head with dynamic caption overlay",
        "strength": 9.0,
        "rating": 9.0,
    },
    "summary": "Step-by-step breakdown of how creators use AI workflows to automate content distribution.",
    "framework": "Problem-Agitate-Solve",
    "pacing": {
        "style": "fast",
        "average_shot_duration": 1.8,
        "energy": "high",
    },
    "cta": {
        "action": "comment",
        "keyword": "GROWTH",
        "offer": "Free AI Growth Playbook",
    },
    "score": 8.8,
    "scenes": [
        {"tile": 1, "description": "Bold hook with large yellow typography"},
        {"tile": 2, "description": "Problem demonstration on laptop screen"},
        {"tile": 3, "description": "CTA end screen with comment keyword"},
    ],
    "strengths": [
        "Instant visual hook",
        "High contrast subtitle styling",
        "Clear giveaway CTA",
    ],
    "weaknesses": ["Fast cut transitions in scene 2"],
}


def extract_json_from_text(text: str) -> dict[str, Any]:
    """Robustly extract and parse a JSON dictionary from model output text.

    Strips:
    - DeepSeek-R1 / Qwen `<think>...</think>` tags
    - Markdown code fences (```json ... ``` or ``` ... ```)
    - Surrounding conversational commentary
    - Trailing commas inside objects and arrays

    Raises:
        ValueError: If no valid JSON dictionary or array can be parsed.
    """
    cleaned = str(text or "").strip()
    if not cleaned:
        raise ValueError("Cannot extract JSON from empty text string.")

    # 1. Strip reasoning thoughts (<think>...</think>)
    cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL | re.IGNORECASE).strip()

    # 2. Extract from markdown code fence if present
    fence_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", cleaned, flags=re.IGNORECASE)
    if fence_match:
        fence_content = fence_match.group(1).strip()
        try:
            parsed = json.loads(fence_content)
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list):
                return {"items": parsed}
        except json.JSONDecodeError:
            # Fall back to regex bracket search over fence content
            cleaned = fence_content

    # 3. Direct JSON parsing attempt
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list):
            return {"items": parsed}
    except json.JSONDecodeError:
        pass

    # 4. Search for the outermost JSON object brackets { ... }
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = cleaned[start : end + 1]
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            # Remove trailing commas before closing braces/brackets
            fixed = re.sub(r",\s*([}\]])", r"\1", candidate)
            try:
                parsed = json.loads(fixed)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

    # 5. Search for outermost JSON array brackets [ ... ]
    start_arr = cleaned.find("[")
    end_arr = cleaned.rfind("]")
    if start_arr != -1 and end_arr != -1 and end_arr > start_arr:
        candidate_arr = cleaned[start_arr : end_arr + 1]
        try:
            parsed = json.loads(candidate_arr)
            if isinstance(parsed, list):
                return {"items": parsed}
        except json.JSONDecodeError:
            fixed_arr = re.sub(r",\s*([}\]])", r"\1", candidate_arr)
            try:
                parsed = json.loads(fixed_arr)
                if isinstance(parsed, list):
                    return {"items": parsed}
            except json.JSONDecodeError:
                pass

    snippet = cleaned[:200] if len(cleaned) > 200 else cleaned
    raise ValueError(f"Could not extract valid JSON from vision response: {snippet}")


class VisionClient:
    """Universal Vision & Multimodal Analysis Client."""

    def __init__(
        self,
        provider: str = "gemini",
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float = 60.0,
        mock_response: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the Vision Client.

        Args:
            provider: 'gemini', 'openrouter', 'openai', 'ollama', or 'fake'.
            api_key: Explicit API key, or None to load from env / config.
            model: Model name/identifier, or None to use provider default.
            base_url: Custom API endpoint URL for OpenAI/Ollama proxies.
            timeout: HTTP request timeout in seconds.
            mock_response: Custom response dict returned when provider='fake'.
        """
        self.provider = str(provider or "gemini").strip().lower()
        if self.provider not in SUPPORTED_PROVIDERS:
            raise ValueError(
                f"Unsupported vision provider: '{provider}'. "
                f"Choose from: {', '.join(sorted(SUPPORTED_PROVIDERS))}."
            )

        self.timeout = float(timeout)
        self.base_url = str(base_url).strip() if base_url else None
        self.mock_response = mock_response

        # Load environment & app configuration
        cfg = load_config()

        # Resolve API Keys
        if api_key is not None:
            self.api_key = api_key.strip() if api_key.strip() else None
        else:
            if self.provider == "gemini":
                self.api_key = cfg.gemini_api_key or os.environ.get("GEMINI_API_KEY")
            elif self.provider == "openrouter":
                self.api_key = cfg.openrouter_api_key or os.environ.get("OPENROUTER_API_KEY")
            elif self.provider == "openai":
                self.api_key = os.environ.get("OPENAI_API_KEY")
            else:
                self.api_key = None

        # Resolve Secondary Keys for Automatic Quota Failover
        self.gemini_api_key = (
            self.api_key if self.provider == "gemini" and self.api_key else (cfg.gemini_api_key or os.environ.get("GEMINI_API_KEY"))
        )
        self.openrouter_api_key = (
            self.api_key if self.provider == "openrouter" and self.api_key else (cfg.openrouter_api_key or os.environ.get("OPENROUTER_API_KEY"))
        )

        # Resolve Model
        if model is not None and model != "":
            self.model = model.strip()
        else:
            if self.provider == "gemini":
                self.model = cfg.gemini_model or DEFAULT_GEMINI_MODEL
            elif self.provider == "openrouter":
                self.model = cfg.openrouter_model or DEFAULT_OPENROUTER_MODEL
            elif self.provider == "openai":
                self.model = DEFAULT_OPENAI_MODEL
            elif self.provider == "ollama":
                self.model = DEFAULT_OLLAMA_MODEL
            else:
                self.model = "fake-model"

        # Resolve Fallback Models
        self.gemini_model = (
            self.model if self.provider == "gemini" else (cfg.gemini_model or DEFAULT_GEMINI_MODEL)
        )
        self.openrouter_model = (
            self.model if self.provider == "openrouter" else (cfg.openrouter_model or DEFAULT_OPENROUTER_MODEL)
        )

    def ask_contact_sheet(
        self,
        sheet_path: Path | str,
        context_prompt: str = "",
    ) -> dict[str, Any]:
        """Submit a contact sheet image to the vision provider and retrieve structured JSON.

        Args:
            sheet_path: Path to the labeled contact sheet JPEG/PNG image.
            context_prompt: Contextual metadata (e.g. caption, title, transcript).

        Returns:
            dict containing visual hook, summary, framework, pacing, CTA, and score.

        Raises:
            FileNotFoundError: If the sheet image does not exist.
            ValueError: If required API credentials are missing or response JSON is invalid.
            RuntimeError: If the remote API request fails.
        """
        path = Path(sheet_path)
        if not path.is_file():
            raise FileNotFoundError(f"Contact sheet image not found: {path}")

        # 1. Fake / Offline Provider
        if self.provider == "fake":
            print(format_status("info", f"Analyzing contact sheet using fake provider (offline mode)..."))
            if self.mock_response is not None:
                return dict(self.mock_response)
            return dict(DEFAULT_MOCK_RESPONSE)

        # 2. Validate API Key for cloud providers
        if self.provider in ("gemini", "openrouter", "openai") and not self.api_key:
            name_map = {
                "gemini": "Gemini",
                "openrouter": "OpenRouter",
                "openai": "OpenAI",
                "ollama": "Ollama",
            }
            name = name_map.get(self.provider, self.provider.capitalize())
            env_var = f"{self.provider.upper()}_API_KEY"
            raise ValueError(
                f"{name} API key is required. Set {env_var} environment variable or pass api_key."
            )

        # 3. Read and Base64 encode the image
        img_bytes = path.read_bytes()
        b64_img = base64.b64encode(img_bytes).decode("utf-8")

        # Determine MIME type
        mime_type, _ = mimetypes.guess_type(str(path))
        if not mime_type:
            mime_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"

        # Construct full prompt
        prompt_parts = [VISION_SYSTEM_PROMPT]
        if context_prompt.strip():
            prompt_parts.append(f"\n--- Context Metadata ---\n{context_prompt.strip()}")
        full_prompt = "\n".join(prompt_parts)

        # 4. Dispatch by provider
        print(format_status("progress", f"Submitting contact sheet to {self.provider} ({self.model})..."))

        def _is_quota_error(exc: Exception) -> bool:
            msg = str(exc).lower()
            return any(k in msg for k in (
                "429", "quota", "resourceexhausted", "rate limit", "rate_limit",
                "credit", "exceeded", "too many requests", "insufficient_quota"
            ))

        if self.provider == "gemini":
            try:
                res = self._call_gemini(b64_img, mime_type, full_prompt)
            except Exception as exc:
                if _is_quota_error(exc) and self.openrouter_api_key:
                    print(format_status("warning", f"Gemini quota/rate limit hit ({exc}). Automatically failing over to OpenRouter ({self.openrouter_model})..."))
                    res = self._call_openrouter(
                        b64_img,
                        mime_type,
                        full_prompt,
                        api_key=self.openrouter_api_key,
                        model=self.openrouter_model,
                    )
                else:
                    raise
        elif self.provider == "openrouter":
            try:
                res = self._call_openrouter(b64_img, mime_type, full_prompt)
            except Exception as exc:
                if _is_quota_error(exc) and self.gemini_api_key:
                    print(format_status("warning", f"OpenRouter quota/rate limit hit ({exc}). Automatically failing over to Gemini ({self.gemini_model})..."))
                    res = self._call_gemini(
                        b64_img,
                        mime_type,
                        full_prompt,
                        api_key=self.gemini_api_key,
                        model=self.gemini_model,
                    )
                else:
                    raise
        elif self.provider == "openai":
            res = self._call_openai(b64_img, mime_type, full_prompt)
        elif self.provider == "ollama":
            res = self._call_ollama(b64_img, mime_type, full_prompt)
        else:
            res = dict(DEFAULT_MOCK_RESPONSE)

        print(format_status("success", f"Vision deconstruction completed via {self.provider} ({self.model})."))
        return res

    def _call_gemini(
        self,
        b64_img: str,
        mime_type: str,
        prompt: str,
        api_key: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Execute request to Google Gemini API."""
        use_key = api_key or self.api_key
        use_model = model or self.model
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{use_model}:generateContent?key={use_key}"
        )
        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": b64_img,
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {
                "response_mime_type": "application/json",
            },
        }

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload)

        if resp.status_code != 200:
            snippet = resp.text.strip()[:300]
            raise RuntimeError(f"Gemini API error ({resp.status_code}): {snippet}")

        data = resp.json()
        try:
            candidates = data.get("candidates", [])
            text_resp = candidates[0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"Malformed Gemini API response: {data}") from exc

        return extract_json_from_text(text_resp)

    def _call_openrouter(
        self,
        b64_img: str,
        mime_type: str,
        prompt: str,
        api_key: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Execute request to OpenRouter multimodal completions API."""
        use_key = api_key or self.api_key
        use_model = model or self.model
        base = self.base_url or "https://openrouter.ai/api/v1"
        url = f"{base.rstrip('/')}/chat/completions"

        headers = {
            "Authorization": f"Bearer {use_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/gwelix/reel-watcher",
            "X-Title": "Reel-Watcher",
        }
        payload = {
            "model": use_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{b64_img}"
                            },
                        },
                    ],
                }
            ],
            "response_format": {"type": "json_object"},
        }

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload, headers=headers)

        if resp.status_code != 200:
            snippet = resp.text.strip()[:300]
            raise RuntimeError(f"OpenRouter API error ({resp.status_code}): {snippet}")

        data = resp.json()
        try:
            choices = data.get("choices", [])
            text_resp = choices[0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"Malformed OpenRouter API response: {data}") from exc

        return extract_json_from_text(text_resp)

    def _call_openai(self, b64_img: str, mime_type: str, prompt: str) -> dict[str, Any]:
        """Execute request to OpenAI chat completions API."""
        base = self.base_url or "https://api.openai.com/v1"
        url = f"{base.rstrip('/')}/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{b64_img}"
                            },
                        },
                    ],
                }
            ],
            "response_format": {"type": "json_object"},
        }

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload, headers=headers)

        if resp.status_code != 200:
            snippet = resp.text.strip()[:300]
            raise RuntimeError(f"OpenAI API error ({resp.status_code}): {snippet}")

        data = resp.json()
        try:
            choices = data.get("choices", [])
            text_resp = choices[0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"Malformed OpenAI API response: {data}") from exc

        return extract_json_from_text(text_resp)

    def _call_ollama(self, b64_img: str, mime_type: str, prompt: str) -> dict[str, Any]:
        """Execute request to local Ollama API."""
        base = self.base_url or "http://localhost:11434"
        url = f"{base.rstrip('/')}/api/chat"

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [b64_img],
                }
            ],
            "stream": False,
            "format": "json",
        }

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload)

        if resp.status_code != 200:
            snippet = resp.text.strip()[:300]
            raise RuntimeError(f"Ollama API error ({resp.status_code}): {snippet}")

        data = resp.json()
        try:
            text_resp = data["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError(f"Malformed Ollama API response: {data}") from exc

        return extract_json_from_text(text_resp)

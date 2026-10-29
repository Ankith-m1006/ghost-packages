"""Minimal Gemini API client for Gemma models (plain REST, no SDK).

The API key is read from the environment (GEMINI_API_KEY) and sent only in the
`x-goog-api-key` header, so it never appears in URLs, logs or exception messages.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

BASE = "https://generativelanguage.googleapis.com/v1beta"


class GemmaError(RuntimeError):
    pass


def load_key(extra_env_files: list[str | os.PathLike] = ()) -> str | None:
    """GEMINI_API_KEY from the environment, else from ./.env or the given .env files."""
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    try:
        from dotenv import dotenv_values
    except ImportError:
        return None
    for path in [Path.cwd() / ".env", *map(Path, extra_env_files)]:
        if path.is_file():
            value = dotenv_values(path).get("GEMINI_API_KEY")
            if value:
                return value
    return None


class Gemma:
    def __init__(self, key: str, min_interval: float = 4.0, session=None):
        import requests

        if not key:
            raise GemmaError("no GEMINI_API_KEY")
        self._session = session or requests.Session()
        self._session.headers.update({"x-goog-api-key": key, "Content-Type": "application/json"})
        self.min_interval = min_interval
        self._last = 0.0
        self.calls = 0  # generateContent HTTP requests made (including retries)

    def list_models(self) -> list[dict]:
        models, token = [], None
        while True:
            params = {"pageSize": 200}
            if token:
                params["pageToken"] = token
            r = self._session.get(f"{BASE}/models", params=params, timeout=30)
            if r.status_code != 200:
                raise GemmaError(f"list models failed: HTTP {r.status_code}")
            body = r.json()
            models.extend(body.get("models", []))
            token = body.get("nextPageToken")
            if not token:
                return models

    def generate(self, model: str, prompt: str, temperature: float = 0.7, max_tokens: int = 1200,
                 max_retries: int = 6, on_call=None) -> dict:
        """Returns {"text", "finish_reason", "usage"}. `on_call()` is invoked before every HTTP request."""
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        delay = 10.0
        for attempt in range(max_retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            if on_call:
                on_call()
            self._last = time.monotonic()
            self.calls += 1
            try:
                r = self._session.post(f"{BASE}/models/{model}:generateContent", json=payload, timeout=120)
            except Exception as exc:
                if attempt == max_retries:
                    raise GemmaError(f"network error: {type(exc).__name__}") from None
                time.sleep(delay)
                delay = min(delay * 2, 120)
                continue
            if r.status_code == 200:
                body = r.json()
                cands = body.get("candidates") or []
                if not cands:
                    return {"text": "", "finish_reason": "NO_CANDIDATE", "usage": body.get("usageMetadata", {})}
                parts = (cands[0].get("content") or {}).get("parts") or []
                return {
                    "text": "".join(p.get("text", "") for p in parts),
                    "finish_reason": cands[0].get("finishReason", ""),
                    "usage": body.get("usageMetadata", {}),
                }
            if r.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                retry_after = r.headers.get("Retry-After")
                time.sleep(float(retry_after) if retry_after and retry_after.isdigit() else delay)
                delay = min(delay * 2, 120)
                continue
            # error bodies from this API do not contain the key, but keep only the status + message
            msg = ""
            try:
                msg = (r.json().get("error") or {}).get("message", "")[:200]
            except ValueError:
                pass
            raise GemmaError(f"HTTP {r.status_code}: {msg}")
        raise GemmaError("retries exhausted")

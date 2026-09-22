"""Optional Gemini-powered title shortening.

Long, spammy titles make unreadable filenames, so when the user has configured
a Gemini API key, titles above TITLE_MAX_CHARS are shortened by the model.

Everything here is best-effort: with no key, an invalid key, a quota error or a
malformed response the caller keeps the original title, so the app behaves
exactly as it does without this feature.
"""

from __future__ import annotations

import requests

from core.logger import logger

GEMINI_MODEL = "gemini-3.6-flash"
API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"
REQUEST_TIMEOUT = 20

# Titles longer than this are sent to Gemini for shortening.
TITLE_MAX_CHARS = 100

_PROMPT = """Shorten this video title into a clean label usable as a filename.

Rules:
- Reply with the label only: no quotes, no explanation, one line.
- Keep the original language of the title.
- Keep the words that identify the video; drop spam, marketing filler and URLs.
- Use neutral wording: never include explicit or sexual terms.
- Maximum {max_chars} characters.

Title: {title}"""


def shorten_title(title: str, api_key: str, max_chars: int = TITLE_MAX_CHARS) -> str | None:
    """Ask Gemini for a shorter title.

    Returns None when no key is configured or the request/response cannot be
    used, so callers can fall back to the original title.
    """
    api_key = (api_key or "").strip()
    if not api_key:
        return None

    prompt = _PROMPT.format(max_chars=max_chars, title=title)

    try:
        response = requests.post(
            f"{API_ROOT}/{GEMINI_MODEL}:generateContent",
            params={"key": api_key},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        logger.warning(f"[gemini] could not shorten title: {type(exc).__name__}: {exc}")
        return None

    candidate = _extract_text(payload)
    if not candidate:
        return None

    # Only accept a result that is actually an improvement.
    if len(candidate) >= len(title):
        return None

    return candidate


def _extract_text(payload: dict) -> str | None:
    """Pull the answer text out of a generateContent response, or explain why not."""
    candidates = payload.get("candidates")
    if not candidates:
        block_reason = (payload.get("promptFeedback") or {}).get("blockReason")
        logger.warning(
            "[gemini] no candidates in response"
            + (f" (blocked: {block_reason})" if block_reason else "")
            + f"; raw={_preview(payload)}"
        )
        return None

    candidate = candidates[0] or {}
    parts = (candidate.get("content") or {}).get("parts") or []
    text = next(
        (part.get("text") for part in parts
         if isinstance(part, dict) and isinstance(part.get("text"), str) and part["text"].strip()),
        None,
    )

    if text is None:
        # Most often a safety filter refused the title (e.g. adult wording).
        logger.warning(
            f"[gemini] response carried no text (finishReason={candidate.get('finishReason')!r})"
            f"; keeping the original title. raw={_preview(payload)}"
        )
        return None

    # Models occasionally wrap the answer in quotes or add a trailing line.
    cleaned = text.strip().splitlines()[0].strip()
    cleaned = cleaned.strip().strip('"\'').strip()
    cleaned = " ".join(cleaned.split())
    return cleaned or None


def _preview(payload, limit: int = 300) -> str:
    """Short, single-line dump of a response so log lines stay readable."""
    try:
        import json

        text = json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(payload)
    return text[:limit]

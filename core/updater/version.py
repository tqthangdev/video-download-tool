"""
core/updater/version.py

The running build's version, and how versions are compared.

The version lives in one place — `version.json` next to the app (bundled into
the release) — so no module has to hard-code it.
"""

from __future__ import annotations

import json
from typing import Tuple

from core.logger import logger
from core.utils import get_resource_path

VERSION_FILE = "version.json"


def read_current_version() -> str:
    """The version of this build, e.g. "1.0.2" ("" when it cannot be read)."""
    try:
        data = json.loads(get_resource_path(VERSION_FILE).read_text(encoding="utf-8"))
        return str(data.get("version") or "").strip()
    except (OSError, ValueError, AttributeError) as e:
        logger.error(f"[updater] Cannot read {VERSION_FILE}: {e}")
        return ""


def parse_version(text: str) -> Tuple[int, ...]:
    """Turn "v1.0.2" / "1.0.2" into a comparable tuple (1, 0, 2).

    Anything after the leading digits of a part is ignored, so a tag such as
    "v1.0.2-beta" still parses.
    """
    parts = []
    for chunk in (text or "").strip().lstrip("vV").split("."):
        digits = ""
        for ch in chunk:
            if not ch.isdigit():
                break
            digits += ch
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def is_newer(latest: str, current: str) -> bool:
    """True when `latest` is a strictly higher version than `current`.

    Compared part by part rather than as text, so 1.0.10 > 1.0.9. An
    unreadable version on either side counts as "no update".
    """
    new, old = parse_version(latest), parse_version(current)
    if not new or not old:
        return False
    return new > old

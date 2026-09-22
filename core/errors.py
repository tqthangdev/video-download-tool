"""Application-level error model.

Every yt-dlp exception/message is translated into one of these so the GUI only
ever shows a concise, human-readable message, while the full yt-dlp diagnostic
goes to the log (flow.md #35, #58).
"""

from __future__ import annotations

# Error codes: stable identifiers the GUI/engine can branch on.
UNSUPPORTED = "unsupported"
PRIVATE = "private"
LOGIN_REQUIRED = "login_required"
GEO = "geo"
UNAVAILABLE = "unavailable"
FORMAT_UNAVAILABLE = "format_unavailable"
BLOCKED = "blocked"
FILENAME_TOO_LONG = "filename_too_long"
NETWORK = "network"
HTTP = "http"
EXTRACTOR = "extractor"
POSTPROCESS = "postprocess"
CANCELLED = "cancelled"
OUTPUT_MISSING = "output_missing"
UNKNOWN = "unknown"


_MESSAGES = {
    UNSUPPORTED: "This URL is not supported by yt-dlp.",
    PRIVATE: "This video is private.",
    LOGIN_REQUIRED: "Login (or cookies) is required to access this video.",
    GEO: "This video is not available in your region.",
    UNAVAILABLE: "This video is unavailable.",
    FORMAT_UNAVAILABLE: "The selected format is no longer available.",
    BLOCKED: "The site blocked the request. It may need cookies or a different network.",
    FILENAME_TOO_LONG: "The output filename is too long for the filesystem.",
    NETWORK: "Network error, please check your connection.",
    HTTP: "The server returned an error.",
    EXTRACTOR: "Failed to extract video information.",
    POSTPROCESS: "Post-processing failed (FFmpeg is required).",
    CANCELLED: "Download was cancelled.",
    OUTPUT_MISSING: "The output file is missing or incomplete after download.",
    UNKNOWN: "Download failed.",
}


class ApplicationError(Exception):
    """Base error surfaced to the GUI."""

    def __init__(self, message: str, *, code: str = UNKNOWN, detail: str | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.detail = detail

    def __str__(self) -> str:
        return self.message


def message_for(code: str) -> str:
    return _MESSAGES.get(code, _MESSAGES[UNKNOWN])


def app_error(code: str, detail: str | None = None) -> ApplicationError:
    return ApplicationError(message_for(code), code=code, detail=detail)


# Keyword -> error code. Order matters: the first match wins, so the more
# specific causes must come before the generic "unable to download webpage"
# (which would otherwise swallow an HTTP 403 as a network error).
_KEYWORDS = (
    (UNSUPPORTED, ("unsupported url", "is not a valid url", "no suitable extractor")),
    (FORMAT_UNAVAILABLE, ("requested format is not available", "requested format not available",
                          "format is not available", "no video formats found")),
    (PRIVATE, ("private video", "this video is private", "sign in to confirm your age")),
    (BLOCKED, ("http error 403", "403 forbidden", "http error 401", "401 unauthorized",
               "http error 429", "too many requests")),
    (FILENAME_TOO_LONG, ("file name too long", "errno 36")),
    (LOGIN_REQUIRED, ("login required", "sign in to confirm", "authentication",
                      "cookies", "account", "members-only", "members only")),
    (GEO, ("not available in your country", "geo restricted", "geo restriction",
           "blocked in your country")),
    (UNAVAILABLE, ("video unavailable", "video is unavailable", "is unavailable",
                   "is not available", "has been removed",
                   "no longer exists", "does not exist", "has been deleted",
                   "content is not available")),
    (POSTPROCESS, ("postprocessing", "post-processing", "ffmpeg", "merging",
                   "you have requested merging")),
    (NETWORK, ("unable to download webpage", "connection", "timed out", "timeout",
               "temporary failure", "network", "unable to connect", "read timed out")),
    (HTTP, ("http error",)),
)


def translate_ytdlp_error(exc: BaseException) -> ApplicationError:
    """Map a yt-dlp exception into an ApplicationError."""
    text = str(exc).lower()

    for code, needles in _KEYWORDS:
        if any(n in text for n in needles):
            return ApplicationError(message_for(code), code=code, detail=str(exc))

    return ApplicationError(message_for(EXTRACTOR), code=EXTRACTOR, detail=str(exc))


def is_format_unavailable(exc: BaseException) -> bool:
    text = str(exc).lower()
    return (
        "requested format is not available" in text
        or "requested format not available" in text
        or "format is not available" in text
    )

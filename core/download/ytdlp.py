"""yt-dlp wrapper.

The single place that talks to yt_dlp.YoutubeDL: extraction (preview /
refresh formats) and downloading (flow.md #20, #51, #52). Everything blocking
lives here; callers run it in a thread pool so the Qt event loop never blocks
(flow.md #53).
"""

from __future__ import annotations

import html
import os
import re
import shutil
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse

import requests
import yt_dlp

from core.download.format_selector import VIDEO, VideoInfo, normalize_formats
from core.download.segmented import (
    DEFAULT_CONNECTIONS,
    MAX_CONNECTIONS,
    SegmentedCancelled,
    download_segmented,
)
from core.errors import (
    BLOCKED,
    CANCELLED,
    EXTRACTOR,
    GEO,
    HTTP,
    NETWORK,
    OUTPUT_MISSING,
    UNSUPPORTED,
    ApplicationError,
    app_error,
    translate_ytdlp_error,
)
from core.logger import logger
from core.utils import (
    build_output_template,
    clean_title,
    expected_output_path,
    get_resource_path,
    job_temp_dir,
    resolve_output_file,
)


class _Cancelled(Exception):
    """Raised inside a progress hook to abort a running download."""


def ffmpeg_path() -> str | None:
    """The FFmpeg binary to use: bundled with the app, else the one on PATH.

    Release builds ship FFmpeg next to the app (see `build.py`), so an installed
    copy never has to rely on the user's PATH.
    """
    exe_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    bundled = get_resource_path(exe_name)
    if bundled.is_file():
        return str(bundled)
    return shutil.which(exe_name)


def ffmpeg_available() -> bool:
    """True when FFmpeg is available (needed for merge/conversion)."""
    return ffmpeg_path() is not None


def js_runtime_path() -> str | None:
    """The Deno binary yt-dlp should use for YouTube's JS challenges.

    Bundled with the app (see `build.py`); falls back to `deno` on PATH. Without
    a JS runtime YouTube extraction is degraded and misses formats.
    """
    exe_name = "deno.exe" if os.name == "nt" else "deno"
    bundled = get_resource_path(exe_name)
    if bundled.is_file():
        return str(bundled)
    return shutil.which(exe_name)


# ----------------------------------------------------------------------
# Generic media-URL discovery
# ----------------------------------------------------------------------
# yt-dlp's generic extractor only looks for media through a fixed list of
# known player patterns (JW Player, flowplayer, cinerama, ...). Sites that
# build the player with a plain JS call — and every clone/mirror of them —
# are therefore extracted without their HLS ladder, even though the manifest
# URL is sitting in the HTML as a normal string.
#
# Scanning the whole document for media URLs fixes that for any domain, with
# no per-site list to maintain. It only runs when an extractor gave us nothing
# with a known resolution, so working extractions are untouched.

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_MEDIA_URL_RE = re.compile(
    r"""https?://[^\s"'<>\\]{2,500}?\.(?:m3u8|mp4|webm|mkv|m4v)(?:\?[^\s"'<>\\]*)?""",
    re.IGNORECASE,
)
_RELATIVE_MEDIA_RE = re.compile(
    r"""["'](/[^\s"'<>\\]{1,300}?\.(?:m3u8|mp4|webm|mkv|m4v)(?:\?[^\s"'<>\\]*)?)["']""",
    re.IGNORECASE,
)
_MEDIA_PATH_SUFFIXES = (".m3u8", ".mp4", ".webm", ".mkv", ".m4v", ".ts")

_MAX_SCAN_BYTES = 5 * 1024 * 1024
_MAX_CANDIDATES = 6
_MAX_EMBEDS = 5
_MAX_MANIFESTS = 8

# Player/embed pages referenced by the document. Kept narrow on purpose:
# <iframe src> plus the data-* attributes players are usually wired to.
_IFRAME_SRC_RE = re.compile(r'<iframe[^>]+src\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_EMBED_DATA_RE = re.compile(
    r'data-(?:source|src|video|url|iframe|player|embed|file)\s*=\s*["\']([^"\']{8,500})["\']',
    re.IGNORECASE,
)
# Static assets that are never a player page.
_ASSET_PATH_RE = re.compile(
    r"\.(?:png|jpe?g|gif|webp|svg|ico|bmp|css|js|mjs|json|xml|txt|woff2?|ttf|eot|map)(?:$|[?#])",
    re.IGNORECASE,
)
# Path shapes that normally mean "this is a player page".
_PLAYER_PATH_RE = re.compile(r"/(?:play|embed|player|watch|e|v|videos?\b)", re.IGNORECASE)

# Related-video cards ship their preview clip in one of these attributes. The
# card is not the page's main stream, so its URL must not become a candidate.
_RELATED_MEDIA_ATTR_RE = re.compile(
    r"""\bdata-(?:mediabook|preview|trailer|teaser)\s*=\s*(?:"[^"]*"|'[^']*')""",
    re.IGNORECASE,
)
_RELATED_MEDIA_VALUE_RE = re.compile(
    r"""\bdata-(?:mediabook|preview|trailer|teaser)\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)
# A player that is built in JavaScript: no media URL in the HTML, only a
# container the site's script fills in. Such pages need the browser fallback.
_JS_PLAYER_RE = re.compile(
    r"""id\s*=\s*["']video-player(?:-area)?["']"""
    r"""|data-mpu\s*="""
    r"""|class\s*=\s*["'][^"']*\bresponsive-player\b""",
    re.IGNORECASE,
)

# Metadata read straight from the page, used when no extractor could give us
# any (which is exactly when the media scan kicks in).
_OG_TITLE_RE = re.compile(
    r'<meta[^>]+property\s*=\s*["\']og:title["\'][^>]+content\s*=\s*["\']([^"\']*)["\']',
    re.IGNORECASE,
)
_TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property\s*=\s*["\']og:image["\'][^>]+content\s*=\s*["\']([^"\']*)["\']',
    re.IGNORECASE,
)


class _YtdlpLogger:
    """Bridge yt-dlp's logger into the application logger (flow.md #36)."""

    def debug(self, msg):
        # yt-dlp routes info through debug() with a "[debug] " prefix.
        if str(msg).startswith("[debug] "):
            return
        logger.debug(msg)

    def info(self, msg):
        logger.debug(msg)

    def warning(self, msg):
        logger.warning(msg)

    def error(self, msg):
        logger.error(msg)


@dataclass
class DownloadResult:
    ok: bool
    output_file: Optional[str] = None
    error: Optional[ApplicationError] = None


# Same variable name as the server build, so a shell can override the proxy
# stored in config.json without editing the file.
PROXY_ENV = "YTDLP_PROXY"

# A browser-resolved manifest is reused for this long: the preview and the
# download then share one browser run. After it expires (or a download fails
# with a network error) the URL is resolved again.
BROWSER_MANIFEST_TTL = 5 * 60.0


class YtdlpClient:
    """Thin, blocking wrapper around yt_dlp.YoutubeDL."""

    def __init__(
        self,
        config: dict,
        proxy_url: str | None = None,
        tor=None,
    ):
        self.config = config
        # Local fallback proxy (core.network); used only when no explicit
        # proxy is configured.
        self._fallback_proxy_url = proxy_url or None
        # Tor SOCKS listener started by the app (core.network.tor).
        self._tor_proxy_url: str | None = None
        self.tor = tor

        # Auto mode is per-link: only URLs that failed once use Tor. The flag
        # is thread-local so parallel downloads do not switch each other.
        self._local = threading.local()
        self._tor_urls: set[str] = set()
        self._tor_urls_lock = threading.Lock()

        # page url -> (deadline, manifest url, referer) for browser-resolved URLs.
        self._manifest_cache: dict[str, tuple[float, str, str]] = {}
        self._manifest_cache_lock = threading.Lock()

    def set_proxy(self, proxy_url: str | None) -> None:
        """Point yt-dlp/requests at the local fallback proxy (or None)."""
        self._fallback_proxy_url = proxy_url or None

    def set_tor_proxy(self, proxy_url: str | None) -> None:
        """Attach/detach the Tor listener started by the app."""
        self._tor_proxy_url = proxy_url or None

    def _proxy_mode(self) -> str:
        mode = str(self.config.get("proxy_mode", "auto")).strip().lower()
        return mode if mode in ("auto", "on", "off") else "auto"

    def _use_tor(self) -> bool:
        mode = self._proxy_mode()
        if mode == "on":
            return True
        if mode == "off":
            return False
        return bool(getattr(self._local, "use_tor", False))

    @contextmanager
    def _tor_scope(self, enabled: bool):
        previous = getattr(self._local, "use_tor", None)
        self._local.use_tor = bool(enabled)
        try:
            yield
        finally:
            if previous is None:
                self._local.__dict__.pop("use_tor", None)
            else:
                self._local.use_tor = previous

    def _requires_tor(self, url: str) -> bool:
        if self._proxy_mode() != "auto" or self.configured_proxy():
            return False
        key = (url or "").strip()
        with self._tor_urls_lock:
            return key in self._tor_urls

    def _mark_tor(self, url: str, info=None) -> None:
        keys = {(url or "").strip()}
        webpage = getattr(info, "webpage_url", None) if info is not None else None
        if webpage:
            keys.add(webpage.strip())
        with self._tor_urls_lock:
            self._tor_urls.update(keys)

    def _ensure_tor(self) -> bool:
        """Start Tor on demand and wait for its SOCKS listener."""
        if self.tor is None:
            return False
        try:
            timeout = float(self.config.get("tor_timeout", 90))
        except (TypeError, ValueError):
            timeout = 90.0
        proxy = self.tor.start_and_wait(timeout)
        if not proxy:
            logger.warning("[Tor] could not start")
            return False
        self.set_tor_proxy(proxy)
        return True

    def _should_retry_with_tor(self, err: ApplicationError) -> bool:
        if self._proxy_mode() != "auto":
            return False
        if self.configured_proxy() or self._use_tor():
            return False
        if err.code in (NETWORK, BLOCKED, GEO):
            return True
        return bool(getattr(self._local, "scan_network_failed", False))

    def configured_proxy(self) -> str | None:
        """Explicit proxy: `YTDLP_PROXY`, then `proxy_url` from config.

        Tor runs a SOCKS listener at 127.0.0.1:9050, so
        `socks5h://127.0.0.1:9050` sends both DNS and traffic through it.
        """
        env_proxy = (os.environ.get(PROXY_ENV) or "").strip()
        if env_proxy:
            return env_proxy
        return str(self.config.get("proxy_url") or "").strip() or None

    @property
    def proxy_url(self) -> str | None:
        """The proxy in effect: explicit, Tor (when in scope), then fallback."""
        explicit = self.configured_proxy()
        if explicit:
            return explicit
        if self._use_tor():
            return self._tor_proxy_url or self._fallback_proxy_url
        return self._fallback_proxy_url

    def _requests_proxies(self) -> dict | None:
        proxy = self.proxy_url
        if not proxy:
            return None
        return {"http": proxy, "https": proxy}

    def _get_content_length(
        self,
        url: str,
        headers: dict[str, str] | None = None,
    ) -> int | None:
        """Get media size from HTTP headers when yt-dlp has no filesize."""
        request_headers = {
            "User-Agent": _BROWSER_UA,
            **(headers or {}),
        }

        try:
            with requests.head(
                url,
                headers=request_headers,
                timeout=int(self.config.get("request_timeout", 30)),
                allow_redirects=True,
                proxies=self._requests_proxies(),
            ) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and content_length.isdigit():
                    return int(content_length)

        except Exception as exc:
            logger.debug(f"[size] HEAD request failed for {url}: {exc}")

        # Some servers do not support HEAD but do return the total size for
        # a one-byte range request.
        try:
            request_headers["Range"] = "bytes=0-0"

            with requests.get(
                url,
                headers=request_headers,
                timeout=int(self.config.get("request_timeout", 30)),
                stream=True,
                allow_redirects=True,
                proxies=self._requests_proxies(),
            ) as response:
                content_range = response.headers.get("Content-Range")

                if content_range and "/" in content_range:
                    total = content_range.rsplit("/", 1)[1]

                    if total.isdigit():
                        return int(total)

        except Exception as exc:
            logger.debug(f"[size] Range request failed for {url}: {exc}")

        return None

    # ------------------------------------------------------------------
    # OPTIONS
    # ------------------------------------------------------------------

    def _cookies_opts(self) -> dict:
        opts = {}
        cookies_file = str(self.config.get("cookies_file") or "").strip()
        if cookies_file and os.path.exists(cookies_file):
            opts["cookiefile"] = cookies_file

        browser = str(self.config.get("cookies_from_browser") or "").strip()
        if browser:
            opts["cookiesfrombrowser"] = (browser,)
        return opts

    def _base_opts(self, extra: dict | None = None) -> dict:
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
            "ignoreerrors": False,
            "no_color": True,
            "logger": _YtdlpLogger(),
            "socket_timeout": int(self.config.get("request_timeout", 30)),
            "retries": int(self.config.get("download_retry", 3)),
            # Keep partial downloads and resume them on the next run.
            "continuedl": True,
            "nopart": False,
        }
        if self.proxy_url:
            opts["proxy"] = self.proxy_url

        ffmpeg = ffmpeg_path()
        if ffmpeg:
            opts["ffmpeg_location"] = os.path.dirname(ffmpeg)

        deno = js_runtime_path()
        if deno:
            opts["js_runtimes"] = {"deno": {"path": os.path.dirname(deno)}}

        opts.update(self._cookies_opts())
        if extra:
            opts.update(extra)
        return opts

    # ------------------------------------------------------------------
    # EXTRACTION
    # ------------------------------------------------------------------

    def extract(self, url: str) -> VideoInfo:
        """Extract metadata + formats, using Tor only if the link is blocked."""
        self._local.scan_network_failed = False
        mode = self._proxy_mode()
        if mode == "on":
            self._ensure_tor()
        use_tor = mode == "auto" and self._requires_tor(url)
        if use_tor and not self._ensure_tor():
            use_tor = False

        with self._tor_scope(use_tor):
            try:
                return self._extract_once(url)
            except ApplicationError as err:
                if not self._should_retry_with_tor(err):
                    raise
                if not self._ensure_tor():
                    raise

                logger.info(f"[Tor] retrying blocked link through Tor: {url}")
                self._local.scan_network_failed = False
                with self._tor_scope(True):
                    info = self._extract_once(url)
                self._mark_tor(url, info)
                return info

    def _extract_once(self, url: str) -> VideoInfo:
        """Extract metadata + formats without downloading (flow.md #6)."""
        try:
            video, video_id = self._extract_with_ytdlp(url)
        except ApplicationError as err:
            # No extractor could make sense of this page. It may still carry
            # the stream in plain JS, so scan it before giving up.
            if err.code in (UNSUPPORTED, EXTRACTOR):
                scanned = self._scan_page_for_media(url)
                if scanned is not None:
                    return scanned
            raise

        # An extractor matched but gave us nothing with a known quality: the
        # page may still expose a better manifest than the one it picked.
        if self._needs_media_scan(video, url):
            scanned = self._scan_page_for_media(url, video_id, base=video)
            if scanned is not None:
                video = scanned

        return video

    def _extract_with_ytdlp(self, url: str) -> tuple[VideoInfo, Optional[str]]:
        """Run yt-dlp on the URL; returns the video info and its id."""
        opts = self._base_opts({"skip_download": True})
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except ApplicationError:
            raise
        except Exception as exc:
            err = translate_ytdlp_error(exc)
            logger.error(f"[yt-dlp] extract failed for {url}: {exc}", exc_info=True)
            raise err from exc

        if not info:
            raise app_error("extractor", detail="yt-dlp returned no info")

        # A playlist/collection: use its first playable entry.
        if info.get("entries"):
            entry = next((e for e in info["entries"] if e), None)
            if entry:
                info = entry

        video_info = self._to_video_info(info, url)
        self._fill_missing_filesizes(video_info, info)

        return video_info, info.get("id")

    def refresh_formats(self, url: str) -> VideoInfo:
        """Explicit format refresh (flow.md #59)."""
        return self.extract(url)

    def _fill_missing_filesizes(
        self,
        video_info: VideoInfo,
        info: dict,
    ) -> None:
        """Fill missing format sizes using HTTP Content-Length."""
        http_headers = info.get("http_headers") or {}

        for fmt in video_info.formats:
            if fmt.filesize is not None or fmt.filesize_approx is not None:
                continue

            # Manifest URLs such as m3u8 do not represent the final media size.
            if not fmt.url or ".m3u8" in fmt.url.lower():
                continue

            size = self._get_content_length(
                fmt.url,
                headers=http_headers,
            )

            if size is not None:
                fmt.filesize = size

    # ------------------------------------------------------------------
    # GENERIC MEDIA-URL DISCOVERY
    # ------------------------------------------------------------------

    @staticmethod
    def _is_media_url(url: str) -> bool:
        """True when the URL itself points at a media file, not a page."""
        path = urlparse(url).path.lower()
        return path.endswith(_MEDIA_PATH_SUFFIXES)

    @staticmethod
    def _needs_media_scan(video: VideoInfo, url: str) -> bool:
        if not video.formats or YtdlpClient._is_media_url(url):
            return False
        return not any(f.type == VIDEO and f.height for f in video.formats)

    def _fetch_page(self, url: str) -> Optional[tuple[str, str]]:
        """Download an HTML page; returns (final url after redirects, text)."""
        self._local.fetch_error = None
        try:
            response = requests.get(
                url,
                headers={"User-Agent": _BROWSER_UA, "Referer": url},
                timeout=int(self.config.get("request_timeout", 30)),
                allow_redirects=True,
                proxies=self._requests_proxies(),
            )
            response.raise_for_status()
        except Exception as exc:
            self._local.fetch_error = exc
            logger.debug(f"[scan] could not fetch page {url}: {exc}")
            return None

        if "html" not in (response.headers.get("content-type") or "").lower():
            return None
        return response.url, response.text[:_MAX_SCAN_BYTES]

    @staticmethod
    def _media_candidates(html: str, page_url: str, video_id=None) -> list[str]:
        """Every media URL found in the document (including inside scripts)."""
        text = html.replace("\\/", "/")  # JS-escaped slashes
        text = _RELATED_MEDIA_ATTR_RE.sub("", text)  # related-card previews

        found = list(_MEDIA_URL_RE.findall(text))
        found += [urljoin(page_url, m) for m in _RELATIVE_MEDIA_RE.findall(text)]

        def rank(url):
            clean = url.split("?")[0].lower()
            return (
                0 if clean.endswith(".m3u8") else 1,
                0 if video_id and video_id in url else 1,
            )

        unique = list(dict.fromkeys(found))
        return sorted(unique, key=rank)[:_MAX_CANDIDATES]

    @staticmethod
    def _related_preview_urls(page_html: str) -> set[str]:
        """Preview clips embedded in related-video cards, never the main stream."""
        values = _RELATED_MEDIA_VALUE_RE.findall(page_html)
        return {html.unescape(value.strip()) for value in values if value.strip()}

    @staticmethod
    def _is_js_player_page(page_html: str) -> bool:
        return bool(_JS_PLAYER_RE.search(page_html))

    @staticmethod
    def _page_metadata(html_text: str) -> dict:
        """Title/thumbnail from the page itself (og tags, then <title>)."""

        def first(match):
            return html.unescape(match.group(1)).strip() if match else None

        title = first(_OG_TITLE_RE.search(html_text)) or first(_TITLE_TAG_RE.search(html_text))
        return {"title": title, "thumbnail": first(_OG_IMAGE_RE.search(html_text))}

    @staticmethod
    def _referers_for(manifest_url: str, found_on: str) -> list[str]:
        """Referers to try for a manifest: its own origin, then the page's.

        CDNs of these players commonly require a Referer (they 403 without
        one); which one they accept differs, so both are attempted.
        """
        referers = []
        for url in (manifest_url, found_on):
            parsed = urlparse(url)
            if parsed.scheme and parsed.netloc:
                origin = f"{parsed.scheme}://{parsed.netloc}/"
                if origin not in referers:
                    referers.append(origin)
        return referers

    def _formats_from_url(self, url: str, referer: Optional[str] = None):
        """Ask yt-dlp to read formats straight from a media URL."""
        opts = self._base_opts({"skip_download": True})
        if referer:
            opts["http_headers"] = {"Referer": referer}

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info:
            return []
        return normalize_formats(info.get("formats") or [])

    @staticmethod
    def _embed_candidates(html: str, page_url: str) -> list[str]:
        """Player/embed pages referenced by the document, best first."""
        page_host = urlparse(page_url).netloc

        found = _IFRAME_SRC_RE.findall(html) + _EMBED_DATA_RE.findall(html)

        candidates = []
        for raw in found:
            url = urljoin(page_url, raw.strip())
            if not url.startswith(("http://", "https://")):
                continue
            if url == page_url or YtdlpClient._is_media_url(url):
                continue
            if _ASSET_PATH_RE.search(urlparse(url).path):
                continue
            candidates.append(url)

        def rank(url):
            parsed = urlparse(url)
            return (
                0 if parsed.netloc != page_host else 1,  # players are usually cross-host
                0 if _PLAYER_PATH_RE.search(parsed.path) else 1,
            )

        unique = list(dict.fromkeys(candidates))
        return sorted(unique, key=rank)[:_MAX_EMBEDS]

    def _config_api_manifest(self, player_url: str, player_html: str, page_url: str) -> Optional[str]:
        """Ask a player's `<base>/config?d=<domain>` endpoint for a signed manifest.

        Some player builds (JW-player based) do not expose the stream in the
        markup at all: they POST their own id plus the embedding domain and get
        a signed manifest URL back. Rules are based on the endpoint shape the
        page calls, not on any hostname.
        """
        if "/config?d=" not in player_html:
            return None

        parsed = urlparse(player_url)
        base = parsed.path.rstrip("/").rsplit("/", 1)[0]
        if not base:
            return None

        try:
            response = requests.post(
                f"{parsed.scheme}://{parsed.netloc}{base}/config",
                params={"d": urlparse(page_url).netloc},
                headers={
                    "User-Agent": _BROWSER_UA,
                    "Referer": page_url,
                    "Origin": f"{parsed.scheme}://{parsed.netloc}",
                    "Content-Type": "application/json",
                },
                data=b"",
                timeout=int(self.config.get("request_timeout", 30)),
                proxies=self._requests_proxies(),
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.debug(f"[scan] player config API failed for {player_url}: {exc}")
            return None

        for source in payload.get("sources") or []:
            file_url = (source or {}).get("file")
            if file_url and ".m3u8" in file_url:
                return file_url
        return None

    def _collect_manifests(
        self,
        page_html: str,
        page_url: str,
        video_id=None,
        embeds: list[str] | None = None,
    ) -> list[tuple[str, str]]:
        """Media manifests reachable from a page, with the page they were seen on.

        Covers the page itself plus one level of the player/embed pages it
        loads, so no per-site knowledge is needed.
        """
        manifests = [(url, page_url) for url in self._media_candidates(page_html, page_url, video_id)]

        for embed_url in (embeds if embeds is not None else self._embed_candidates(page_html, page_url)):
            fetched = self._fetch_page(embed_url)
            if not fetched:
                continue

            # Players often bounce to another host; the redirected URL is the
            # one that serves the config endpoint and the streams.
            player_url, player_html = fetched

            signed = self._config_api_manifest(player_url, player_html, page_url)
            if signed:
                manifests.append((signed, player_url))

            manifests.extend(
                (url, player_url) for url in self._media_candidates(player_html, player_url, video_id)
            )

        unique: list[tuple[str, str]] = []
        seen = set()
        for entry in manifests:
            if entry[0] in seen:
                continue
            seen.add(entry[0])
            unique.append(entry)
        return unique[:_MAX_MANIFESTS]

    def _resolve_manifest(self, candidates, wanted_id=None):
        """First candidate that parses and (optionally) contains the wanted id.

        Returns (manifest_url, referer) so the downloader can replay the
        headers the manifest needed.
        """
        for candidate, found_on in candidates:
            for referer in self._referers_for(candidate, found_on):
                try:
                    formats = self._formats_from_url(candidate, referer)
                except Exception as exc:
                    logger.debug(f"[scan] {candidate} unusable: {exc}")
                    continue

                if wanted_id is not None:
                    if any(f.format_id == wanted_id for f in formats):
                        return candidate, referer
                elif any(f.type == VIDEO for f in formats):
                    # A media playlist may declare no resolution at all; it is
                    # still a usable stream, so do not reject it for that.
                    return candidate, referer

        return None

    def _scan_page_for_media(self, page_url: str, video_id=None, base: Optional[VideoInfo] = None) -> Optional[VideoInfo]:
        """Find the real stream by scanning the page (and the players it loads)."""
        fetched = self._fetch_page(page_url)
        self._local.scan_network_failed = self._local.fetch_error is not None
        page = ""
        embeds = []
        related_previews: set[str] = set()
        browser_tried = False
        resolved = None

        if fetched:
            _, page = fetched
            embeds = self._embed_candidates(page, page_url)
            related_previews = self._related_preview_urls(page)

            # A JavaScript player has no media URL in the HTML; let the browser
            # run before trusting media URLs found elsewhere on the page.
            if self._is_js_player_page(page):
                browser_tried = True
                resolved = self._browser_manifest(page_url, related_previews)

            if resolved is None:
                resolved = self._resolve_manifest(
                    self._collect_manifests(page, page_url, video_id, embeds=embeds)
                )

        # A static fetch can fail while a real browser still loads the page
        # (cold proxy circuit, JS challenge); try the browser in both cases.
        if resolved is None:
            should_try_browser = (
                self._has_player_markup(page, embeds) if page else True
            )
            if should_try_browser and not browser_tried:
                resolved = self._browser_manifest(page_url, related_previews)
        if resolved is None:
            logger.info("[scan] no media manifest with resolvable quality found")
            return None

        manifest_url, referer = resolved
        logger.info(f"[scan] using media manifest found in the page: {manifest_url}")

        formats = self._formats_from_url(manifest_url, referer)
        metadata = self._page_metadata(page)
        title = (base.title if base else None) or metadata.get("title") or page_url
        thumbnail = (base.thumbnail if base else None) or metadata.get("thumbnail")

        return VideoInfo(
            url=page_url,
            title=title,
            thumbnail=thumbnail,
            duration=base.duration if base else None,
            uploader=base.uploader if base else None,
            webpage_url=page_url,
            extractor=base.extractor if base else None,
            formats=formats,
            source_url=manifest_url,
        )

    def _refresh_manifest(self, page_url: str, fmt: dict) -> Optional[tuple[str, str]]:
        """Re-resolve the manifest for a scanned job (its URL may have expired)."""
        cached = self._cached_manifest(
            page_url, expected_url=fmt.get("source_url")
        )
        if cached is not None:
            logger.info("[scan] reusing cached manifest for download")
            return cached

        fetched = self._fetch_page(page_url)
        page = ""
        embeds = []
        related_previews: set[str] = set()
        browser_tried = False
        resolved = None

        if fetched:
            _, page = fetched
            embeds = self._embed_candidates(page, page_url)
            related_previews = self._related_preview_urls(page)

            if self._is_js_player_page(page):
                browser_tried = True
                resolved = self._browser_manifest(page_url, related_previews)

            if resolved is None:
                candidates = self._collect_manifests(page, page_url, embeds=embeds)
                prefer_host = urlparse(fmt.get("source_url") or "").netloc or None
                if prefer_host:
                    candidates.sort(key=lambda entry: 0 if urlparse(entry[0]).netloc == prefer_host else 1)
                resolved = self._resolve_manifest(candidates, wanted_id=fmt.get("format_id"))

        if resolved is None:
            should_try_browser = (
                self._has_player_markup(page, embeds) if page else True
            )
            if should_try_browser and not browser_tried:
                resolved = self._browser_manifest(page_url, related_previews)
        return resolved

    def _cached_manifest(
        self,
        page_url: str,
        expected_url: Optional[str] = None,
    ) -> Optional[tuple[str, str]]:
        """A browser manifest still inside its TTL (and matching the format)."""
        key = (page_url or "").strip()
        now = time.monotonic()
        with self._manifest_cache_lock:
            entry = self._manifest_cache.get(key)
            if entry is None:
                return None
            deadline, url, referer = entry
            if now >= deadline:
                self._manifest_cache.pop(key, None)
                return None
        if expected_url and url != expected_url:
            return None
        return url, referer

    def _remember_manifest(self, page_url: str, url: str, referer: str) -> None:
        key = (page_url or "").strip()
        with self._manifest_cache_lock:
            self._manifest_cache[key] = (
                time.monotonic() + BROWSER_MANIFEST_TTL,
                url,
                referer or page_url,
            )

    def _forget_manifest(self, page_url: str) -> None:
        with self._manifest_cache_lock:
            self._manifest_cache.pop((page_url or "").strip(), None)

    def _segmented_connections(self) -> int:
        try:
            connections = int(
                self.config.get("download_connections", DEFAULT_CONNECTIONS)
            )
        except (TypeError, ValueError):
            connections = DEFAULT_CONNECTIONS
        connections = max(1, min(connections, MAX_CONNECTIONS))
        if self._use_tor():
            # Multiple streams over one Tor circuit do not add bandwidth.
            connections = min(connections, 2)
        return connections

    def _can_segment(
        self,
        fmt: dict,
        target_url: str,
        output_ext: str,
        connections: int,
    ) -> bool:
        if connections < 2 or output_ext != "mp4":
            return False
        if fmt.get("type") != "video":
            return False
        if "+" in str(fmt.get("format_id") or ""):
            return False
        if self.config.get("cookies_file") or self.config.get("cookies_from_browser"):
            return False

        path = urlparse(target_url).path.lower()
        if path.endswith((".m3u8", ".mpd")):
            return False
        return path.endswith((".mp4", ".m4v", ".webm")) or (
            str(fmt.get("ext") or "").lower() == "mp4"
        )

    def _browser_manifest(
        self,
        page_url: str,
        related_previews: set[str],
    ) -> Optional[tuple[str, str]]:
        """Browser fallback, reusing a recent result and rejecting related cards."""
        cached = self._cached_manifest(page_url)
        if cached is not None and cached[0] not in related_previews:
            logger.info("[scan] reusing cached browser manifest")
            return cached

        resolved = self._browser_resolve(page_url, related_previews)
        if resolved is None:
            return None
        if resolved[0] in related_previews:
            logger.info("[scan] browser only found a related-video preview; ignoring it")
            return None
        self._remember_manifest(page_url, resolved[0], resolved[1])
        return resolved

    @staticmethod
    def _has_player_markup(page_html: str, embeds: list[str]) -> bool:
        """True when a JS player may own the stream (so the browser is worth it)."""
        if embeds:
            return True
        if re.search(r"<(?:iframe|video)\b|videojs|jwplayer|plyr", page_html, re.I):
            return True
        return bool(_JS_PLAYER_RE.search(page_html))

    def _browser_resolve(
        self,
        page_url: str,
        related_previews: set[str] | None = None,
    ) -> Optional[tuple[str, str]]:
        """Last resort: let a real browser expose the player's signed manifest."""
        if not bool(self.config.get("browser_fallback", True)):
            return None
        try:
            from core.download.browser_probe import sniff_media
        except ImportError:
            logger.info("[scan] browser fallback unavailable (playwright not installed)")
            return None

        try:
            timeout = float(self.config.get("browser_timeout", 30))
        except (TypeError, ValueError):
            timeout = 30.0

        media = sniff_media(
            page_url,
            proxy_url=self.proxy_url,
            timeout=timeout,
            block_ads=bool(self.config.get("browser_block_ads", True)),
            exclude=related_previews or set(),
        )
        if media is None:
            logger.info("[scan] browser fallback found no media")
            return None

        logger.info(f"[scan] browser fallback found media: {media.url}")
        return media.url, media.referer or page_url

    def _to_video_info(self, info: dict, url: str) -> VideoInfo:
        # Spam links are cut out of the title; if nothing but the link was left,
        # keep whatever yt-dlp gave us rather than storing an empty title.
        raw_title = info.get("title") or ""
        title = clean_title(raw_title) or raw_title or url

        live_status = info.get("live_status")
        is_live = bool(info.get("is_live")) or live_status == "is_live"

        return VideoInfo(
            url=url,
            title=title,
            thumbnail=info.get("thumbnail"),
            duration=info.get("duration"),
            uploader=info.get("uploader") or info.get("channel"),
            webpage_url=info.get("webpage_url") or url,
            extractor=info.get("extractor_key") or info.get("extractor"),
            formats=normalize_formats(info.get("formats") or []),
            is_live=is_live,
            live_status=live_status,
        )

    # ------------------------------------------------------------------
    # DOWNLOAD
    # ------------------------------------------------------------------

    def download(
        self,
        job,
        on_progress: Callable[[dict], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> DownloadResult:
        """Download with the proxy the link was resolved with."""
        mode = self._proxy_mode()
        needs_tor = mode == "on" or (
            mode == "auto" and self._requires_tor(job.url)
        )
        if self.configured_proxy():
            needs_tor = False
        if needs_tor and not self._ensure_tor():
            needs_tor = False

        with self._tor_scope(needs_tor):
            result = self._download(job, on_progress, should_cancel)

        if (
            not result.ok
            and result.error is not None
            and result.error.code in (NETWORK, HTTP)
        ):
            # The cached signed URL may have expired; resolve it again next time.
            self._forget_manifest(job.url)
        return result

    def _download(
        self,
        job,
        on_progress: Callable[[dict], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> DownloadResult:
        """Download job.url using job.selected_format."""
        fmt = job.selected_format or {}
        output_ext = fmt.get("output_ext") or "mp4"

        # Formats discovered by a page scan live in a manifest whose URL may
        # carry an expiring token, so resolve a fresh one (plus the headers it
        # needs) before downloading.
        target_url = job.url
        manifest_headers = None
        if fmt.get("source_url"):
            refreshed = self._refresh_manifest(job.url, fmt)
            if refreshed:
                target_url, referer = refreshed
                manifest_headers = {"Referer": referer}
            else:
                logger.warning(f"[{job.title}] could not refresh the media manifest; retrying the page")

        temp_dir = job_temp_dir(job.save_path, job.session_id, job.id)
        temp_dir.mkdir(parents=True, exist_ok=True)
        connections = self._segmented_connections()

        # A direct MP4/WebM with byte ranges is fetched by several connections
        # instead of yt-dlp's single stream. Anything else stays with yt-dlp.
        if self._can_segment(fmt, target_url, output_ext, connections):
            dest = expected_output_path(temp_dir, job.title, output_ext)
            headers = {"User-Agent": _BROWSER_UA, **(manifest_headers or {})}
            try:
                ok = download_segmented(
                    target_url,
                    dest,
                    connections=connections,
                    headers=headers,
                    proxies=self._requests_proxies(),
                    timeout=float(self.config.get("request_timeout", 30)),
                    on_progress=on_progress,
                    should_cancel=should_cancel,
                )
            except SegmentedCancelled:
                return DownloadResult(False, error=app_error(CANCELLED))
            except Exception as exc:
                logger.warning(
                    f"[{job.title}] parallel download failed; using yt-dlp: {exc}"
                )
                ok = False
            if ok:
                return self._move_output_out(job, temp_dir, output_ext)

        progress_hook = self._make_progress_hook(on_progress, should_cancel)
        if connections > 1 and urlparse(target_url).path.lower().endswith((".m3u8", ".mpd")):
            base_hook = progress_hook

            def progress_hook(data, _base=base_hook, _connections=connections):
                _base({**data, "connections": _connections})

        opts = self._base_opts({
            "format": fmt.get("format_id") or "best",
            "outtmpl": build_output_template(job.title),
            "paths": {"home": str(temp_dir)},
            "progress_hooks": [progress_hook],
        })
        # HLS/DASH fragments benefit from concurrency; direct downloads ignore it.
        opts["concurrent_fragments"] = max(1, connections)
        if manifest_headers:
            opts["http_headers"] = manifest_headers

        if output_ext == "mp4":
            opts["merge_output_format"] = "mp4"

        if fmt.get("type") == "audio" and output_ext == "mp3":
            opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": str(fmt.get("bitrate") or 192),
            }]

        try:
            temp_dir.mkdir(parents=True, exist_ok=True)
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([target_url])
        except _Cancelled:
            return DownloadResult(False, error=app_error(CANCELLED))
        except Exception as exc:
            if should_cancel is not None and should_cancel():
                return DownloadResult(False, error=app_error(CANCELLED))
            err = translate_ytdlp_error(exc)
            logger.error(f"[{job.title}] yt-dlp download failed: {exc}", exc_info=True)
            return DownloadResult(False, error=err)

        if should_cancel is not None and should_cancel():
            return DownloadResult(False, error=app_error(CANCELLED))

        return self._move_output_out(job, temp_dir, output_ext)

    @staticmethod
    def _move_output_out(job, temp_dir: Path, output_ext: str) -> DownloadResult:
        """Move the finished file out of the scratch folder (flow.md #27).

        Same-filesystem rename, so the save folder gets the file complete or
        not at all. Whatever else the scratch folder holds (``.part``,
        ``.ytdl``, ``.temp.*``) is discarded with it.
        """
        produced = resolve_output_file(temp_dir, job.title, output_ext)
        try:
            if produced is None:
                return DownloadResult(False, error=app_error(OUTPUT_MISSING))

            job.save_path.mkdir(parents=True, exist_ok=True)
            final_path = job.save_path / produced.name
            shutil.move(str(produced), str(final_path))
            return DownloadResult(True, output_file=str(final_path))
        except OSError as exc:
            logger.error(f"[{job.title}] could not move output out of the temp folder: {exc}")
            return DownloadResult(False, error=translate_ytdlp_error(exc))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def _make_progress_hook(on_progress, should_cancel):
        def _hook(data: dict):
            if should_cancel is not None and should_cancel():
                raise _Cancelled()
            if on_progress is not None:
                on_progress(_progress_event(data))
        return _hook


def _progress_event(data: dict) -> dict:
    """Normalize a raw yt-dlp progress dict into the app's progress event."""
    total = data.get("total_bytes") or data.get("total_bytes_estimate")
    return {
        "status": data.get("status"),
        "downloaded_bytes": data.get("downloaded_bytes") or 0,
        "total_bytes": total,
        "speed": data.get("speed"),
        "eta": data.get("eta"),
        "connections": data.get("connections"),
    }

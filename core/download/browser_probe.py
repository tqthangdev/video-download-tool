"""Last-resort media sniffing in a real browser.

The static scanner only reads HTML, so a player built in JavaScript (usually
inside an iframe) never exposes its stream to it. This module loads the page in
system Chrome, tries to start playback, and returns the first HLS/DASH/direct
media URL the player requests.

Nodriver (a stealth-driven Chrome) is tried first; Playwright is the fallback
for hosts/browsers nodriver cannot drive. It is only called after the static
scan failed. Ads are filtered on a best-effort basis: known ad/tracker hosts and
paths, ad-looking iframes, popups, images, fonts and video segments (only the
manifest is needed) are blocked.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
NAV_TIMEOUT_MS = 20000
# Downloads run in parallel; serialise probes so they do not spawn a browser
# per worker at once.
_PROBE_LOCK = threading.Lock()
CLICK_TIMEOUT_MS = 600
POLL_MS = 400
CANDIDATE_GRACE = 2.0

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

LAUNCH_ARGS = (
    "--autoplay-policy=no-user-gesture-required",
    "--disable-blink-features=AutomationControlled",
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--mute-audio",
    "--no-first-run",
    "--no-default-browser-check",
)

PLAY_SELECTORS = (
    "#promo-start",
    ".vjs-big-play-button",
    ".plyr__control--overlaid",
    "[data-plyr='play']",
    "[data-action='play']",
    "[class*='play-button']",
    "button[aria-label*='play' i]",
    "button[title*='play' i]",
)

SEGMENT_URL_RE = re.compile(r"\.(?:ts|m4s|jpg|jpeg|png|aac|m4a|vtt)(?:$|[?#])", re.I)

HLS_TYPES = ("mpegurl",)
DASH_TYPES = ("dash+xml",)
VIDEO_PREFIX = "video/"

# A conservative list: only well-known ad/tracker hosts. Players and their CDNs
# are not on it.
AD_HOSTS = (
    "doubleclick.net",
    "googlesyndication.com",
    "googleadservices.com",
    "googletagservices.com",
    "googletagmanager.com",
    "google-analytics.com",
    "amazon-adsystem.com",
    "adnxs.com",
    "adsystem.com",
    "criteo.com",
    "criteo.net",
    "taboola.com",
    "outbrain.com",
    "pubmatic.com",
    "rubiconproject.com",
    "openx.net",
    "zedo.com",
    "mgid.com",
    "revcontent.com",
    "propellerads.com",
    "onclickads.net",
    "adsterra.com",
    "popads.net",
    "popcash.net",
    "exoclick.com",
    "juicyads.com",
    "trafficjunky.net",
    "ad-delivery.net",
    "adnium.com",
    "clickadu.com",
    "hilltopads.net",
    "clickaine.com",
    "adcash.com",
    "bidvertiser.com",
    "media.net",
    "smartadserver.com",
    "yieldmo.com",
    "teads.tv",
    "sharethrough.com",
)

AD_PATH_RE = re.compile(
    r"(?:^|[/._-])(?:ads?|adserver|advert(?:ising)?|banner|popunder|prebid)(?:[/._-]|$)",
    re.I,
)
AD_FRAME_RE = re.compile(
    r"(?:^|[/._-])(?:ads?|adserver|advert(?:ising)?|banner|promo|popunder|click)(?:[/._-]|$)",
    re.I,
)
PLAYER_FRAME_RE = re.compile(
    r"player|embed|videojs|plyr|jwplayer|video", re.I
)


@dataclass
class SniffedMedia:
    """A media URL captured from browser traffic."""

    url: str
    referer: Optional[str] = None
    content_type: str = ""
    kind: str = "hls"  # hls | dash | file


def sniff_media(
    page_url: str,
    *,
    proxy_url: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT,
    block_ads: bool = True,
    prefer_nodriver: bool = True,
    exclude: Optional[set[str]] = None,
) -> Optional[SniffedMedia]:
    """Load `page_url` in a browser and return the first media URL it requests.

    Nodriver is tried first because it drives a real Chrome without Playwright's
    automation fingerprints; Playwright remains the fallback. Returns None when
    no browser is available; the caller then keeps its "unsupported" result.
    """
    if not _PROBE_LOCK.acquire(timeout=timeout):
        logger.info("[browser] another probe is still running; skipping")
        return None

    excluded = exclude or set()
    deadline = time.monotonic() + timeout
    try:
        if prefer_nodriver:
            media = _sniff_with_nodriver(
                page_url,
                proxy_url=proxy_url,
                timeout=min(20.0, timeout),
                block_ads=block_ads,
                exclude=excluded,
            )
            if media is not None:
                return media

        remaining = max(5.0, deadline - time.monotonic())
        return _sniff_with_playwright(
            page_url,
            proxy_url=proxy_url,
            timeout=remaining,
            block_ads=block_ads,
            exclude=excluded,
        )
    finally:
        _PROBE_LOCK.release()


def _sniff_with_playwright(
    page_url: str,
    *,
    proxy_url: Optional[str],
    timeout: float,
    block_ads: bool,
    exclude: set[str],
) -> Optional[SniffedMedia]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.info("[browser] playwright is not installed; fallback unavailable")
        return None

    try:
        proxy = _proxy_config(proxy_url)
        with sync_playwright() as playwright:
            browser = _launch(playwright)
            if browser is None:
                return None
            try:
                return _sniff_in_browser(
                    browser, page_url, proxy, timeout, block_ads, exclude
                )
            finally:
                browser.close()
    except Exception:  # noqa: BLE001 - never break extraction because of the browser
        logger.warning("[browser] media probe failed", exc_info=True)
        return None


# ----------------------------------------------------------------------
# NODRIVER
# ----------------------------------------------------------------------

def _sniff_with_nodriver(
    page_url: str,
    *,
    proxy_url: Optional[str],
    timeout: float,
    block_ads: bool,
    exclude: set[str],
) -> Optional[SniffedMedia]:
    try:
        import nodriver as uc
        from nodriver import cdp
    except ImportError:
        logger.info("[browser] nodriver is not installed")
        return None

    try:
        return asyncio.run(
            _nodriver_probe(uc, cdp, page_url, proxy_url, timeout, block_ads, exclude)
        )
    except RuntimeError as exc:
        # asyncio.run cannot be used from a thread that already has a loop.
        logger.info("[browser] nodriver unavailable here: %s", exc)
        return None
    except Exception:  # noqa: BLE001 - never break extraction because of the browser
        logger.warning("[browser] nodriver probe failed", exc_info=True)
        return None


async def _nodriver_probe(
    uc,
    cdp,
    page_url: str,
    proxy_url: Optional[str],
    timeout: float,
    block_ads: bool,
    exclude: set[str],
) -> Optional[SniffedMedia]:
    candidates: dict[str, SniffedMedia] = {}

    def remember(url: str, content_type: str = "") -> None:
        if not url.startswith(("http://", "https://")):
            return
        if url in exclude or _is_ad_url(url, page_url):
            return
        kind = _media_kind(url, content_type)
        if kind is None:
            return
        candidates[url] = SniffedMedia(
            url, page_url, content_type, kind
        )

    def on_request(event) -> None:
        try:
            remember(event.request.url)
        except Exception:
            pass

    def on_response(event) -> None:
        try:
            remember(
                event.response.url,
                (event.response.mime_type or "").lower(),
            )
        except Exception:
            pass

    args = [
        "--disable-blink-features=AutomationControlled",
        "--mute-audio",
        "--autoplay-policy=no-user-gesture-required",
        "--no-first-run",
        "--no-default-browser-check",
        # The page must keep running while the window sits minimized in the
        # taskbar; minimize happens through CDP once the page has loaded.
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
        "--window-size=1280,720",
    ]
    proxy_arg = _chrome_proxy_server(proxy_url)
    if proxy_arg:
        args.append(proxy_arg)

    browser = await uc.start(
        headless=_nodriver_headless(),
        browser_args=args,
        lang="en-US",
    )
    try:
        page = await browser.get(page_url)
        await page.send(cdp.network.enable())
        page.add_handler(cdp.network.RequestWillBeSent, on_request)
        page.add_handler(cdp.network.ResponseReceived, on_response)

        if block_ads:
            try:
                await page.send(cdp.network.set_blocked_ur_ls(urls=_ad_block_patterns()))
            except Exception:
                pass

        await page.sleep(4)
        # Let the page load first, then minimize through CDP: the flag alone is
        # honoured by some window managers and ignored by others.
        try:
            await page.minimize()
        except Exception as exc:
            logger.debug("[browser] could not minimize: %s", exc)

        for selector in (
            ".play-button",
            "#promo-start",
            ".vjs-big-play-button",
            ".plyr__control--overlaid",
            "button[aria-label*='play' i]",
        ):
            try:
                element = await page.select(selector, timeout=1)
            except Exception:
                element = None
            if element:
                try:
                    await element.click()
                    break
                except Exception:
                    pass

        # The player sometimes focuses/restores its window; put it back down.
        try:
            await page.minimize()
        except Exception:
            pass

        deadline = time.monotonic() + timeout
        first_candidate_at = None
        while time.monotonic() < deadline:
            await page.sleep(1)
            best = _best_nodriver_candidate(candidates, page_url)
            if best is not None:
                if _matches_page_code(best.url, page_url):
                    return best
                if first_candidate_at is None:
                    first_candidate_at = time.monotonic()
                elif time.monotonic() - first_candidate_at >= CANDIDATE_GRACE:
                    return best
        return _best_nodriver_candidate(candidates, page_url)
    finally:
        try:
            browser.stop()
        except Exception:
            pass


def _nodriver_headless() -> bool:
    """A real window is stealthier, but only when a desktop session exists."""
    if sys.platform in ("win32", "darwin"):
        return False
    return not bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _chrome_proxy_server(proxy_url: Optional[str]) -> Optional[str]:
    if not proxy_url:
        return None
    parsed = urlparse(proxy_url)
    if not parsed.hostname:
        return None
    scheme = parsed.scheme.lower()
    if scheme in ("socks5", "socks5h", "socks4", "socks4a"):
        mapped = "socks5" if scheme.startswith("socks5") else "socks4"
        return f"--proxy-server={mapped}://{parsed.hostname}:{parsed.port or 1080}"
    if parsed.username or parsed.password:
        # Chrome cannot carry proxy credentials in --proxy-server; the
        # Playwright fallback handles authenticated HTTP proxies.
        return None
    return f"--proxy-server=http://{parsed.hostname}:{parsed.port or 8080}"


def _ad_block_patterns() -> list[str]:
    patterns = ["*Top_Banner*", "*banner_*", "*black.html*", "*out.php*"]
    for host in AD_HOSTS:
        patterns += [f"*://{host}/*", f"*://*.{host}/*"]
    return patterns


def _page_code(page_url: str) -> str:
    match = re.search(r"([a-z]{2,10}[-_]\d{2,6})", urlparse(page_url).path.lower())
    return match.group(1).replace("_", "-") if match else ""


def _matches_page_code(url: str, page_url: str) -> bool:
    code = _page_code(page_url)
    if not code:
        return False
    return code in url.lower().replace("_", "-")


def _slug_tokens(page_url: str) -> set[str]:
    stop = {
        "video", "videos", "watch", "html", "php", "decensored",
        "uncensored", "censored", "leaked",
    }
    tokens = re.split(r"[^a-z0-9]+", urlparse(page_url).path.lower())
    return {
        token for token in tokens
        if len(token) >= 4 and not token.isdigit() and token not in stop
    }


def _best_nodriver_candidate(
    candidates: dict[str, SniffedMedia],
    page_url: str,
) -> Optional[SniffedMedia]:
    if not candidates:
        return None
    code = _page_code(page_url)
    tokens = _slug_tokens(page_url)

    def score(media: SniffedMedia) -> int:
        url = media.url.lower().replace("_", "-")
        value = 100 if code and code in url else 0
        value += sum(1 for token in tokens if token in url)
        if media.kind == "hls":
            value += 1
        return value

    return max(candidates.values(), key=score)


def _sniff_in_browser(
    browser: Any,
    page_url: str,
    proxy,
    timeout: float,
    block_ads: bool,
    exclude: set[str],
) -> Optional[SniffedMedia]:
    context = browser.new_context(
        proxy=proxy,
        ignore_https_errors=True,
        user_agent=BROWSER_UA,
        viewport={"width": 1280, "height": 720},
        locale="en-US",
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
    )

    candidates: dict[str, tuple[int, int, SniffedMedia]] = {}

    def remember(url: str, frame_url: str, content_type: str = "", kind: str = "") -> None:
        if not url.startswith(("http://", "https://")):
            return
        if url in exclude:
            return
        if _is_ad_url(url, page_url) or _is_ad_frame(frame_url, page_url):
            return
        media_kind = kind or _media_kind(url, content_type)
        if media_kind is None:
            return
        kind_rank = {"hls": 0, "dash": 1, "file": 2}[media_kind]
        frame_rank = _frame_rank(frame_url, page_url)
        prev = candidates.get(url)
        if prev is None or (kind_rank, frame_rank) < prev[:2]:
            candidates[url] = (
                kind_rank,
                frame_rank,
                SniffedMedia(url, frame_url or page_url, content_type, media_kind),
            )

    def route_handler(route, request) -> None:
        url = request.url
        frame_url = _request_frame_url(request, page_url)

        if request.is_navigation_request() and url == page_url:
            route.continue_()
            return

        if block_ads and (_is_ad_url(url, page_url) or _is_ad_frame(frame_url, page_url)):
            route.abort()
            return

        # The probe only needs the manifest: do not load images/fonts when ad
        # filtering is on, and never load the actual media segments (some
        # sites wrap TS in .jpg files).
        if request.resource_type in ("image", "font"):
            if block_ads:
                route.abort()
            else:
                route.continue_()
            return
        if request.resource_type == "media" or SEGMENT_URL_RE.search(url):
            remember(url, frame_url)
            route.abort()
            return

        route.continue_()

    def response_handler(response) -> None:
        url = response.url
        try:
            status = response.status
            content_type = (response.headers.get("content-type") or "").lower()
        except Exception:
            return
        if status < 200 or status >= 400:
            return
        kind = _media_kind(url, content_type)
        if kind is None:
            return
        if kind in ("hls", "dash") and not _is_valid_manifest(response, kind):
            return
        remember(url, _response_frame_url(response, page_url), content_type, kind)

    context.route("**/*", route_handler)
    context.on("response", response_handler)

    page = context.new_page()
    context.on("page", lambda popup: _close_popup(popup, page))

    try:
        page.goto(page_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
    except Exception as exc:
        logger.info("[browser] navigation failed: %s", exc)
        return None

    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    except Exception:
        pass
    page.wait_for_timeout(800)

    deadline = time.monotonic() + timeout
    next_trigger = 0.0
    first_candidate_at = None

    while time.monotonic() < deadline:
        best = _best_candidate(candidates)
        if best is not None:
            media, kind_rank, frame_rank = best
            # A manifest from the player frame (or the page itself) is final;
            # a lower-ranked frame gets a short grace period so the player can
            # expose its own manifest instead of an ad/trailer.
            if kind_rank == 0 and frame_rank <= 1:
                return media
            if first_candidate_at is None:
                first_candidate_at = time.monotonic()
            elif time.monotonic() - first_candidate_at >= CANDIDATE_GRACE:
                return media

        now = time.monotonic()
        if now >= next_trigger:
            _trigger_playback(page, page_url)
            next_trigger = now + 3.0
        page.wait_for_timeout(POLL_MS)

    best = _best_candidate(candidates)
    return best[0] if best else None


def _best_candidate(candidates):
    if not candidates:
        return None
    kind_rank, frame_rank, media = min(
        candidates.values(), key=lambda entry: (entry[0], entry[1])
    )
    return media, kind_rank, frame_rank


def _trigger_playback(page: Any, page_url: str) -> None:
    for frame in page.frames:
        frame_url = frame.url
        if frame_url != page_url and _is_ad_frame(frame_url, page_url):
            continue

        try:
            frame.evaluate(
                """() => {
                    for (const video of document.querySelectorAll('video')) {
                        try { video.muted = true; video.play(); } catch (e) {}
                    }
                    for (const button of document.querySelectorAll('#promo-start, .vjs-big-play-button, .plyr__control--overlaid, [data-plyr="play"], button')) {
                        const label = ((button.getAttribute('aria-label') || button.title || button.textContent || '') + '').toLowerCase();
                        if (button.id === 'promo-start'
                            || button.classList.contains('vjs-big-play-button')
                            || button.classList.contains('plyr__control--overlaid')
                            || /play|phát|xem/.test(label)) {
                            try { button.click(); } catch (e) {}
                        }
                    }
                }"""
            )
        except Exception:
            pass

        for selector in PLAY_SELECTORS:
            try:
                locator = frame.locator(selector).first
                if locator.count():
                    locator.click(timeout=CLICK_TIMEOUT_MS, force=True)
            except Exception:
                pass


def _launch(playwright: Any):
    for channel in ("chrome", "msedge"):
        try:
            return playwright.chromium.launch(
                channel=channel, headless=True, args=list(LAUNCH_ARGS)
            )
        except Exception:
            continue

    for name in (
        "chromium",
        "chromium-browser",
        "google-chrome",
        "google-chrome-stable",
        "microsoft-edge",
        "microsoft-edge-stable",
        "brave-browser",
    ):
        path = shutil.which(name)
        if not path:
            continue
        try:
            return playwright.chromium.launch(
                executable_path=path, headless=True, args=list(LAUNCH_ARGS)
            )
        except Exception:
            continue

    try:
        return playwright.chromium.launch(headless=True, args=list(LAUNCH_ARGS))
    except Exception:
        logger.info("[browser] no Chrome/Chromium/Edge available")
        return None


def _proxy_config(proxy_url: Optional[str]):
    if not proxy_url:
        return None
    parsed = urlparse(proxy_url)
    if not parsed.scheme or not parsed.hostname:
        return {"server": proxy_url}

    scheme = {"socks5h": "socks5", "socks4a": "socks4"}.get(
        parsed.scheme.lower(), parsed.scheme.lower()
    )
    server = f"{scheme}://{parsed.hostname}"
    if parsed.port:
        server += f":{parsed.port}"

    config = {"server": server}
    if parsed.username:
        config["username"] = unquote(parsed.username)
        config["password"] = unquote(parsed.password or "")
    return config


def _media_kind(url: str, content_type: str = "") -> Optional[str]:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    content = (content_type or "").lower()
    path = parsed.path.lower()
    if any(token in content for token in HLS_TYPES) or path.endswith(".m3u8"):
        return "hls"
    if any(token in content for token in DASH_TYPES) or path.endswith(".mpd"):
        return "dash"
    if content.startswith(VIDEO_PREFIX) or path.endswith((".mp4", ".m4v", ".webm")):
        return "file"
    return None


def _is_valid_manifest(response, kind: str) -> bool:
    try:
        body = response.text()
    except Exception:
        return True  # content type/extension already matched
    if kind == "hls":
        return body.lstrip("\ufeff \t\r\n").startswith("#EXTM3U")
    if kind == "dash":
        return "<MPD" in body[:2048]
    return True


def _is_ad_url(url: str, page_url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if any(host == blocked or host.endswith("." + blocked) for blocked in AD_HOSTS):
        return True
    return bool(AD_PATH_RE.search(parsed.path))


def _is_ad_frame(frame_url: str, page_url: str) -> bool:
    if not frame_url or frame_url == page_url:
        return False
    return bool(AD_FRAME_RE.search(urlparse(frame_url).path))


def _frame_rank(frame_url: str, page_url: str) -> int:
    if not frame_url or frame_url == page_url:
        return 1
    if PLAYER_FRAME_RE.search(frame_url):
        return 0
    if _is_ad_frame(frame_url, page_url):
        return 3
    return 2


def _request_frame_url(request, fallback: str) -> str:
    try:
        frame = request.frame
        return frame.url or fallback
    except Exception:
        return fallback


def _response_frame_url(response, fallback: str) -> str:
    try:
        frame = response.frame
        return frame.url or fallback
    except Exception:
        return fallback


def _close_popup(popup, main_page) -> None:
    if popup is main_page:
        return
    try:
        popup.close()
    except Exception:
        pass

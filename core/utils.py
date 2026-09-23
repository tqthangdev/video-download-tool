import glob as glob_module
import json
import re
import sys
from pathlib import Path


# Linux limits each path component to 255 bytes (NAME_MAX) — Windows to 255
# UTF-16 code units. Multibyte UTF-8 characters (Vietnamese, CJK, emoji) can
# blow past that even at well under 255 *characters*, so keep a safe margin
# and truncate by bytes, never splitting a character in the middle.
MAX_FILENAME_BYTES = 255

# Byte budget for the *stem* of an output filename. The rest is reserved for
# the suffixes yt-dlp may append while downloading and post-processing
# (".mp4.part-Frag9999.part" is the longest realistic one).
MAX_STEM_BYTES = 200


def safe_filename(name: str, max_length: int = MAX_FILENAME_BYTES):
    # 1. Strip characters forbidden by the OS
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)

    # 2. Truncate long names — by *bytes* so multibyte UTF-8 (Vietnamese, CJK,
    #    emoji) can't exceed the filesystem's per-component byte limit.
    encoded = name.encode("utf-8", errors="ignore")
    if len(encoded) > max_length:
        # Cut at the byte boundary, then trim any trailing partial character.
        encoded = encoded[:max_length]
        name = encoded.decode("utf-8", errors="ignore")

    # 3. Strip trailing dots and spaces
    name = name.rstrip(" .")

    return name


def get_base_dir() -> Path:
    """Return the directory containing the executable or project root."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent

    return Path(__file__).parent.parent


def get_resource_path(relative_path: str) -> Path:
    """Return the path to a bundled/read-only application resource."""
    if getattr(sys, "frozen", False):
        base_path = Path(
            getattr(sys, "_MEIPASS", None)
            or Path(sys.executable).parent
        )
    else:
        base_path = Path(__file__).parent.parent

    return base_path / relative_path


BASE_DIR = get_base_dir()


def get_user_data_dir() -> Path:
    """
    Return a writable directory for application data.

    The data directory is created right next to the executable (release)
    or in the project root (dev), so config.json / jobs.db live wherever
    the app is run from.
    """
    data_dir = BASE_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    return data_dir


# Writable application data directory.
DATA_DIR = get_user_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)


DEFAULT_CONFIG = {
    "max_workers": 3,
    "download_path": str(Path.home() / "Downloads"),
    "default_video_quality": "720p",
    "default_audio_bitrate": "128k",
    "default_audio_bitrates": [128, 192, 320],
    "prefer": "video",
    "shutdown_after_complete": False,
    "shutdown_delay": 30,
    "language": "en",
    "request_timeout": 30,
    "download_retry": 3,
    "cookies_file": "",
    "cookies_from_browser": "",
}


def get_config_path() -> Path:
    """Return the writable user configuration path."""
    return DATA_DIR / "config.json"


def load_config() -> dict:
    """
    Load configuration from the writable user data directory.

    A bundled config.json is used as the initial template when no
    user configuration exists yet.
    """
    config_path = get_config_path()
    bundled_config_path = get_resource_path("config.json")

    config = DEFAULT_CONFIG.copy()

    # Existing user configuration
    if config_path.exists() and config_path.stat().st_size > 0:
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)

            config.update(
                {
                    k: v
                    for k, v in user_config.items()
                    if v not in (None, "")
                }
            )

            # Add newly introduced default fields
            if set(DEFAULT_CONFIG) - set(user_config):
                try:
                    with open(config_path, "w", encoding="utf-8") as f:
                        json.dump(
                            config,
                            f,
                            indent=4,
                            ensure_ascii=False,
                        )
                except Exception as e:
                    from core.logger import logger

                    logger.error(
                        f"[config] Failed to update config.json: {e}"
                    )

        except Exception as e:
            from core.logger import logger

            logger.error(
                f"[config] Error reading config.json, using defaults: {e}"
            )

            try:
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(
                        config,
                        f,
                        indent=4,
                        ensure_ascii=False,
                    )
            except Exception:
                pass

    # No user config yet
    else:
        # If the bundled config exists, use it as the initial config.
        if bundled_config_path.exists():
            try:
                with open(
                    bundled_config_path,
                    "r",
                    encoding="utf-8",
                ) as f:
                    bundled_config = json.load(f)

                config.update(
                    {
                        k: v
                        for k, v in bundled_config.items()
                        if v not in (None, "")
                    }
                )

            except Exception as e:
                from core.logger import logger

                logger.error(
                    f"[config] Error reading bundled config.json: {e}"
                )

        # Create writable user config
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(
                    config,
                    f,
                    indent=4,
                    ensure_ascii=False,
                )

        except Exception as e:
            from core.logger import logger

            logger.error(
                f"[config] Failed to create config.json: {e}"
            )

    return config


def save_config(config: dict) -> bool:
    """Save configuration to the writable user data directory."""
    config_path = get_config_path()

    try:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(
                config,
                f,
                indent=4,
                ensure_ascii=False,
            )

        return True

    except Exception as e:
        from core.logger import logger

        logger.error(
            f"[config] Failed to write config.json: {e}"
        )

        return False


CONFIG = load_config()

# ================= TITLE CLEANUP =================

# Many sites stuff short links into the video title for SEO ("... https://bit.ly/xxxx").
# yt-dlp may also derive the title from a URL slug, leaving the link mangled into
# words ("https:  bit.ly 3IphDCM ..."). Strip those so filenames stay readable.
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_SHORTENER_RE = re.compile(
    r"\b(?:bit\.ly|bitly\.com|tinyurl\.com|goo\.gl|is\.gd|t\.co|ow\.ly|buff\.ly|"
    r"cutt\.ly|rebrand\.ly|shorturl\.at|short\.gy|rb\.gy|s\.id)"
    r"(?:\s*/\s*\S+|\s+\S*\d\S*)",
    re.IGNORECASE,
)
_SCHEME_RE = re.compile(r"https?\s*:?\s*/{0,2}", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")
# Separators left dangling once a link is cut out of the title.
_EDGE_JUNK_RE = re.compile(r"^[\s\-–—|~:/]+|[\s\-–—|~:]+$")


def clean_title(title: str) -> str:
    """Remove spam links from a video title and tidy the whitespace.

    Returns "" when nothing but the link was left, so callers can fall back to
    the original value instead of storing an empty title.
    """
    if not title:
        return ""

    cleaned = _URL_RE.sub(" ", title)
    cleaned = _SHORTENER_RE.sub(" ", cleaned)
    cleaned = _SCHEME_RE.sub(" ", cleaned)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    return _EDGE_JUNK_RE.sub("", cleaned).strip()


# ================= OUTPUT FILENAMES (flow.md #26) =================

# yt-dlp temporary names are not only suffixes: scratch copies use
# ``prepend_extension(name, "temp")`` -> ``Name.temp.mp4``, and fragmented
# downloads write ``Name.mp4.part-Frag<N>.part``. Match a marker as a whole
# dotted segment followed by either a separator or the end, so real names like
# ``my.partial.mp4`` are left alone.
_PARTIAL_NAME_RE = re.compile(r"\.(?:part|ytdl|temp)(?:[.-]|$)", re.IGNORECASE)


def is_partial_name(name: str) -> bool:
    """True for the temporary names yt-dlp writes while downloading.

    Covers ``.part`` / ``.part-Frag<N>.part`` (incomplete download),
    ``.temp.<ext>`` (post-processing scratch) and ``.ytdl`` (download state).
    """
    return bool(_PARTIAL_NAME_RE.search(name))


# Reverse of the markers above: strip them back off a temporary name to find
# the media file the scratch belongs to. ``Name.temp.mp4`` and
# ``Name.mp4.part`` both point at ``Name.mp4``.
_PARTIAL_TAIL_RE = re.compile(r"\.(?:part|ytdl)(?:-Frag\d+)?(?:\.part)?$", re.IGNORECASE)
_PARTIAL_TEMP_RE = re.compile(r"\.temp(?=\.[^.]+$)", re.IGNORECASE)


def _partial_base_stem(name: str) -> str:
    """Stem of the media file a temporary name belongs to (flow.md #27).

    ``foo.mp4.part`` / ``foo.mp4.part-Frag3.part`` / ``foo.mp4.ytdl`` and
    ``foo.temp.mp4`` all give ``foo``; a fragment partial keeps its own
    stem, so ``foo.f137.mp4.part`` gives ``foo.f137`` and never touches the
    merged ``foo.mp4``.
    """
    stripped = _PARTIAL_TAIL_RE.sub("", name)
    stripped = _PARTIAL_TEMP_RE.sub("", stripped)
    return Path(stripped).stem


def base_output_files(partials) -> list[Path]:
    """The media files a set of temporary files belongs to.

    A half-written ``Name.mp4`` must go together with the ``Name.mp4.part``
    or ``Name.temp.mp4`` that shares its stem — the temporary name says
    which file that is, so nothing is removed when there is no temporary
    file next to it.
    """
    partials = list(partials)
    partial_paths = set(partials)
    found = set()
    for path in partials:
        stem = _partial_base_stem(path.name)
        if not stem:
            continue
        escaped = glob_module.escape(stem)
        for sibling in path.parent.glob(f"{escaped}.*"):
            if sibling.is_file() and sibling not in partial_paths and not is_partial_name(sibling.name):
                found.add(sibling)
    return sorted(found)


def output_stem(title: str) -> str:
    """Build the output filename stem from the video title.

    Titles can be arbitrarily long (some sites use the whole description), and
    yt-dlp appends its own suffixes to the name it downloads to
    (``.mp4.part``, ``.mp4.part-Frag123.part``, ``.ytdl``). Keep the stem short
    enough that the longest of those still fits in MAX_FILENAME_BYTES.
    """
    return safe_filename(title, max_length=MAX_STEM_BYTES) or "video"


def build_output_template(title: str) -> str:
    """yt-dlp outtmpl (filename template, relative to the job save_path)."""
    return f"{output_stem(title)}.%(ext)s"


def expected_output_path(save_path: Path, title: str, output_ext: str) -> Path:
    """The deterministic final path for a job's chosen output format."""
    return Path(save_path) / f"{output_stem(title)}.{output_ext}"


def partial_files(save_path, title: str) -> list[Path]:
    """Temporary files yt-dlp left behind for this job's output stem."""
    folder = Path(save_path)
    if not folder.is_dir():
        return []

    stem = output_stem(title)
    escaped = glob_module.escape(stem)  # literal-match [ ] * ? in the real filename
    return [
        candidate
        for candidate in folder.glob(f"{escaped}.*")
        if candidate.is_file() and is_partial_name(candidate.name)
    ]


def resolve_output_file(save_path: Path, title: str, output_ext: str):
    """Find the produced file: exact expected name, else any non-partial match."""
    expected = expected_output_path(save_path, title, output_ext)
    if expected.exists():
        return expected

    stem = output_stem(title)
    escaped = glob_module.escape(stem)
    for candidate in sorted(Path(save_path).glob(f"{escaped}.*")):
        if is_partial_name(candidate.name):
            continue
        return candidate
    return None


def remove_partial_files(save_path, title: str, *, include_output: bool = False) -> int:
    """Delete a job's leftover temporary files; returns how many were removed.

    Paused jobs deliberately keep their partial files so yt-dlp can resume
    them, so this only runs once a job is really gone (deleted) or has failed
    for good.

    With ``include_output`` the media file each partial belongs to
    (``Name.mp4`` beside ``Name.mp4.part`` / ``Name.temp.mp4``) is removed as
    well. That only happens when a temporary file was actually found, so a
    finished download is never touched by a cleanup that has nothing to
    clean (flow.md #27).
    """
    from core.logger import logger

    partials = partial_files(save_path, title)
    targets = list(partials)
    if include_output:
        targets += base_output_files(partials)

    removed = 0
    for path in targets:
        try:
            path.unlink()
            removed += 1
        except OSError as exc:
            logger.warning(f"[cleanup] could not remove {path}: {exc}")
    return removed


def sweep_orphaned_partials(root: Path) -> list[Path]:
    """One-off cleanup: remove every leftover temp/part/ytdl file under root.

    Unlike remove_partial_files (per-job, matched by title stem), this scans
    the whole download tree regardless of which job owns a file — for
    clearing out orphans left by older app versions that failed to clean up
    (e.g. the glob-escaping bug), or files whose job record no longer exists.
    """
    from core.logger import logger

    root = Path(root)
    if not root.is_dir():
        return []

    removed = []
    for path in root.rglob("*"):
        if path.is_file() and is_partial_name(path.name):
            try:
                path.unlink()
                removed.append(path)
            except OSError as exc:
                logger.warning(f"[sweep] could not remove {path}: {exc}")
    return removed


# ================= LINK FILE VALIDATION (Add Queue by file) =================

# A line is considered a valid job entry if it looks like an http(s) URL.
URL_PATTERN = re.compile(r"^https?://\S+$", re.IGNORECASE)

# Reject files above this size before even trying to read them (a link list
# file should never be this large; avoids loading a huge binary into RAM).
MAX_LINK_FILE_BYTES = 5 * 1024 * 1024  # 5 MB

# How many leading bytes to sniff for a NUL byte (binary-content signature).
BINARY_SNIFF_BYTES = 8192


def _looks_binary(path: Path) -> bool:
    """Cheap binary-content check: text files essentially never contain a
    NUL byte, while executables/archives/media almost always do within the
    first few KB. This catches .exe/.dll/.zip/etc. regardless of extension,
    without needing to read the whole file."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(BINARY_SNIFF_BYTES)
    except OSError:
        return False  # let the caller's own read attempt report the error
    return b"\x00" in chunk


def parse_link_file(path) -> tuple[list, str | None, str | None]:
    """Read and validate a link-list file.

    Blank lines and lines starting with "#" are treated as comments and
    ignored (not counted as invalid). Every remaining line must match
    URL_PATTERN.

    Returns (urls, error_code, error_detail):
    - Success: (urls, None, None)
    - Failure: ([], error_code, error_detail)
      error_code is one of "too_large", "binary", "not_text", "read",
      "empty", "invalid".
    """
    file_path = Path(path)

    try:
        size = file_path.stat().st_size
    except OSError as e:
        return [], "read", str(e)

    if size > MAX_LINK_FILE_BYTES:
        return [], "too_large", None

    # Catches binaries (exe/dll/zip/media/...) regardless of extension,
    # before we ever try to decode the whole file as text.
    if _looks_binary(file_path):
        return [], "binary", None

    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [], "not_text", None
    except OSError as e:
        return [], "read", str(e)

    lines = [line.strip() for line in content.splitlines()]
    lines = [line for line in lines if line and not line.startswith("#")]

    if not lines:
        return [], "empty", None

    invalid_lines = [line for line in lines if not URL_PATTERN.match(line)]
    if invalid_lines:
        preview = "\n".join(invalid_lines[:5])
        if len(invalid_lines) > 5:
            preview += f"\n... (+{len(invalid_lines) - 5})"
        return [], "invalid", preview

    return lines, None, None
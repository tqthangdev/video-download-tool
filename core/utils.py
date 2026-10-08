import glob as glob_module
import json
import re
import shutil
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


def format_size(num_bytes) -> str:
    """Human-readable file size ("1.05 GB", "720 KB"), "" when unknown."""
    try:
        size = float(num_bytes)
    except (TypeError, ValueError):
        return ""
    if size <= 0:
        return ""

    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} B"
            text = f"{size:.2f}".rstrip("0").rstrip(".")
            return f"{text} {unit}"
        size /= 1024
    return f"{size:.2f} TB"


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
    "shutdown_after_complete": False,
    "shutdown_delay": 30,
    "language": "en",
    "request_timeout": 30,
    "download_retry": 3,
    "cookies_file": "",
    "cookies_from_browser": "",
    "network_enabled": True,
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
                    if k in DEFAULT_CONFIG and v not in (None, "")
                }
            )

            # Add newly introduced default fields and drop keys the app no
            # longer knows about (e.g. an option removed after a refactor).
            if set(DEFAULT_CONFIG) != set(user_config):
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
                        if k in DEFAULT_CONFIG and v not in (None, "")
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


# ================= DOWNLOAD SCRATCH FOLDERS (flow.md #27, #29) =================

# yt-dlp downloads and post-processes inside a per-job scratch folder
# (``<save_path>/.temp/<session_id>/<job_id>``). It is scoped by session because
# each session is its own database and numbers its jobs from 1, so job ids would
# otherwise collide across sessions. The folder is stable for a job, so yt-dlp
# can resume the ``.part`` file it left there (flow.md #29). The finished file is
# then moved out with a same-filesystem rename, so the save folder only ever
# receives complete outputs, and cleanup is a single rmtree of the job's folder.
TEMP_DIR_NAME = ".temp"


def job_temp_dir(save_path, session_id, job_id) -> Path:
    """Scratch folder yt-dlp downloads one job into."""
    return Path(save_path) / TEMP_DIR_NAME / str(session_id) / str(job_id)


def remove_job_temp_dir(save_path, session_id, job_id) -> None:
    """Delete a job's scratch folder with everything left in it."""
    if job_id is None:
        return
    shutil.rmtree(job_temp_dir(save_path, session_id, job_id), ignore_errors=True)


def remove_session_temp_dirs(save_path, session_id) -> None:
    """Delete every scratch folder belonging to one session."""
    if not session_id:
        return
    shutil.rmtree(Path(save_path) / TEMP_DIR_NAME / str(session_id), ignore_errors=True)


def cleanup_orphan_temp_dirs(save_path, keep_keys) -> int:
    """Delete scratch folders whose ``(session_id, job_id)`` is no longer live.

    ``keep_keys`` holds the ``(session_id, job_id)`` pairs of jobs that can
    still be resumed. Legacy ``.temp/<job_id>`` folders (written before sessions
    existed) cannot be resumed under the new layout, so they are removed too.
    """
    root = Path(save_path) / TEMP_DIR_NAME
    if not root.is_dir():
        return 0

    removed = 0
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.isdigit():
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
            continue

        session_id = entry.name
        for job_entry in entry.iterdir():
            if not job_entry.is_dir():
                continue
            try:
                job_id = int(job_entry.name)
            except ValueError:
                continue
            if (session_id, job_id) in keep_keys:
                continue
            shutil.rmtree(job_entry, ignore_errors=True)
            removed += 1
        try:
            entry.rmdir()
        except OSError:
            pass
    return removed


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
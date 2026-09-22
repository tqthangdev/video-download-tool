from datetime import datetime
import logging

from core.utils import BASE_DIR


LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOGS_DIR / f"{datetime.now():%Y-%m-%d}.log"


logger = logging.getLogger("VideoDownloadTool")
logger.setLevel(logging.DEBUG)


# File handler writes INFO+ logs (including yt-dlp diagnostics) to the
# writable user data directory. The GUI only shows concise messages; the
# full yt-dlp output belongs in this file (flow.md #36, #57).
file_handler = logging.FileHandler(
    LOG_FILE,
    encoding="utf-8",
)
file_handler.setLevel(logging.INFO)


formatter = logging.Formatter(
    "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

file_handler.setFormatter(formatter)


if not logger.handlers:
    logger.addHandler(file_handler)


__all__ = [
    "logger",
    "LOGS_DIR",
    "LOG_FILE",
]
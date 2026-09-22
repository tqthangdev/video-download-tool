import sys
from pathlib import Path


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


# --- Normal app run mode ---
import asyncio
from concurrent.futures import ThreadPoolExecutor

from PyQt6.QtWidgets import QApplication
from qasync import QEventLoop

from gui.main_window import MainWindow
from core.engine import Engine
from core.utils import CONFIG


def main():
    from PyQt6.QtGui import QIcon

    app = QApplication(sys.argv)

    icon_path = _get_base_dir() / "assets" / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    # yt-dlp downloads run in this pool so they never block the Qt event loop.
    # Reserve extra threads for interactive work (preview extraction, thumbnails).
    max_workers = int(CONFIG.get("max_workers", 3))
    loop.set_default_executor(ThreadPoolExecutor(max_workers=max_workers + 8))

    engine = Engine(max_workers=max_workers, config=CONFIG)
    window = MainWindow(engine)

    window.show()

    with loop:
        loop.run_forever()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        from core.logger import logger

        logger.critical("Critical error / crash occurred", exc_info=True)
        raise

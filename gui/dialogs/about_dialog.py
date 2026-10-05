"""About dialog: basic information about the app."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from core.i18n import tr
from gui.cursor_utils import apply_pointer_cursors
from gui.theme import HELP_TITLE_STYLE


def ytdlp_version() -> str:
    """The yt-dlp version this build uses ("" when it cannot be read)."""
    try:
        import yt_dlp

        return getattr(yt_dlp.version, "__version__", "") or ""
    except Exception:  # noqa: BLE001 - never break the dialog over this
        return ""


class AboutDialog(QDialog):
    """Modal showing basic information about the app."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("about_title"))
        self.setModal(True)
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)

        title_label = QLabel(tr("app_title"))
        title_label.setStyleSheet(HELP_TITLE_STYLE)
        title_label.setWordWrap(True)

        desc_label = QLabel(
            tr("about_desc").format(version=ytdlp_version() or "?")
        )
        desc_label.setWordWrap(True)
        desc_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        buttons = QDialogButtonBox()
        btn_ok = buttons.addButton(tr("ok"), QDialogButtonBox.ButtonRole.AcceptRole)
        btn_ok.clicked.connect(self.accept)

        layout.addWidget(title_label)
        layout.addWidget(desc_label)
        layout.addWidget(buttons)

        apply_pointer_cursors(self)

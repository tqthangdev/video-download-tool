"""About dialog: basic information about the app."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from core.i18n import tr
from core.updater.version import read_current_version
from gui.common.cursor_utils import apply_pointer_cursors
from gui.dialogs.version_dialog import display_version


def ytdlp_version() -> str:
    """The yt-dlp version this build uses ("" when it cannot be read)."""
    try:
        import yt_dlp

        return getattr(yt_dlp.version, "__version__", "") or ""
    except Exception:  # noqa: BLE001 - never break the dialog over this
        return ""


class AboutDialog(QDialog):
    """Modal showing basic information about the app."""

    def __init__(self, parent=None, on_check_version=None):
        super().__init__(parent)
        self.setWindowTitle(tr("about_title"))
        self.setModal(True)
        self.setMinimumWidth(400)

        self._on_check_version = on_check_version

        layout = QVBoxLayout(self)

        title_label = QLabel(tr("app_title"))
        title_label.setObjectName("dialog_title")
        title_label.setWordWrap(True)

        desc_label = QLabel(
            tr("about_desc").format(ytdlp_version=ytdlp_version() or "?")
        )
        desc_label.setWordWrap(True)
        desc_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        # "Check version" is an inline link opening the version dialog.
        self.version_label = QLabel()
        self.version_label.setTextFormat(Qt.TextFormat.RichText)
        self.version_label.linkActivated.connect(self._check_version)
        self._refresh_version()

        buttons = QDialogButtonBox()
        btn_ok = buttons.addButton(tr("ok"), QDialogButtonBox.ButtonRole.AcceptRole)
        btn_ok.clicked.connect(self.accept)

        layout.addWidget(title_label)
        layout.addWidget(desc_label)
        layout.addWidget(self.version_label)
        layout.addWidget(buttons)

        apply_pointer_cursors(self)

    def _refresh_version(self):
        self.version_label.setText(
            tr("about_version_line").format(
                version=display_version(read_current_version()),
                link=tr("about_check_version"),
            )
        )

    def _check_version(self, _link=None):
        if self._on_check_version is not None:
            self._on_check_version()

    def retranslate(self):
        self.setWindowTitle(tr("about_title"))
        self._refresh_version()

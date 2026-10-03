"""Help dialog: the description/recommendation of a settings option."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from core.i18n import tr
from gui.cursor_utils import apply_pointer_cursors
from gui.theme import HELP_TITLE_STYLE


class HelpDialog(QDialog):
    """Modal showing the detail + recommendation of an option."""

    def __init__(self, title: str, description: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("settings_help_title"))
        self.setModal(True)
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)

        title_label = QLabel(title)
        title_label.setStyleSheet(HELP_TITLE_STYLE)
        title_label.setWordWrap(True)

        desc_label = QLabel(description)
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

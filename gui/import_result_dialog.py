"""Result of a batch import ("add jobs from file").

Shows one row per outcome — imported / live / duplicate / error — each of the
detail rows expanding to the links it contains (title shown, full URL in the
tooltip). Imported needs no list: those are already in the queue.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from core.i18n import tr
from gui.cursor_utils import apply_pointer_cursors
from gui.theme import HELP_TITLE_STYLE, LIST_STYLE, OUTLINE_BUTTON_STYLE

ARROW_DOWN = "\u25bc"
ARROW_UP = "\u25b2"

_MAX_LIST_HEIGHT = 160
_ROW_HEIGHT = 22


class _Section(QWidget):
    """A collapsible row: a header with a count, and the links below it."""

    def __init__(self, label: str, items: list[dict], parent=None):
        super().__init__(parent)
        self._label = label
        self._items = items
        self._expanded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.toggle = QToolButton()
        self.toggle.setAutoRaise(True)
        self.toggle.setStyleSheet(OUTLINE_BUTTON_STYLE)
        self.toggle.setEnabled(bool(items))
        self.toggle.clicked.connect(self._toggle)
        layout.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignLeft)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.list.setFixedHeight(min(_MAX_LIST_HEIGHT, _ROW_HEIGHT * max(1, len(items)) + 8))
        self.list.setVisible(False)
        self.list.setStyleSheet(LIST_STYLE)
        for entry in items:
            text = entry.get("title") or entry.get("url") or ""
            if entry.get("reason"):
                text = f"{text} — {entry['reason']}"
            item = QListWidgetItem(text)
            item.setToolTip(entry.get("url") or "")
            self.list.addItem(item)
        layout.addWidget(self.list)

        self._refresh_text()

    def _refresh_text(self) -> None:
        arrow = ARROW_UP if self._expanded else ARROW_DOWN
        self.toggle.setText(f"{self._label}: {len(self._items)}  {arrow}")

    def _toggle(self) -> None:
        self._expanded = not self._expanded
        self.list.setVisible(self._expanded)
        self._refresh_text()

        # Recompute the layouts *now* (invalidate alone is lazy), so the window
        # can shrink back to its content when a section collapses.
        section_layout = self.layout()
        if section_layout is not None:
            section_layout.invalidate()
            section_layout.activate()

        window = self.window()
        if window is not None:
            window_layout = window.layout()
            if window_layout is not None:
                window_layout.invalidate()
                window_layout.activate()
            window.resize(window.sizeHint())


class ImportResultDialog(QDialog):
    """Modal summary of a batch import."""

    def __init__(self, result: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("import_result_title"))
        self.setModal(True)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)

        header = QLabel(
            tr("import_result_header").format(
                name=result.get("file") or "", count=result.get("total", 0)
            )
        )
        header.setStyleSheet(HELP_TITLE_STYLE)
        layout.addWidget(header)

        layout.addWidget(_Section(tr("import_success"), result.get("success") or []))
        layout.addWidget(_Section(tr("import_live"), result.get("live") or []))
        layout.addWidget(_Section(tr("import_duplicate"), result.get("duplicate") or []))
        layout.addWidget(_Section(tr("import_error"), result.get("error") or []))

        # Absorb leftover height here so the rows keep their spacing when the
        # dialog is taller than its content.
        layout.addStretch(1)

        buttons = QDialogButtonBox()
        btn_close = buttons.addButton(tr("close"), QDialogButtonBox.ButtonRole.AcceptRole)
        btn_close.clicked.connect(self.accept)
        layout.addWidget(buttons)

        apply_pointer_cursors(self)

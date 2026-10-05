"""Sessions manager dialog (feedback.md #4).

Every session is its own database file, listed here as one row:

    [radio] [name] [status]

The action buttons on top apply to the radio-checked row:
``[New] [Select] [Edit/Save] [Remove] [Remove all]``.
"""

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.i18n import tr
from core.sessions import SESSION_NAME_MAX_LENGTH
from gui.cursor_utils import apply_pointer_cursors
from gui.theme import (
    MAIN_WINDOW_STYLE,
    PREVIEW_META_STYLE,
    SCROLLBAR_STYLE,
    SESSION_NAME_READONLY_STYLE,
)
from gui.widgets import make_radio_button

ACTION_BUTTON_WIDTH = 104
STATUS_WIDTH = 110


class SessionDialog(QDialog):
    # The user asked to start a fresh session.
    newRequested = pyqtSignal()
    # The user asked to switch to a session (after confirming).
    selectRequested = pyqtSignal(str)
    # The user asked to delete one session (after confirming).
    removeRequested = pyqtSignal(str)
    # The user asked to delete every session (after confirming).
    removeAllRequested = pyqtSignal()

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        self._group: QButtonGroup | None = None
        self._radio_ids: dict[QRadioButton, str] = {}
        self._name_inputs: dict[str, QLineEdit] = {}
        self._editing: str | None = None
        self._current_row: QWidget | None = None
        self.scroll: QScrollArea | None = None

        self.setWindowTitle(tr("sessions_title"))
        self.setModal(True)
        self.setMinimumSize(570, 400)
        # Pin the initial size: otherwise the dialog grows with its layout
        # sizeHint (i.e. with the number of rows) instead of scrolling.
        self.resize(570, 400)
        self.setStyleSheet(MAIN_WINDOW_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.btn_new = self._action_button(tr("session_new"), self._on_new)
        self.btn_select = self._action_button(tr("session_select"), self._on_select)
        self.btn_edit = self._action_button(tr("session_edit"), self._on_edit)
        self.btn_remove = self._action_button(tr("session_remove"), self._on_remove)
        self.btn_remove_all = self._action_button(
            tr("session_remove_all"), self._on_remove_all
        )
        for btn in (self.btn_new, self.btn_select, self.btn_edit, self.btn_remove,
                    self.btn_remove_all):
            actions.addWidget(btn)
        actions.addStretch()
        layout.addLayout(actions)

        self.empty_label = QLabel(tr("session_empty"))
        self.empty_label.setStyleSheet(PREVIEW_META_STYLE)
        layout.addWidget(self.empty_label)

        self.rows_host = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(6)
        self.rows_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(SCROLLBAR_STYLE)
        scroll.setWidget(self.rows_host)
        self.scroll = scroll
        layout.addWidget(scroll, 1)

        footer = QHBoxLayout()
        footer.addStretch()
        self.btn_close = QPushButton(tr("close"))
        self.btn_close.setAutoDefault(False)
        self.btn_close.setFixedWidth(ACTION_BUTTON_WIDTH)
        self.btn_close.clicked.connect(self.accept)
        footer.addWidget(self.btn_close)
        layout.addLayout(footer)

        apply_pointer_cursors(self)
        self.reload()

    def _action_button(self, text: str, slot) -> QPushButton:
        btn = QPushButton(text)
        btn.setAutoDefault(False)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setFixedWidth(ACTION_BUTTON_WIDTH)
        btn.clicked.connect(slot)
        return btn

    # ------------------------------------------------------------------
    # LIST
    # ------------------------------------------------------------------

    def reload(self):
        while self.rows_layout.count() > 1:
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._radio_ids = {}
        self._name_inputs = {}
        self._editing = None
        self._current_row = None
        self.btn_edit.setText(tr("session_edit"))

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        sessions = self.engine.list_sessions()
        current_id = self.engine.session_id
        for index, session in enumerate(sessions):
            self.rows_layout.insertWidget(index, self._make_row(session, current_id))
        self.empty_label.setVisible(not sessions)
        self._sync_buttons()
        # Bring the in-use session into view once the layout has settled.
        QTimer.singleShot(0, self._scroll_to_current)

    def _scroll_to_current(self):
        if self.scroll is not None and self._current_row is not None:
            self.scroll.ensureWidgetVisible(self._current_row)

    def _make_row(self, session, current_id: str) -> QWidget:
        row = QWidget()
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        radio = make_radio_button("")
        radio.setChecked(session.id == current_id)
        self._group.addButton(radio)
        self._radio_ids[radio] = session.id
        radio.toggled.connect(
            lambda checked, sid=session.id: checked and self._on_radio(sid)
        )

        name_input = QLineEdit(session.name)
        name_input.setReadOnly(True)
        name_input.setFixedHeight(28)
        name_input.setMaxLength(SESSION_NAME_MAX_LENGTH)
        name_input.setStyleSheet(SESSION_NAME_READONLY_STYLE)
        self._name_inputs[session.id] = name_input

        status = QLabel(tr("session_status_in_use") if session.id == current_id else "")
        status.setStyleSheet(PREVIEW_META_STYLE)
        status.setFixedWidth(STATUS_WIDTH)

        def _pick(_event, r=radio):
            r.setChecked(True)

        row.mousePressEvent = _pick
        name_input.mousePressEvent = _pick
        status.mousePressEvent = _pick

        layout.addWidget(radio)
        layout.addWidget(name_input, 1)
        layout.addWidget(status)
        if session.id == current_id:
            self._current_row = row
        return row

    # ------------------------------------------------------------------
    # SELECTION / EDITS
    # ------------------------------------------------------------------

    def _selected_id(self) -> str | None:
        if self._group is None:
            return None
        radio = self._group.checkedButton()
        return self._radio_ids.get(radio) if radio is not None else None

    def _sync_buttons(self):
        has_selection = self._selected_id() is not None
        self.btn_select.setEnabled(has_selection)
        self.btn_edit.setEnabled(has_selection)
        self.btn_remove.setEnabled(has_selection)

    def _on_radio(self, session_id: str):
        if self._editing and self._editing != session_id:
            self._commit_edit()
        self._sync_buttons()

    def _on_edit(self):
        session_id = self._selected_id()
        if session_id is None:
            return
        if self._editing == session_id:
            self._commit_edit()
            return
        if self._editing:
            self._commit_edit()

        name_input = self._name_inputs.get(session_id)
        if name_input is None:
            return
        self._editing = session_id
        name_input.setReadOnly(False)
        name_input.setStyleSheet("")
        name_input.setFocus()
        name_input.selectAll()
        self.btn_edit.setText(tr("session_save"))

    def _commit_edit(self):
        session_id = self._editing
        self._editing = None
        self.btn_edit.setText(tr("session_edit"))
        if session_id is None:
            return
        name_input = self._name_inputs.get(session_id)
        if name_input is None:
            return
        name_input.setReadOnly(True)
        name_input.setStyleSheet(SESSION_NAME_READONLY_STYLE)
        self.engine.rename_session(session_id, name_input.text())
        # Reflect what was actually stored (empty input keeps the old name).
        info = self.engine.session_store.get(session_id)
        if info is not None:
            name_input.setText(info.name)

    def done(self, result):
        # Closing still commits a rename in progress.
        if self._editing:
            self._commit_edit()
        super().done(result)

    # ------------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------------

    def _on_new(self):
        self.newRequested.emit()
        self.accept()

    def _on_select(self):
        session_id = self._selected_id()
        if session_id is None or session_id == self.engine.session_id:
            self.accept()
            return
        if self._confirm(tr("session_select_confirm_title"), tr("session_select_confirm_text")):
            self.selectRequested.emit(session_id)
            self.accept()

    def _on_remove(self):
        session_id = self._selected_id()
        if session_id is None:
            return
        info = self.engine.session_store.get(session_id)
        if not self._confirm(
            tr("session_remove_confirm_title"),
            tr("session_remove_confirm_text").format(name=info.name if info else session_id),
        ):
            return
        self.removeRequested.emit(session_id)
        self.accept()

    def _on_remove_all(self):
        if not self._confirm(
            tr("session_remove_all_confirm_title"),
            tr("session_remove_all_confirm_text"),
        ):
            return
        self.removeAllRequested.emit()
        self.accept()

    def _confirm(self, title: str, text: str) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.setIcon(QMessageBox.Icon.Warning)
        btn_yes = box.addButton(tr("yes"), QMessageBox.ButtonRole.YesRole)
        btn_no = box.addButton(tr("no"), QMessageBox.ButtonRole.NoRole)
        box.setDefaultButton(btn_no)
        box.exec()
        return box.clickedButton() is btn_yes

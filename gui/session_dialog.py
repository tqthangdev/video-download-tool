"""Session manager dialog (feedback.md #2, #3).

Lists the saved sessions. Each row is:

    [name - Edit - Remove - Restore]

The name is a read-only text box until Edit turns it editable; Remove deletes
the session (its jobs stay in the database, only unlinked); Restore puts the
session's jobs back into the queue.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.i18n import tr
from gui.cursor_utils import apply_pointer_cursors
from gui.theme import MAIN_WINDOW_STYLE, PREVIEW_META_STYLE

ROW_BUTTON_WIDTH = 90


class SessionDialog(QDialog):
    # A saved session should be restored into the queue.
    restoreRequested = pyqtSignal(int)
    # The user asked to snapshot the current queue as a session.
    saveRequested = pyqtSignal()
    # The user asked to start a fresh session.
    newRequested = pyqtSignal()

    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self.engine = engine
        # Commit callback of the row currently being renamed (only one at a time).
        self._active_commit = None

        self.setWindowTitle(tr("sessions_title"))
        self.setModal(True)
        self.setMinimumSize(560, 380)
        self.setStyleSheet(MAIN_WINDOW_STYLE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self.empty_label = QLabel(tr("session_empty"))
        self.empty_label.setStyleSheet(PREVIEW_META_STYLE)
        self.empty_label.setWordWrap(True)

        self.rows_host = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_host)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(6)
        self.rows_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.rows_host)

        layout.addWidget(self.empty_label)
        layout.addWidget(scroll, 1)

        footer = QHBoxLayout()
        footer.setSpacing(6)
        self.btn_new = QPushButton(tr("session_new"))
        self.btn_new.setAutoDefault(False)
        self.btn_new.clicked.connect(self._on_new)
        footer.addWidget(self.btn_new)
        self.btn_save_current = QPushButton(tr("session_save_current"))
        self.btn_save_current.setAutoDefault(False)
        self.btn_save_current.clicked.connect(self._on_save_current)
        footer.addWidget(self.btn_save_current)
        footer.addStretch()
        self.btn_close = QPushButton(tr("close"))
        self.btn_close.setAutoDefault(False)
        self.btn_close.setFixedWidth(ROW_BUTTON_WIDTH + 12)
        self.btn_close.clicked.connect(self.accept)
        footer.addWidget(self.btn_close)
        layout.addLayout(footer)

        apply_pointer_cursors(self)
        self.reload()

    # ------------------------------------------------------------------
    # LIST
    # ------------------------------------------------------------------

    def reload(self):
        self._commit_active_edit()
        while self.rows_layout.count() > 1:
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        sessions = self.engine.sessions()
        for index, session in enumerate(sessions):
            self.rows_layout.insertWidget(index, self._make_row(session))

        self.empty_label.setVisible(not sessions)

    def _make_row(self, session) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        name_input = QLineEdit(session.name)
        name_input.setReadOnly(True)
        name_input.setFixedHeight(28)

        btn_edit = QPushButton(tr("session_edit"))
        btn_edit.setAutoDefault(False)
        # Keep focus on the name field while this button is clicked, so the
        # click commits the rename instead of first stealing focus.
        btn_edit.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn_edit.setFixedWidth(ROW_BUTTON_WIDTH)

        btn_remove = QPushButton(tr("session_remove"))
        btn_remove.setAutoDefault(False)
        btn_remove.setFixedWidth(ROW_BUTTON_WIDTH)

        btn_restore = QPushButton(tr("session_restore"))
        btn_restore.setAutoDefault(False)
        btn_restore.setFixedWidth(ROW_BUTTON_WIDTH)

        editing = {"on": False}

        def set_editing(on: bool):
            if on:
                # Only one row is edited at a time: commit the other one first.
                previous = self._active_commit
                if previous is not None and previous is not commit_rename:
                    previous()
            editing["on"] = on
            name_input.setReadOnly(not on)
            btn_edit.setText(tr("session_save") if on else tr("session_edit"))
            if on:
                self._active_commit = commit_rename
                name_input.setFocus()
                name_input.selectAll()
            elif self._active_commit is commit_rename:
                self._active_commit = None

        def commit_rename():
            if not editing["on"]:
                return
            new_name = name_input.text().strip()
            set_editing(False)
            if new_name and new_name != session.name:
                session.name = new_name
                self.engine.rename_session(session.id, new_name)
            else:
                name_input.setText(session.name)

        def on_edit():
            if editing["on"]:
                commit_rename()
            else:
                set_editing(True)

        def on_remove():
            if self._confirm_remove(session):
                self.engine.delete_session(session.id)
                self.reload()

        def on_restore():
            self.restoreRequested.emit(session.id)
            self.accept()

        name_input.returnPressed.connect(commit_rename)
        btn_edit.clicked.connect(on_edit)
        btn_remove.clicked.connect(on_remove)
        btn_restore.clicked.connect(on_restore)

        layout.addWidget(name_input, 1)
        layout.addWidget(btn_edit)
        layout.addWidget(btn_remove)
        layout.addWidget(btn_restore)
        return row

    def _commit_active_edit(self):
        commit = self._active_commit
        self._active_commit = None
        if commit is not None:
            commit()

    def done(self, result):
        # Closing (Close / Restore / Esc) still saves the rename in progress.
        self._commit_active_edit()
        super().done(result)

    def _confirm_remove(self, session) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle(tr("session_remove_confirm_title"))
        box.setText(tr("session_remove_confirm_text").format(name=session.name))
        box.setIcon(QMessageBox.Icon.Warning)
        btn_yes = box.addButton(tr("yes"), QMessageBox.ButtonRole.YesRole)
        btn_no = box.addButton(tr("no"), QMessageBox.ButtonRole.NoRole)
        box.setDefaultButton(btn_no)
        box.exec()
        return box.clickedButton() is btn_yes

    def _on_save_current(self):
        self.saveRequested.emit()
        self.reload()

    def _on_new(self):
        self.newRequested.emit()
        self.reload()

"""
gui/login_dialog.py

Shared login dialog for every manga site registered in AuthManager.
Assumes the app uses PyQt6 (queue_delegate.py in this project suggests so).
If you use PySide6 instead, just switch `from PyQt6` -> `from PySide6`.
"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QComboBox, QLineEdit,
    QDialogButtonBox, QLabel, QMessageBox
)

from core.auth import auth_manager, AuthError
from core.i18n import tr


class LoginDialog(QDialog):
    def __init__(self, parent=None, default_site: str | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("login_title"))
        self.setMinimumWidth(320)

        self.site_combo = QComboBox()
        self.site_combo.addItems(auth_manager.list_sites())
        if default_site and default_site in auth_manager.list_sites():
            self.site_combo.setCurrentText(default_site)

        self.username_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)

        form = QFormLayout()
        form.addRow(tr("login_site"), self.site_combo)
        form.addRow(tr("login_username"), self.username_edit)
        form.addRow(tr("login_password"), self.password_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_login)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.status_label)
        layout.addWidget(buttons)

    def _on_login(self) -> None:
        site_id = self.site_combo.currentText()
        username = self.username_edit.text().strip()
        password = self.password_edit.text()

        if not username or not password:
            self.status_label.setText(tr("login_required_fields"))
            return

        try:
            auth_manager.login(site_id, username, password, remember=True)
        except AuthError as e:
            QMessageBox.warning(self, tr("login_failed_title"), str(e))
            return

        self.accept()  # close the dialog and report success to the caller


def prompt_login(parent=None, default_site: str | None = None) -> bool:
    """
    Quick helper to call from main_window.py:

        if not auth_manager.is_logged_in("site_a"):
            if not prompt_login(self, default_site="site_a"):
                return  # user pressed Cancel

    Returns True on successful login, False if the user cancels.
    """
    dialog = LoginDialog(parent, default_site=default_site)
    return dialog.exec() == QDialog.DialogCode.Accepted
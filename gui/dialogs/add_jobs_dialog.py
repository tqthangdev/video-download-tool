"""
gui/dialogs/add_jobs_dialog.py

Modal shown while the app imports a batch of links from a file and adds each
one to the download queue (crawling each link to fill in its details first).

The import can be stopped: [Cancel] (or closing the dialog) asks for
confirmation first, then `cancelled` turns True and the owner stops handing out
the links that are left.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from core.i18n import tr


class AddJobsDialog(QDialog):
    """Progress dialog for a batch import, with a confirmed cancel."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle(tr("adding_jobs_title"))
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint
        )

        # Read by the owner: once True it stops importing the remaining links.
        self.cancelled = False
        self._finished = False

        self.setFixedSize(360, 150)

        self.label = QLabel(tr("adding_jobs_text").format(current=0, total=0))
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedHeight(8)
        self.progress.setTextVisible(False)

        self.btn_cancel = QPushButton(tr("cancel"))
        self.btn_cancel.clicked.connect(self._request_cancel)

        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(self.btn_cancel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addWidget(self.label)
        layout.addWidget(self.progress)
        layout.addLayout(button_row)

    def set_progress(self, current, total):
        if current <= 0:
            # Nothing has finished yet — every link is still being extracted.
            # An indeterminate range keeps the bar animated so the dialog does
            # not look frozen while the first extraction is running.
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, max(total, 1))
            self.progress.setValue(current)
        self.label.setText(
            tr("adding_jobs_text").format(current=current, total=total)
        )

    # ------------------------------------------------------------------
    # CANCEL
    # ------------------------------------------------------------------

    def _confirm_cancel(self) -> bool:
        """Ask before dropping the links that have not been imported yet."""
        box = QMessageBox(self)
        box.setWindowTitle(tr("import_cancel_title"))
        box.setText(tr("import_cancel_text"))
        box.setIcon(QMessageBox.Icon.Warning)
        btn_yes = box.addButton(tr("yes"), QMessageBox.ButtonRole.YesRole)
        btn_no = box.addButton(tr("no"), QMessageBox.ButtonRole.NoRole)
        box.setDefaultButton(btn_no)
        box.exec()
        return box.clickedButton() is btn_yes

    def _request_cancel(self):
        if self._confirm_cancel():
            self.cancelled = True
            self.close()

    def finish(self):
        """Called by the owner when the import is over: close without asking."""
        self._finished = True
        self.close()

    def closeEvent(self, event):
        if self._finished or self.cancelled:
            event.accept()
            return
        if self._confirm_cancel():
            self.cancelled = True
            event.accept()
        else:
            event.ignore()

    def reject(self):
        # ESC goes through the same confirmation as [Cancel].
        if self._finished or self.cancelled:
            super().reject()
            return
        if self._confirm_cancel():
            self.cancelled = True
            super().reject()

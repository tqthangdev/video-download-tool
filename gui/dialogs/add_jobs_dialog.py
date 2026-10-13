"""
gui/add_jobs_dialog.py

Modal shown while the app imports a batch of links from a file and adds each
one to the download queue (crawling each link to fill in its details first).
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QLabel, QProgressBar, QVBoxLayout

from core.i18n import tr


class AddJobsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle(tr("adding_jobs_title"))
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        # Disable minimize, maximize, and close buttons
        self.setWindowFlags(Qt.WindowType.Dialog)

        self.setFixedSize(320, 110)

        self.label = QLabel(tr("adding_jobs_text").format(current=0, total=0))
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        layout.addWidget(self.label)
        layout.addWidget(self.progress)

    def set_progress(self, current, total):
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(current)
        self.label.setText(
            tr("adding_jobs_text").format(current=current, total=total)
        )

    def closeEvent(self, event):
        # Prevent the user from closing while jobs are being added
        event.ignore()

    def reject(self):
        # Prevent ESC from closing
        pass
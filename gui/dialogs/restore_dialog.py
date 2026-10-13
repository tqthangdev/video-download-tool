from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QDialog,
    QLabel,
    QProgressBar,
    QVBoxLayout,
)


class RestoreDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Please wait")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        # Disable minimize, maximize, and close buttons
        self.setWindowFlags(Qt.WindowType.Dialog)

        self.setFixedSize(320, 110)

        self.label = QLabel("Restoring...")
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
        self.progress.setRange(0, total)
        self.progress.setValue(current)

        self.label.setText(
            f"Restoring... {current}/{total}"
        )

    def closeEvent(self, event):
        # Prevent the user from closing
        event.ignore()

    def reject(self):
        # Prevent ESC from closing
        pass
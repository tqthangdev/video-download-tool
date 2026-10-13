from pathlib import Path

from PyQt6.QtGui import QIntValidator
from PyQt6.QtWidgets import (
    QGroupBox,
    QLabel,
    QLineEdit,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtCore import Qt, QSettings

from core.i18n import tr
from core.utils import CONFIG
from gui.panels.video_preview import VideoPreview
from gui.common.widgets import make_checkbox

# Shared width for the small buttons on the right of each input row.
SIDE_BUTTON_WIDTH = 90


class LeftPanel(QWidget):
    """Left panel: source inputs, options and the preview."""

    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)

        self.settings = settings
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 0, 6, 6)
        layout.setSpacing(6)

        # ================= SOURCE (URL + output folder) =================
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(tr("url_placeholder"))
        self.url_input.setReadOnly(True)
        self.url_input.setFixedHeight(29)

        self.btn_paste = QPushButton(tr("paste"))
        self.btn_paste.setFixedWidth(SIDE_BUTTON_WIDTH)

        url_row = QWidget()
        url_layout = QHBoxLayout(url_row)
        url_layout.setContentsMargins(0, 0, 0, 0)
        url_layout.setSpacing(6)
        url_layout.addWidget(self.url_input, 1)
        url_layout.addWidget(self.btn_paste)

        self.path_input = QLineEdit()
        default_path = CONFIG.get("download_path") or str(Path.home() / "Downloads")
        saved_path = self.settings.value("save_path", "", type=str)

        # The saved path may come from another machine or a disconnected drive
        # -> fall back to the configured/default folder.
        if not saved_path or not Path(saved_path).is_absolute() or not Path(saved_path).exists():
            saved_path = default_path

        self.path_input.setPlaceholderText(tr("path_placeholder"))
        self.path_input.setText(saved_path)
        self.path_input.editingFinished.connect(self._save_path)

        self.btn_folder = QPushButton(tr("folder"))
        self.btn_folder.setFixedWidth(SIDE_BUTTON_WIDTH)

        path_row = QWidget()
        path_layout = QHBoxLayout(path_row)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(6)
        path_layout.addWidget(self.path_input, 1)
        path_layout.addWidget(self.btn_folder)

        self.btn_add = QPushButton(tr("add_queue"))
        self.btn_add.setDisabled(True)

        # ================= OPTIONS =================
        self.auto_queue_cb = make_checkbox(tr("auto_queue"))
        self.auto_queue_cb.setChecked(
            self.settings.value("auto_queue", False, type=bool)
        )
        self.auto_queue_cb.toggled.connect(self.on_auto_queue_toggled)

        self.auto_mp3_cb = make_checkbox(tr("auto_mp3"))
        self.auto_mp3_cb.setChecked(
            self.settings.value("auto_mp3", False, type=bool)
        )
        self.auto_mp3_cb.toggled.connect(self.on_auto_mp3_toggled)

        self.shutdown_cb = make_checkbox(tr("shutdown_after_done"))
        self.shutdown_cb.setChecked(
            self.settings.value("shutdown_after_done", False, type=bool)
        )
        self.shutdown_cb.toggled.connect(self.on_shutdown_toggled)

        saved_delay = self.settings.value("shutdown_delay", 10, type=int)
        self.shutdown_delay = QLineEdit()
        self.shutdown_delay.setValidator(QIntValidator(1, 600, self))
        self.shutdown_delay.setText(str(saved_delay if isinstance(saved_delay, int) else 10))
        self.shutdown_delay.setFixedSize(38, 22)
        self.shutdown_delay.setObjectName("compact_input")
        self.shutdown_delay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.shutdown_delay.setToolTip(tr("shutdown_delay_hint"))
        self.shutdown_delay.editingFinished.connect(self._save_shutdown_delay)
        self.shutdown_delay.setEnabled(self.shutdown_cb.isChecked())

        self.shutdown_delay_unit = QLabel(tr("shutdown_seconds"))
        self.shutdown_delay_unit.setToolTip(tr("shutdown_delay_hint"))

        shutdown_row = QWidget()
        shutdown_layout = QHBoxLayout(shutdown_row)
        shutdown_layout.setContentsMargins(0, 0, 0, 0)
        shutdown_layout.setSpacing(6)
        shutdown_layout.addWidget(self.shutdown_cb)
        shutdown_layout.addWidget(self.shutdown_delay)
        shutdown_layout.addWidget(self.shutdown_delay_unit)
        shutdown_layout.addStretch()

        self._session_name = ""
        self.session_label = QLabel("")
        self.session_label.setObjectName("meta_label")

        # ================= VIDEO PREVIEW =================
        self.preview = VideoPreview(CONFIG)

        # ================= ASSEMBLE =================
        layout.addWidget(self._build_source_group(url_row, path_row), 0)
        layout.addWidget(self._build_options_group(shutdown_row), 0)
        layout.addWidget(self._build_preview_group(), 1)

        # events that only affect this panel's own widgets
        self.btn_folder.clicked.connect(self.pick_folder)
        self.url_input.textChanged.connect(lambda _=None: self._update_add_button())
        self.preview.formatChanged.connect(lambda _=None: self._update_add_button())
        self._update_add_button()

    # =========================
    # GROUP BOXES
    # =========================
    def _build_source_group(self, url_row: QWidget, path_row: QWidget) -> QGroupBox:
        self.source_group = QGroupBox(tr("group_source"))
        group_layout = QVBoxLayout(self.source_group)
        group_layout.addWidget(url_row)
        group_layout.addSpacing(6)
        group_layout.addWidget(path_row)
        group_layout.addSpacing(6)
        group_layout.addWidget(self.btn_add)
        return self.source_group

    def _build_options_group(self, shutdown_row: QWidget) -> QGroupBox:
        self.options_group = QGroupBox(tr("group_options"))
        group_layout = QVBoxLayout(self.options_group)
        group_layout.addWidget(self.auto_queue_cb, 0, Qt.AlignmentFlag.AlignLeft)
        group_layout.addWidget(self.auto_mp3_cb, 0, Qt.AlignmentFlag.AlignLeft)
        group_layout.addWidget(shutdown_row, 0)
        group_layout.addWidget(self.session_label, 0)
        return self.options_group

    def _build_preview_group(self) -> QGroupBox:
        self.preview_group = QGroupBox(tr("group_preview"))
        group_layout = QVBoxLayout(self.preview_group)
        group_layout.addWidget(self.preview)
        return self.preview_group

    # =========================
    # SAVE THE SELECTED PATH (for the next run)
    # =========================
    def _save_path(self):
        path = self.path_input.text().strip()
        if path:
            self.settings.setValue("save_path", path)

    def on_auto_queue_toggled(self, checked):
        self.settings.setValue("auto_queue", checked)

    def on_auto_mp3_toggled(self, checked):
        self.settings.setValue("auto_mp3", checked)

    def on_shutdown_toggled(self, checked):
        self.settings.setValue("shutdown_after_done", checked)
        self.shutdown_delay.setEnabled(checked)

    def _save_shutdown_delay(self):
        """Clamp + persist the countdown value typed in the delay text box."""
        try:
            value = max(1, min(int(self.shutdown_delay.text().strip() or "60"), 3600))
        except ValueError:
            value = 60
        self.shutdown_delay.setText(str(value))
        self.settings.setValue("shutdown_delay", value)

    @property
    def shutdown_delay_seconds(self) -> int:
        """Countdown (seconds) currently shown next to the shutdown checkbox."""
        try:
            return max(1, min(int(self.shutdown_delay.text().strip() or "60"), 3600))
        except ValueError:
            return 60

    def set_session_name(self, name: str):
        """Show which session the queue currently belongs to."""
        self._session_name = name or ""
        self._refresh_session_label()

    def _refresh_session_label(self):
        self.session_label.setText(
            tr("session_current").format(name=self._session_name)
            if self._session_name
            else ""
        )

    # =========================
    # UPDATE TEXT WHEN THE LANGUAGE CHANGES
    # =========================
    def retranslate(self):
        self.source_group.setTitle(tr("group_source"))
        self.options_group.setTitle(tr("group_options"))
        self.preview_group.setTitle(tr("group_preview"))
        self.url_input.setPlaceholderText(tr("url_placeholder"))
        self.path_input.setPlaceholderText(tr("path_placeholder"))
        self.btn_paste.setText(tr("paste"))
        self.btn_folder.setText(tr("folder"))
        self.btn_add.setText(tr("add_queue"))
        self.auto_queue_cb.setText(tr("auto_queue"))
        self.auto_mp3_cb.setText(tr("auto_mp3"))
        self._refresh_session_label()
        self.shutdown_cb.setText(tr("shutdown_after_done"))
        self.shutdown_delay.setToolTip(tr("shutdown_delay_hint"))
        self.shutdown_delay_unit.setText(tr("shutdown_seconds"))
        self.shutdown_delay_unit.setToolTip(tr("shutdown_delay_hint"))
        self.preview.retranslate()

    # =========================
    # FOLDER PICKER
    # =========================
    def pick_folder(self):
        from PyQt6.QtWidgets import QFileDialog

        folder = QFileDialog.getExistingDirectory(self, tr("pick_folder_title"))
        if folder:
            self.path_input.setText(folder)
            self._save_path()

    # =========================
    # UPDATE ADD-QUEUE BUTTON STATE
    # =========================
    def _update_add_button(self):
        self.btn_add.setEnabled(
            bool(self.url_input.text().strip())
            and self.preview.selected_choice() is not None
        )

    # =========================
    # LOADING STATE
    # =========================
    def on_loading(self, show: bool):
        self.preview.set_loading(show)
        if show:
            self.btn_add.setDisabled(True)

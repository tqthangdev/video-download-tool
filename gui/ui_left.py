from pathlib import Path

from PyQt6.QtGui import QIntValidator
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QDialog,
    QFormLayout,
    QDialogButtonBox,
    QToolButton,
    QComboBox,
    QStackedWidget,
    QFrame,
)
from PyQt6.QtCore import Qt, QSettings

from core.utils import CONFIG, save_config
from core.i18n import tr, set_lang, get_lang
from gui.cursor_utils import apply_pointer_cursors
from gui.theme import (
    HELP_TITLE_STYLE,
    CONFIG_DIALOG_STYLE,
    HELP_BUTTON_STYLE,
    COMPACT_INPUT_STYLE,
)
from gui.video_preview import VideoPreview
from gui.widgets import make_checkbox, make_radio_button

# Shared width for the small buttons on the right of each input row
# (Paste / Folder / Settings / About). Keeping them equal keeps the rows aligned.
SIDE_BUTTON_WIDTH = 90

# Options offered by the Settings dropdowns.
WORKER_OPTIONS = tuple(range(1, 11))
VIDEO_QUALITY_OPTIONS = ("360p", "480p", "720p", "1080p", "1440p", "2160p")
AUDIO_BITRATE_OPTIONS = ("128k", "192k", "320k")


def _combo_options(key: str):
    """Choices for a settings key, or None when the field stays a text box."""
    if key == "max_workers":
        return [(str(value), value) for value in WORKER_OPTIONS]
    if key == "default_video_quality":
        return [(value, value) for value in VIDEO_QUALITY_OPTIONS]
    if key == "default_audio_bitrate":
        return [(value, value) for value in AUDIO_BITRATE_OPTIONS]
    if key == "prefer":
        return [(tr("prefer_video"), "video"), (tr("prefer_audio"), "audio")]
    return None


class LeftPanel(QWidget):
    """
    Left side of the main window:
    - Mode selector (manual / auto) + input row (URL/paste or file/choose)
    - Save path input + folder picker
    - "Shutdown when done" / "Automatically add to queue" checkboxes
    - Add Queue button
    - Video preview (metadata + format radio buttons)
    """

    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)

        self.settings = settings
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # ================= MODE AREA =================
        self.mode_area = QWidget()
        mode_layout = QHBoxLayout(self.mode_area)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(6)

        mode_label = QLabel(tr("mode"))
        self.rb_manual = make_radio_button(tr("mode_manual"))
        self.rb_auto = make_radio_button(tr("mode_auto"))
        self.rb_manual.setChecked(True)

        mode_layout.addWidget(mode_label)
        mode_layout.addWidget(self.rb_manual)
        mode_layout.addWidget(self.rb_auto)
        mode_layout.addStretch()

        self.rb_manual.toggled.connect(self._on_mode_changed)
        self.rb_auto.toggled.connect(self._on_mode_changed)

        # ================= INPUT STACK =================
        self.input_stack = QStackedWidget()
        self.input_stack.setFrameShape(QFrame.Shape.NoFrame)
        self.input_stack.setContentsMargins(0, 0, 0, 0)

        # --- manual page ---
        manual_page = QWidget()
        manual_layout = QHBoxLayout(manual_page)
        manual_layout.setContentsMargins(0, 0, 0, 0)
        manual_layout.setSpacing(6)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(tr("url_placeholder"))
        self.url_input.setReadOnly(True)
        self.url_input.setFixedHeight(29)

        self.btn_paste = QPushButton(tr("paste"))
        self.btn_paste.setFixedWidth(SIDE_BUTTON_WIDTH)

        manual_layout.addWidget(self.url_input, 1)
        manual_layout.addWidget(self.btn_paste)

        # --- auto page ---
        auto_page = QWidget()
        auto_layout = QHBoxLayout(auto_page)
        auto_layout.setContentsMargins(0, 0, 0, 0)
        auto_layout.setSpacing(6)

        self.file_input = QLineEdit()
        self.file_input.setPlaceholderText(tr("file_placeholder"))
        self.file_input.setReadOnly(True)
        self.file_input.setFixedHeight(29)
        self.file_input.mousePressEvent = self._pick_file_for_event

        self.btn_pick_file = QPushButton(tr("file_pick"))
        self.btn_pick_file.setFixedWidth(SIDE_BUTTON_WIDTH)

        auto_layout.addWidget(self.file_input, 1)
        auto_layout.addWidget(self.btn_pick_file)

        self.input_stack.addWidget(manual_page)  # index 0 = manual
        self.input_stack.addWidget(auto_page)    # index 1 = auto

        # ================= CHECKBOX + SETTINGS =================
        settings_row = QWidget()
        settings_layout = QHBoxLayout(settings_row)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(6)

        checkbox_col = QVBoxLayout()
        checkbox_col.setContentsMargins(0, 0, 0, 0)
        checkbox_col.setSpacing(6)

        self.shutdown_cb = make_checkbox(tr("shutdown_after_done"))
        self.shutdown_cb.setChecked(
            self.settings.value("shutdown_after_done", False, type=bool)
        )
        self.shutdown_cb.toggled.connect(self.on_shutdown_toggled)

        saved_delay = self.settings.value("shutdown_delay", 60, type=int)
        self.shutdown_delay = QLineEdit()
        self.shutdown_delay.setValidator(QIntValidator(1, 3600, self))
        self.shutdown_delay.setText(str(saved_delay if isinstance(saved_delay, int) else 60))
        self.shutdown_delay.setFixedSize(38, 22)
        self.shutdown_delay.setStyleSheet(COMPACT_INPUT_STYLE)
        self.shutdown_delay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.shutdown_delay.setToolTip(tr("shutdown_delay_hint"))
        self.shutdown_delay.editingFinished.connect(self._save_shutdown_delay)
        self.shutdown_delay.setEnabled(self.shutdown_cb.isChecked())

        self.shutdown_delay_unit = QLabel(tr("shutdown_seconds"))
        self.shutdown_delay_unit.setToolTip(tr("shutdown_delay_hint"))

        shutdown_row = QWidget()
        shutdown_row_layout = QHBoxLayout(shutdown_row)
        shutdown_row_layout.setContentsMargins(0, 0, 0, 0)
        shutdown_row_layout.setSpacing(6)
        shutdown_row_layout.addWidget(self.shutdown_cb)
        shutdown_row_layout.addWidget(self.shutdown_delay)
        shutdown_row_layout.addWidget(self.shutdown_delay_unit)
        shutdown_row_layout.addStretch()

        self.auto_queue_cb = make_checkbox(tr("auto_queue"))
        self.auto_queue_cb.setChecked(
            self.settings.value("auto_queue", False, type=bool)
        )
        self.auto_queue_cb.toggled.connect(self.on_auto_queue_toggled)

        checkbox_col.addWidget(shutdown_row, 0, Qt.AlignmentFlag.AlignLeft)
        checkbox_col.addWidget(self.auto_queue_cb, 0, Qt.AlignmentFlag.AlignLeft)

        self.btn_settings = QPushButton(tr("settings"))
        self.btn_settings.setFixedWidth(SIDE_BUTTON_WIDTH)
        self.btn_settings.clicked.connect(self.open_settings)

        settings_layout.addLayout(checkbox_col, 1)
        settings_layout.addWidget(self.btn_settings)
        settings_layout.setAlignment(self.btn_settings, Qt.AlignmentFlag.AlignTop)

        # ================= PATH AREA =================
        path_area = QWidget()
        path_layout = QHBoxLayout(path_area)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(6)

        self.btn_folder = QPushButton(tr("folder"))
        self.btn_folder.setFixedWidth(SIDE_BUTTON_WIDTH)

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

        path_layout.addWidget(self.path_input, 1)
        path_layout.addWidget(self.btn_folder)

        # ================= ADD QUEUE / ABOUT BUTTONS =================
        self.btn_add = QPushButton(tr("add_queue"))
        self.btn_add.setDisabled(True)

        self.btn_about = QPushButton(tr("about"))
        self.btn_about.setFixedWidth(SIDE_BUTTON_WIDTH)

        add_row = QWidget()
        add_row_layout = QHBoxLayout(add_row)
        add_row_layout.setContentsMargins(0, 0, 0, 0)
        add_row_layout.setSpacing(6)
        add_row_layout.addWidget(self.btn_add, 1)
        add_row_layout.addWidget(self.btn_about)

        # ================= VIDEO PREVIEW =================
        self.preview = VideoPreview()

        # ================= ASSEMBLE =================
        layout.addWidget(self.mode_area, 0)
        layout.addWidget(self.input_stack, 0)
        layout.addWidget(path_area, 0)
        layout.addWidget(settings_row, 0)
        layout.addWidget(add_row, 0)
        layout.addWidget(self.preview, 1)

        # events that only affect this panel's own widgets
        self.btn_folder.clicked.connect(self.pick_folder)
        self.btn_pick_file.clicked.connect(self.pick_file)
        self.btn_about.clicked.connect(self.open_about)
        self.url_input.textChanged.connect(lambda _=None: self._update_add_button())
        self.file_input.textChanged.connect(lambda _=None: self._update_add_button())
        self.preview.formatChanged.connect(lambda _=None: self._update_add_button())
        self._on_mode_changed(self.rb_manual.isChecked())

    # =========================
    # SAVE THE SELECTED PATH (for the next run)
    # =========================
    def _save_path(self):
        path = self.path_input.text().strip()
        if path:
            self.settings.setValue("save_path", path)

    def on_auto_queue_toggled(self, checked):
        self.settings.setValue("auto_queue", checked)

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

    # =========================
    # UPDATE TEXT WHEN THE LANGUAGE CHANGES
    # =========================
    def retranslate(self):
        self.file_input.setPlaceholderText(tr("file_placeholder"))
        self.btn_pick_file.setText(tr("file_pick"))
        self.url_input.setPlaceholderText(tr("url_placeholder"))
        self.path_input.setPlaceholderText(tr("path_placeholder"))
        self.btn_paste.setText(tr("paste"))
        self.btn_folder.setText(tr("folder"))
        self.btn_settings.setText(tr("settings"))
        self.btn_add.setText(tr("add_queue"))
        self.btn_about.setText(tr("about"))
        self.auto_queue_cb.setText(tr("auto_queue"))
        self.shutdown_cb.setText(tr("shutdown_after_done"))
        self.shutdown_delay.setToolTip(tr("shutdown_delay_hint"))
        self.shutdown_delay_unit.setText(tr("shutdown_seconds"))
        self.shutdown_delay_unit.setToolTip(tr("shutdown_delay_hint"))
        self.rb_manual.setText(tr("mode_manual"))
        self.rb_auto.setText(tr("mode_auto"))
        self.preview.retranslate()

    def open_settings(self):
        _ConfigDialog(self).exec()

    def open_about(self):
        _AboutDialog(self).exec()

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
    # FILE PICKER (add jobs from file)
    # =========================
    def _pick_file_for_event(self, event):
        self.pick_file()

    def pick_file(self):
        """Open a file dialog and validate the chosen file as a link list."""
        from PyQt6.QtWidgets import QFileDialog, QMessageBox
        from core.utils import parse_link_file

        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("file_pick_title"),
            "",
            f"{tr('all_files')} (*)",
        )
        if not path:
            return

        _urls, error_code, error_detail = parse_link_file(path)

        if error_code is not None:
            message = tr(f"import_error_{error_code}")
            if error_detail:
                message = f"{message}\n\n{error_detail}"
            QMessageBox.critical(self, tr("import_error_title"), message)
            return

        self.file_input.setText(path)
        self.settings.setValue("import_file", path)
        self._update_add_button()

    # =========================
    # MODE CHANGE (manual / auto)
    # =========================
    def _on_mode_changed(self, checked):
        manual = self.rb_manual.isChecked()
        self.input_stack.setCurrentIndex(0 if manual else 1)
        self._update_add_button()

    # =========================
    # UPDATE ADD-QUEUE BUTTON STATE
    # =========================
    def _update_add_button(self):
        if self.rb_auto.isChecked():
            self.btn_add.setEnabled(bool(self.file_input.text().strip()))
            return

        self.btn_add.setEnabled(
            bool(self.url_input.text().strip()) and self.preview.selected_choice() is not None
        )

    # =========================
    # LOADING STATE
    # =========================
    def on_loading(self, show: bool):
        self.preview.set_loading(show)
        if show:
            self.btn_add.setDisabled(True)


class _ConfigDialog(QDialog):
    """Modal to edit the values in config.json."""

    # (i18n label key, config key, i18n description key)
    FIELDS = [
        ("field_max_workers", "max_workers", "field_max_workers_desc"),
        ("field_download_path", "download_path", "field_download_path_desc"),
        ("field_video_quality", "default_video_quality", "field_video_quality_desc"),
        ("field_audio_bitrate", "default_audio_bitrate", "field_audio_bitrate_desc"),
        ("field_prefer", "prefer", "field_prefer_desc"),
        ("field_gemini_api", "gemini_api", "field_gemini_api_desc"),
    ]

    @staticmethod
    def _make_help_button(callback) -> QToolButton:
        btn = QToolButton()
        btn.setText("?")
        btn.setFixedSize(24, 24)
        btn.setAutoRaise(True)
        btn.setStyleSheet(HELP_BUTTON_STYLE)
        btn.clicked.connect(callback)
        return btn

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("settings_title"))
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setStyleSheet(CONFIG_DIALOG_STYLE)

        self._inputs = {}

        layout = QVBoxLayout(self)
        form = QFormLayout()

        # ===== LANGUAGE COMBOBOX =====
        self.cb_lang = QComboBox()
        self.cb_lang.addItem(tr("lang_vi"), "vi")
        self.cb_lang.addItem(tr("lang_en"), "en")
        idx = self.cb_lang.findData(get_lang())
        self.cb_lang.setCurrentIndex(idx if idx >= 0 else 0)

        lang_row = QWidget()
        lang_layout = QHBoxLayout(lang_row)
        lang_layout.setContentsMargins(0, 0, 0, 0)
        lang_layout.setSpacing(4)
        lang_layout.addWidget(self.cb_lang, 1)
        lang_spacer = QWidget()
        lang_spacer.setFixedWidth(24)
        lang_layout.addWidget(lang_spacer)

        form.addRow(tr("language_label"), lang_row)

        for label_key, key, desc_key in self.FIELDS:
            label = tr(label_key)
            desc = tr(desc_key)
            value = CONFIG.get(key, "")

            options = _combo_options(key)
            if options is None:
                # Free-form value (the download folder) stays a text box.
                widget = QLineEdit(str(value))
            else:
                widget = QComboBox()
                # Keep an unrecognised stored value selectable instead of
                # silently replacing it with the first option.
                if value not in [option_value for _, option_value in options]:
                    options = [(str(value), value), *options]
                for option_label, option_value in options:
                    widget.addItem(option_label, option_value)
                index = widget.findData(value)
                if index >= 0:
                    widget.setCurrentIndex(index)

            self._inputs[key] = widget

            btn_help = self._make_help_button(
                lambda _=False, t=label, d=desc: _HelpDialog(t, d, self).exec()
            )

            row = QWidget()
            row.setFixedHeight(26)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)
            row_layout.addWidget(widget, 1)
            row_layout.addWidget(btn_help)

            form.addRow(label, row)

        layout.addLayout(form)

        buttons = QDialogButtonBox()
        btn_apply = buttons.addButton(tr("apply"), QDialogButtonBox.ButtonRole.AcceptRole)
        btn_cancel = buttons.addButton(tr("cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        btn_apply.clicked.connect(self._on_apply)
        btn_cancel.clicked.connect(self.reject)
        layout.addWidget(buttons)

        apply_pointer_cursors(self)
        self.setFocus()

    def _on_apply(self):
        new_config = dict(CONFIG)
        for key, widget in self._inputs.items():
            if isinstance(widget, QComboBox):
                new_config[key] = widget.currentData()
            else:
                text = widget.text().strip()
                if text:
                    new_config[key] = text

        new_config["language"] = self.cb_lang.currentData()

        if save_config(new_config):
            CONFIG.clear()
            CONFIG.update(new_config)
            set_lang(new_config["language"])
            self.accept()
        else:
            from PyQt6.QtWidgets import QMessageBox

            QMessageBox.critical(self, tr("error"), tr("save_error"))


class _HelpDialog(QDialog):
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


class _AboutDialog(QDialog):
    """Modal showing basic information about the app."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("about_title"))
        self.setModal(True)
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)

        title_label = QLabel(tr("app_title"))
        title_label.setStyleSheet(HELP_TITLE_STYLE)
        title_label.setWordWrap(True)

        desc_label = QLabel(tr("about_desc"))
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

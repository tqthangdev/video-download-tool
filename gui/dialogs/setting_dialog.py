"""Settings dialog: edits the values stored in config.json."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.i18n import get_lang, set_lang, tr
from core.utils import CONFIG, save_config
from gui.cursor_utils import apply_pointer_cursors
from gui.dialogs.help_dialog import HelpDialog
from gui.theme import CONFIG_DIALOG_STYLE, LIST_STYLE
from gui.widgets import make_checkbox, make_combo, make_help_button

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
    return None


class SettingDialog(QDialog):
    """Modal to edit the values in config.json."""

    # (i18n label key, config key, i18n description key)
    FIELDS = [
        ("field_max_workers", "max_workers", "field_max_workers_desc"),
        ("field_download_path", "download_path", "field_download_path_desc"),
        ("field_video_quality", "default_video_quality", "field_video_quality_desc"),
        ("field_audio_bitrate", "default_audio_bitrate", "field_audio_bitrate_desc"),
    ]

    def __init__(self, parent=None, network=None):
        super().__init__(parent)
        self.setWindowTitle(tr("settings_title"))
        self.setModal(True)
        self.setMinimumWidth(520)
        self.setStyleSheet(CONFIG_DIALOG_STYLE)

        self.network = network
        self._inputs = {}

        layout = QVBoxLayout(self)
        form = QFormLayout()

        # ===== LANGUAGE COMBOBOX =====
        self.cb_lang = make_combo()
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
                widget = make_combo()
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

            btn_help = make_help_button(
                lambda _=False, t=label, d=desc: HelpDialog(t, d, self).exec()
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

        # ===== NETWORK (automatic fallback) =====
        self.network_cb = None
        if self.network is not None:
            layout.addWidget(QLabel(tr("network_label")))
            self.network_cb = make_checkbox(tr("network_fallback"))
            self.network_cb.setChecked(bool(CONFIG.get("network_enabled", True)))
            layout.addWidget(self.network_cb, 0, Qt.AlignmentFlag.AlignLeft)

            layout.addWidget(QLabel(tr("network_learned")))
            self.network_list = QListWidget()
            self.network_list.setStyleSheet(LIST_STYLE)
            self.network_list.setFixedHeight(72)
            self.network_list.setSelectionMode(
                QAbstractItemView.SelectionMode.NoSelection
            )
            layout.addWidget(self.network_list)

            self.btn_clear_network = QPushButton(tr("network_clear"))
            self.btn_clear_network.clicked.connect(self._clear_network)
            layout.addWidget(self.btn_clear_network, 0, Qt.AlignmentFlag.AlignLeft)
            self._refresh_network_list()

        buttons = QDialogButtonBox()
        btn_apply = buttons.addButton(tr("apply"), QDialogButtonBox.ButtonRole.AcceptRole)
        btn_cancel = buttons.addButton(tr("cancel"), QDialogButtonBox.ButtonRole.RejectRole)
        btn_apply.clicked.connect(self._on_apply)
        btn_cancel.clicked.connect(self.reject)
        layout.addWidget(buttons)

        apply_pointer_cursors(self)
        self.setFocus()

    def _refresh_network_list(self):
        self.network_list.clear()
        hosts = self.network.learned_hosts() if self.network else {}
        if not hosts:
            self.network_list.addItem(tr("network_empty"))
            return
        for host, route in sorted(hosts.items()):
            expires = (route.expires_at or "")[:10]
            self.network_list.addItem(
                f"{host}   {route.transport}/{route.strategy or '-'}   "
                f"{tr('network_expires').format(date=expires)}"
            )

    def _clear_network(self):
        if self.network is not None:
            self.network.clear_learned()
            self._refresh_network_list()

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
        if self.network_cb is not None:
            new_config["network_enabled"] = self.network_cb.isChecked()

        if save_config(new_config):
            CONFIG.clear()
            CONFIG.update(new_config)
            set_lang(new_config["language"])
            self.accept()
        else:
            QMessageBox.critical(self, tr("error"), tr("save_error"))

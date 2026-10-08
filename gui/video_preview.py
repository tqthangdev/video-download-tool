"""Video preview: thumbnail, metadata and the format picker (flow.md #12).

The selected object is always the full FormatChoice — the GUI never rebuilds a
format id from the label text (flow.md #13).

The picker is a Video/Audio switch plus a combo box listing that type's
formats (`MP4 — 720p — 1.05 GB`).
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QMovie
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.format_selector import (
    AUDIO,
    VIDEO,
    FormatChoice,
    select_default_format,
)
from core.i18n import tr
from core.utils import format_size, get_resource_path
from gui.theme import (
    PREVIEW_PANEL_STYLE,
    LIVE_BADGE_STYLE,
    MANGA_TITLE_STYLE,
    PREVIEW_COMBO_STYLE,
    PREVIEW_META_STYLE,
)
from gui.widgets import make_radio_button

THUMB_W = 160
THUMB_H = 90
LOADING_ICON_SIZE = 48


def format_duration(seconds) -> str:
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


class VideoPreview(QWidget):
    """Metadata + format picker for the currently previewed URL."""

    formatChanged = pyqtSignal(object)  # FormatChoice | None

    def __init__(self, config: dict | None = None, parent=None):
        super().__init__(parent)

        # The config decides which format is pre-selected per type (the
        # configured video quality / audio bitrate).
        self._config = config or {}
        self._choices: list[FormatChoice] = []
        self._index_by_key: dict[str, int] = {}
        self._selected: FormatChoice | None = None
        self._is_live = False
        self._updating = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addWidget(self._build_preview(), 1)
        layout.addWidget(self._build_loading(), 1)
        self.set_loading(False)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_preview(self) -> QWidget:
        self.preview_panel = QWidget()
        self.preview_panel.setObjectName("video_preview")
        self.preview_panel.setStyleSheet(PREVIEW_PANEL_STYLE)

        outer = QVBoxLayout(self.preview_panel)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(6)

        # ===== METADATA =====
        meta = QWidget()
        meta_layout = QVBoxLayout(meta)
        meta_layout.setContentsMargins(6, 6, 6, 6)
        meta_layout.setSpacing(4)

        line1 = QHBoxLayout()
        self.thumb = QLabel()
        self.thumb.setFixedSize(THUMB_W, THUMB_H)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.title_label = QLabel("")
        self.title_label.setStyleSheet(MANGA_TITLE_STYLE)
        self.title_label.setWordWrap(True)
        # Same height as the thumbnail so the two line up in the row.
        self.title_label.setFixedHeight(THUMB_H)
        self.title_label.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        line1.addWidget(self.thumb)
        line1.addWidget(self.title_label, 1)

        line2 = QHBoxLayout()
        self.live_label = QLabel(tr("live_badge"))
        self.live_label.setStyleSheet(LIVE_BADGE_STYLE)
        self.live_label.setVisible(False)
        self.uploader_label = QLabel("")
        self.uploader_label.setStyleSheet(PREVIEW_META_STYLE)
        self.duration_label = QLabel("")
        self.duration_label.setStyleSheet(PREVIEW_META_STYLE)
        line2.addWidget(self.live_label)
        line2.addWidget(self.uploader_label)
        line2.addStretch()
        line2.addWidget(self.duration_label)

        meta_layout.addLayout(line1)
        meta_layout.addLayout(line2)
        outer.addWidget(meta)

        # ===== FORMAT PICKER =====
        formats = QWidget()
        formats_layout = QVBoxLayout(formats)
        formats_layout.setContentsMargins(6, 6, 6, 6)
        formats_layout.setSpacing(6)

        # ===== TYPE (Video / Audio) =====
        type_row = QHBoxLayout()
        type_row.setContentsMargins(0, 0, 0, 0)
        type_row.setSpacing(10)

        self.type_label = QLabel(tr("formats_label"))
        self.type_label.setStyleSheet(PREVIEW_META_STYLE)
        self.rb_video = make_radio_button(tr("format_video"))
        self.rb_audio = make_radio_button(tr("format_audio"))
        self.rb_video.toggled.connect(self._on_type_toggled)
        self.rb_audio.toggled.connect(self._on_type_toggled)

        type_row.addWidget(self.type_label)
        type_row.addWidget(self.rb_video)
        type_row.addWidget(self.rb_audio)
        type_row.addStretch()

        # ===== FORMATS OF THE CHOSEN TYPE =====
        self.combo = QComboBox()
        self.combo.setPlaceholderText(tr("formats_empty"))
        self.combo.setCurrentIndex(-1)
        self.combo.setStyleSheet(PREVIEW_COMBO_STYLE)
        self.combo.currentIndexChanged.connect(self._on_combo_changed)

        self.empty_label = QLabel(tr("no_formats"))
        self.empty_label.setWordWrap(True)
        self.empty_label.setStyleSheet(PREVIEW_META_STYLE)
        self.empty_label.hide()

        formats_layout.addLayout(type_row)
        formats_layout.addWidget(self.combo)
        formats_layout.addWidget(self.empty_label)
        formats_layout.addStretch()
        outer.addWidget(formats)

        return self.preview_panel

    def _build_loading(self) -> QWidget:
        """Centered spinner shown while a URL is being extracted."""
        self.loading_panel = QWidget()

        outer = QVBoxLayout(self.loading_panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch()

        self.loading_icon = QLabel()
        self.loading_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.movie = QMovie(str(get_resource_path("assets/loading.gif")))
        self.movie.setScaledSize(QSize(LOADING_ICON_SIZE, LOADING_ICON_SIZE))
        self.loading_icon.setMovie(self.movie)

        self.loading_text = QLabel(tr("loading_preview"))
        self.loading_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_text.setStyleSheet(PREVIEW_META_STYLE)

        outer.addWidget(self.loading_icon)
        outer.addWidget(self.loading_text)
        outer.addStretch()

        return self.loading_panel

    # ------------------------------------------------------------------
    # LOADING STATE
    # ------------------------------------------------------------------

    def set_loading(self, on: bool):
        """Show/hide the loading spinner, replacing the preview content."""
        if on:
            self.clear()
            self.preview_panel.hide()
            self.loading_text.setText(tr("loading_preview"))
            self.loading_panel.show()
            self.movie.start()
        else:
            self.movie.stop()
            self.loading_panel.hide()
            self.preview_panel.show()

    # ------------------------------------------------------------------
    # POPULATION
    # ------------------------------------------------------------------

    def set_video(self, video_info, choices: list[FormatChoice], default=None, thumbnail=None):
        self.title_label.setText(video_info.title or "")

        self._is_live = bool(getattr(video_info, "is_live", False))
        self.live_label.setVisible(self._is_live)

        duration = format_duration(video_info.duration)
        self.duration_label.setText(
            f"{tr('duration_label')}: {duration}" if duration else ""
        )
        self.uploader_label.setText(
            f"{tr('uploader_label')}: {video_info.uploader}" if video_info.uploader else ""
        )
        self.set_thumbnail(thumbnail)

        self._choices = list(choices)
        self._selected = None

        self._updating = True
        try:
            self.rb_video.setEnabled(bool(self._choices_of(VIDEO)))
            self.rb_audio.setEnabled(bool(self._choices_of(AUDIO)))
        finally:
            self._updating = False

        self.combo.setVisible(bool(self._choices))
        self.empty_label.setVisible(not self._choices)

        if default is not None:
            target = default
        elif self._choices:
            target = self._default_of(self._choices[0].type)
        else:
            target = None
        if target is not None:
            self.select_choice(target)
        else:
            self._clear_combo()
            self.formatChanged.emit(None)

    def select_choice(self, choice: FormatChoice | None):
        if choice is None or choice not in self._choices:
            return

        self._updating = True
        try:
            if choice.type == AUDIO:
                self.rb_audio.setChecked(True)
            else:
                self.rb_video.setChecked(True)
            self._selected = None
            self._populate_combo(choice.type, choice)
        finally:
            self._updating = False

        self.formatChanged.emit(choice)

    def selected_choice(self) -> FormatChoice | None:
        return self._selected

    def is_live(self) -> bool:
        """True when the previewed URL is a stream that is broadcasting now."""
        return self._is_live

    def clear(self):
        self.title_label.clear()
        self.duration_label.clear()
        self.uploader_label.clear()
        self.live_label.setVisible(False)
        self._is_live = False
        self.thumb.clear()
        self._choices = []
        self._selected = None

        self._updating = True
        try:
            self.rb_video.setEnabled(False)
            self.rb_audio.setEnabled(False)
            self._clear_combo()
        finally:
            self._updating = False

        self.empty_label.hide()
        self.formatChanged.emit(None)

    def retranslate(self):
        self.type_label.setText(tr("formats_label"))
        self.rb_video.setText(tr("format_video"))
        self.rb_audio.setText(tr("format_audio"))
        self.empty_label.setText(tr("no_formats"))
        self.loading_text.setText(tr("loading_preview"))
        self.live_label.setText(tr("live_badge"))

    # ------------------------------------------------------------------
    # INTERNALS
    # ------------------------------------------------------------------

    @staticmethod
    def _key(choice: FormatChoice) -> str:
        return f"{choice.group}|{choice.label}|{choice.format_id}"

    @staticmethod
    def _label(choice: FormatChoice) -> str:
        size = format_size(choice.filesize)
        if size:
            return f"{choice.group} — {choice.label} — {size}"
        return f"{choice.group} — {choice.label}"

    def _choices_of(self, type_: str) -> list[FormatChoice]:
        return [c for c in self._choices if c.type == type_]

    def _default_of(self, type_: str) -> FormatChoice | None:
        """The format matching the configured default for this type."""
        candidates = self._choices_of(type_)
        if not candidates:
            return None
        return select_default_format(candidates, self._config) or candidates[0]

    def _clear_combo(self):
        self.combo.clear()
        self._index_by_key = {}

    def _populate_combo(self, type_: str, target: FormatChoice | None):
        self.combo.clear()
        self._index_by_key = {}
        for index, choice in enumerate(self._choices_of(type_)):
            self.combo.addItem(self._label(choice), choice)
            self._index_by_key[self._key(choice)] = index
        if target is not None:
            index = self._index_by_key.get(self._key(target), -1)
            if index >= 0:
                self.combo.setCurrentIndex(index)
                self._selected = target

    def _on_type_toggled(self, checked: bool):
        if not checked or self._updating:
            return
        type_ = VIDEO if self.sender() is self.rb_video else AUDIO
        candidates = self._choices_of(type_)
        if not candidates:
            return

        target = self._default_of(type_)
        self._updating = True
        try:
            self._selected = None
            self._populate_combo(type_, target)
        finally:
            self._updating = False

        self.formatChanged.emit(target)

    def _on_combo_changed(self, index: int):
        if self._updating or index < 0:
            return
        choice = self.combo.itemData(index)
        if choice is not None:
            self._selected = choice
            self.formatChanged.emit(choice)

    def set_thumbnail(self, data):
        """Set the thumbnail from raw image bytes (or None to clear)."""
        pixmap = pixmap_from_bytes(data)
        if pixmap is None:
            self.thumb.clear()
        else:
            self.thumb.setPixmap(pixmap)


def pixmap_from_bytes(data):
    """Scale raw image bytes into a preview pixmap, or None on failure."""
    if not data:
        return None
    from PyQt6.QtGui import QPixmap

    pixmap = QPixmap()
    if not pixmap.loadFromData(data):
        return None
    return pixmap.scaled(
        THUMB_W,
        THUMB_H,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def fetch_thumbnail_bytes(url) -> bytes | None:
    """Blocking thumbnail fetch; callers run it in a worker thread."""
    if not url:
        return None
    try:
        import requests

        response = requests.get(url, timeout=8)
        response.raise_for_status()
        return response.content
    except Exception:
        return None

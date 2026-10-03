"""Video preview: thumbnail, metadata and the format radio buttons (flow.md #12).

The selected object is always the full FormatChoice — the GUI never rebuilds a
format id from the label text (flow.md #13).
"""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QMovie
from PyQt6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.format_selector import FormatChoice
from core.i18n import tr
from core.utils import get_resource_path
from gui.theme import (
    CHAPTER_PANEL_STYLE,
    FORMAT_GROUP_STYLE,
    LIVE_BADGE_STYLE,
    MANGA_TITLE_STYLE,
    PREVIEW_META_STYLE,
    SCROLLBAR_STYLE,
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
    """Metadata + format radio buttons for the currently previewed URL."""

    formatChanged = pyqtSignal(object)  # FormatChoice | None

    def __init__(self, parent=None):
        super().__init__(parent)

        self._choices: list[FormatChoice] = []
        self._buttons: dict[str, object] = {}
        self._is_live = False
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.buttonToggled.connect(self._on_toggled)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        layout.addWidget(self._build_meta())
        layout.addWidget(self._build_formats(), 1)
        layout.addWidget(self._build_loading(), 1)
        self.set_loading(False)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_meta(self) -> QWidget:
        self.meta_panel = QWidget()
        self.meta_panel.setObjectName("preview_meta")
        self.meta_panel.setStyleSheet(CHAPTER_PANEL_STYLE)

        outer = QVBoxLayout(self.meta_panel)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)

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

        outer.addLayout(line1)
        outer.addLayout(line2)

        return self.meta_panel

    def _build_formats(self) -> QWidget:
        self.formats_panel = QWidget()
        self.formats_panel.setObjectName("preview_formats")
        self.formats_panel.setStyleSheet(CHAPTER_PANEL_STYLE)

        outer = QVBoxLayout(self.formats_panel)
        outer.setContentsMargins(6, 6, 6, 6)
        outer.setSpacing(4)

        self.formats_header = QLabel(tr("formats_label"))
        self.formats_header.setStyleSheet(PREVIEW_META_STYLE)

        # Groups are laid out side by side (MP4 | MP3), each one a column of
        # radio buttons under its own header.
        self.radio_host = QWidget()
        self.radio_layout = QHBoxLayout(self.radio_host)
        self.radio_layout.setContentsMargins(2, 0, 2, 0)
        self.radio_layout.setSpacing(28)
        self.radio_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(SCROLLBAR_STYLE)
        scroll.setWidget(self.radio_host)

        self.empty_label = QLabel(tr("no_formats"))
        self.empty_label.setWordWrap(True)
        self.empty_label.setStyleSheet(PREVIEW_META_STYLE)
        self.empty_label.hide()

        outer.addWidget(self.formats_header)
        outer.addWidget(scroll, 1)
        outer.addWidget(self.empty_label)

        return self.formats_panel

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
            self.meta_panel.hide()
            self.formats_panel.hide()
            self.loading_text.setText(tr("loading_preview"))
            self.loading_panel.show()
            self.movie.start()
        else:
            self.movie.stop()
            self.loading_panel.hide()
            self.meta_panel.show()
            self.formats_panel.show()

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

        self._clear_radios()
        self._choices = list(choices)

        groups: dict[str, list[tuple[int, FormatChoice]]] = {}
        for index, choice in enumerate(self._choices):
            groups.setdefault(choice.group, []).append((index, choice))

        for group_name in sorted(
            groups, key=lambda name: (0 if groups[name][0][1].type == "video" else 1, name)
        ):
            column = QWidget()
            column_layout = QVBoxLayout(column)
            column_layout.setContentsMargins(0, 0, 0, 0)
            column_layout.setSpacing(2)

            header = QLabel(group_name)
            header.setStyleSheet(FORMAT_GROUP_STYLE)
            column_layout.addWidget(header)

            for index, choice in groups[group_name]:
                button = make_radio_button(choice.label)
                button.setProperty("choice_index", index)
                self._group.addButton(button)
                self._buttons[self._key(choice)] = button
                column_layout.addWidget(button)

            column_layout.addStretch()
            self.radio_layout.insertWidget(self.radio_layout.count() - 1, column)

        self.empty_label.setVisible(not self._choices)
        self.formats_header.setVisible(bool(self._choices))

        if default is not None:
            self.select_choice(default)
        elif self._choices:
            self.select_choice(self._choices[0])
        else:
            self.formatChanged.emit(None)

    def select_choice(self, choice: FormatChoice):
        button = self._buttons.get(self._key(choice))
        if button is not None:
            button.setChecked(True)
            self.formatChanged.emit(choice)

    def selected_choice(self) -> FormatChoice | None:
        button = self._group.checkedButton()
        if button is None:
            return None
        index = button.property("choice_index")
        try:
            return self._choices[int(index)]
        except (TypeError, ValueError, IndexError):
            return None

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
        self._clear_radios()
        self.empty_label.hide()
        self.formatChanged.emit(None)

    def retranslate(self):
        self.formats_header.setText(tr("formats_label"))
        self.empty_label.setText(tr("no_formats"))
        self.loading_text.setText(tr("loading_preview"))
        self.live_label.setText(tr("live_badge"))

    # ------------------------------------------------------------------
    # INTERNALS
    # ------------------------------------------------------------------

    @staticmethod
    def _key(choice: FormatChoice) -> str:
        return f"{choice.group}|{choice.label}|{choice.format_id}"

    def set_thumbnail(self, data):
        """Set the thumbnail from raw image bytes (or None to clear)."""
        pixmap = pixmap_from_bytes(data)
        if pixmap is None:
            self.thumb.clear()
        else:
            self.thumb.setPixmap(pixmap)

    def _clear_radios(self):
        for button in list(self._buttons.values()):
            self._group.removeButton(button)
            button.deleteLater()
        self._buttons.clear()

        while self.radio_layout.count() > 1:
            item = self.radio_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _on_toggled(self, button, checked: bool):
        if checked:
            self.formatChanged.emit(self.selected_choice())


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

from PyQt6.QtWidgets import QStyledItemDelegate
from PyQt6.QtGui import QColor, QFontMetrics, QPixmap
from PyQt6.QtCore import Qt, QRect, QEvent, pyqtSignal

from core.utils import get_resource_path


class QueueDelegate(QStyledItemDelegate):
    # Emits the job key when the user clicks the trash icon, so MainWindow
    # can call engine.del_job(key).
    deleteRequested = pyqtSignal(str)

    # Row layout: [trash] title (left) + format (right) / [trash] status
    LEFT_PADDING = 5
    GAP = 12  # gap between the title and the format label

    TRASH_SIZE = 16
    TRASH_GAP = 6
    TRASH_TOP_PADDING = 2


    def __init__(self, parent=None):
        super().__init__(parent)

        self.trash_pixmap = QPixmap(str(get_resource_path("assets/trash.svg")))

        # `parent` must be the view so we can grab its viewport, enable mouse
        # tracking, and install an event filter on it.
        self._view = parent
        if self._view is not None:
            self._view.setMouseTracking(True)
            self._view.viewport().setMouseTracking(True)
            self._view.viewport().installEventFilter(self)
            self._view.destroyed.connect(self._on_view_destroyed)

    def _on_view_destroyed(self, *_):
        self._view = None

    def _trash_rect(self, row_rect: QRect) -> QRect:
        """Return the area occupied by the trash icon.

        The icon is aligned with the title line (the top line), not centered
        on the whole row.
        """
        title_height = row_rect.height() // 2 + 2
        top = (
            row_rect.top()
            + self.TRASH_TOP_PADDING
            + max(0, (title_height - self.TRASH_SIZE) // 2)
        )
        return QRect(
            row_rect.left() + self.LEFT_PADDING,
            top,
            self.TRASH_SIZE,
            self.TRASH_SIZE,
        )

    def eventFilter(self, obj, event):
        # Switch to a pointing-hand cursor while hovering over the trash icon.
        try:
            if self._view is not None and obj is self._view.viewport():
                if event.type() == QEvent.Type.MouseMove:
                    index = self._view.indexAt(event.pos())
                    if index.isValid() and self._trash_rect(self._view.visualRect(index)).contains(event.pos()):
                        self._view.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
                    else:
                        self._view.viewport().unsetCursor()
                elif event.type() == QEvent.Type.Leave:
                    self._view.viewport().unsetCursor()
        except RuntimeError:
            self._view = None

        return super().eventFilter(obj, event)

    def paint(self, painter, option, index):
        data = index.data(Qt.ItemDataRole.UserRole)
        if not data:
            return

        title = data.get("title", "")
        fmt = data.get("format", "")
        size = data.get("size", "")
        status = data.get("status", "")

        painter.save()
        rect = option.rect

        # ================= TRASH ICON =================
        trash_rect = self._trash_rect(rect)
        if not self.trash_pixmap.isNull():
            painter.drawPixmap(trash_rect, self.trash_pixmap)

        # ================= TEXT AREA (left) =================
        # Layout: [trash] title format  /  [trash] status
        # The trash icon is centered vertically, so both lines start to its right.
        text_left = trash_rect.right() + self.TRASH_GAP
        text_width = max(0, rect.right() - text_left)
        text_rect = QRect(
            text_left,
            rect.top() + self.TRASH_TOP_PADDING,
            text_width,
            rect.height(),
        )

        metrics = QFontMetrics(painter.font())
        half = text_rect.height() // 2
        title_rect = QRect(text_rect.left(), text_rect.top(), text_rect.width(), half + 2)
        status_text_rect = QRect(text_rect.left(), text_rect.top() + half, text_rect.width(), half)

        # ---- line 1: title (left) + format (right) ----
        format_width = metrics.horizontalAdvance(fmt) if fmt else 0
        title_width = max(0, title_rect.width() - format_width - self.GAP)

        painter.setPen(QColor("#e0e0e0"))
        painter.drawText(
            QRect(title_rect.left(), title_rect.top(), title_width, title_rect.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            metrics.elidedText(title, Qt.TextElideMode.ElideRight, title_width),
        )

        if fmt:
            painter.setPen(QColor("#9e9e9e"))
            painter.drawText(
                title_rect,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                fmt,
            )

        # ================= line 2: status (left) + size (right) =================
        size_width = metrics.horizontalAdvance(size) if size else 0
        reserved = size_width + self.GAP if size else 0
        status_rect = QRect(
            status_text_rect.left(),
            status_text_rect.top(),
            max(0, status_text_rect.width() - reserved),
            status_text_rect.height(),
        )

        painter.setPen(QColor(_status_color(status)))

        font = painter.font()
        if metrics.horizontalAdvance(status) > status_rect.width():
            font.setPointSizeF(max(2.0, font.pointSizeF() - 1))
            while font.pointSizeF() > 2.0:
                if QFontMetrics(font).horizontalAdvance(status) <= status_rect.width():
                    break
                font.setPointSizeF(max(2.0, font.pointSizeF() - 0.5))
            painter.setFont(font)

        painter.drawText(
            status_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            status,
        )

        if size:
            painter.setPen(QColor("#9e9e9e"))
            painter.drawText(
                status_text_rect,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                size,
            )

        painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.Type.MouseButtonRelease:
            if event.button() == Qt.MouseButton.LeftButton:
                if self._trash_rect(option.rect).contains(event.pos()):
                    data = index.data(Qt.ItemDataRole.UserRole)
                    key = data.get("key") if data else None
                    if key:
                        self.deleteRequested.emit(key)
                    return True
        return super().editorEvent(event, model, option, index)


def _status_color(status: str) -> str:
    if status in ("Done", "Finished"):
        return "#2196F3"
    if status == "Waiting":
        return "#FFC107"
    if status in ("Error", "Failed"):
        return "#F44336"
    if status == "Paused":
        return "#9E9E9E"
    if status.startswith(("Downloading", "Processing", "Starting")):
        return "#4CAF50"
    return "#e0e0e0"

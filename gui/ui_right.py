from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QLabel,
)
from PyQt6.QtCore import QSize, Qt, pyqtSignal

from gui.queue_delegate import QueueDelegate
from gui.theme import QUEUE_LIST_STYLE
from core.i18n import tr
from core.utils import format_size

ROW_HEIGHT = 40

TERMINAL_STATUSES = ("Done",)


class RightPanel(QWidget):
    """
    Right side of the main window:
    - Start / Resume / Pause / Clear Done buttons (top)
    - Queue list (bottom)
    """

    # Emitted when the user clicks the trash icon on a job in the queue list.
    # MainWindow connects this signal to call engine.del_job(key).
    deleteRequested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # ================= BUTTON ROW (top) =================
        self.btn_start = QPushButton(tr("start"))
        self.btn_resume = QPushButton(tr("resume"))
        self.btn_pause = QPushButton(tr("pause"))
        self.btn_clear = QPushButton(tr("clear_done"))

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(0, 0, 0, 0)
        btn_row.setSpacing(6)
        btn_row.addWidget(self.btn_start)
        btn_row.addWidget(self.btn_resume)
        btn_row.addWidget(self.btn_pause)
        btn_row.addWidget(self.btn_clear)

        # ================= QUEUE LIST =================
        self.queue_list = QListWidget()
        self.queue_list.setObjectName("queue_list")
        self.queue_list.setStyleSheet(QUEUE_LIST_STYLE)
        self._delegate = QueueDelegate(self.queue_list)
        self.queue_list.setItemDelegate(self._delegate)
        self._delegate.deleteRequested.connect(self.deleteRequested)
        self.queue_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.queue_label = QLabel(tr("queue"))

        self.row_buttons = QWidget()
        self.row_buttons.setLayout(btn_row)

        layout.addWidget(self.queue_label)
        layout.addWidget(self.row_buttons)
        layout.addWidget(self.queue_list)

        self.btn_clear.clicked.connect(self.clear_done)
        self._update_queue_label()

    def retranslate(self):
        self.btn_start.setText(tr("start"))
        self.btn_resume.setText(tr("resume"))
        self.btn_pause.setText(tr("pause"))
        self.btn_clear.setText(tr("clear_done"))
        self._update_queue_label()

    def _update_queue_label(self):
        count = self.queue_list.count()
        if count:
            self.queue_label.setText(tr("queue_with_count").format(count=count))
        else:
            self.queue_label.setText(tr("queue"))

    def _find(self, key):
        for i in range(self.queue_list.count()):
            item = self.queue_list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if data and data.get("key") == key:
                return i, item, data
        return None, None, None

    def add_queue_item(self, job, status="Waiting"):
        index, _item, _data = self._find(job.key)
        if index is not None:
            return

        item = QListWidgetItem(job.title)
        item.setSizeHint(QSize(0, ROW_HEIGHT))
        item.setData(
            Qt.ItemDataRole.UserRole,
            {
                "key": job.key,
                "url": job.url,
                "title": job.title,
                "format": job.format_label,
                "size": format_size(job.size_bytes),
                "status": status,
                "path": str(job.save_path),
            },
        )
        self.queue_list.addItem(item)
        self._update_queue_label()

    def update_queue_item(self, job, status):
        index, _item, data = self._find(job.key)
        if index is None:
            self.add_queue_item(job, status)
            return

        data["status"] = status
        data["format"] = job.format_label
        data["size"] = format_size(job.size_bytes)
        self.queue_list.item(index).setData(Qt.ItemDataRole.UserRole, data)
        self.queue_list.viewport().update()

    def update_progress(self, key, status):
        index, item, data = self._find(key)
        if index is None:
            return
        data["status"] = status
        item.setData(Qt.ItemDataRole.UserRole, data)
        self.queue_list.viewport().update()

    def remove_queue_item(self, key):
        index, _item, _data = self._find(key)
        if index is not None:
            self.queue_list.takeItem(index)
            self._update_queue_label()

    def clear_queue(self):
        """Empty the visible queue (the jobs themselves stay in the database)."""
        self.queue_list.clear()
        self._update_queue_label()

    def set_all_status(self, status):
        """Set every non-finished item to the given status."""
        for i in range(self.queue_list.count()):
            item = self.queue_list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if data and data.get("status") not in TERMINAL_STATUSES:
                data["status"] = status
                item.setData(Qt.ItemDataRole.UserRole, data)
        self.queue_list.viewport().update()

    def has_status(self, status) -> bool:
        for i in range(self.queue_list.count()):
            item = self.queue_list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if data and data.get("status") == status:
                return True
        return False

    def all_finished(self) -> bool:
        count = self.queue_list.count()
        if count == 0:
            return False
        for i in range(count):
            item = self.queue_list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole) or {}
            if data.get("status") not in TERMINAL_STATUSES:
                return False
        return True

    def clear_done(self):
        for i in range(self.queue_list.count() - 1, -1, -1):
            item = self.queue_list.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if data and data.get("status") in TERMINAL_STATUSES:
                self.queue_list.takeItem(i)
        self._update_queue_label()

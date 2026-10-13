from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QWidget, QPushButton, QCheckBox, QRadioButton, QToolButton
from PyQt6.QtCore import Qt

_POINTER_WIDGET_TYPES = (QPushButton, QCheckBox, QRadioButton, QToolButton)


def apply_pointer_cursors(root: QWidget, event_filter: QWidget = None):
    """Recursively set a pointing-hand cursor on every clickable widget
    under `root` (buttons, checkboxes, radio buttons, tool buttons).

    Qt Style Sheets don't support the `cursor` CSS property, so this has
    to be done in code instead. If `event_filter` is given, it is
    installed on QPushButton/QToolButton instances so the cursor can be
    updated to "forbidden" when they become disabled.
    """
    pointer = QCursor(Qt.CursorShape.PointingHandCursor)

    for widget in root.findChildren(_POINTER_WIDGET_TYPES):
        widget.setCursor(pointer)
        if event_filter is not None and isinstance(widget, (QPushButton, QToolButton)):
            widget.installEventFilter(event_filter)
"""Shared small widget factories used across the GUI panels."""

from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QCheckBox, QRadioButton, QToolButton

from core.utils import get_resource_path
from gui.theme import CHECKBOX_STYLE, OUTLINE_BUTTON_STYLE, RADIO_STYLE

# Checkbox rows sit next to the same-height text inputs / buttons, so a fixed
# height keeps the rows of the sidebar aligned.
CHECKBOX_HEIGHT = 20

# Help "?" icon button: small, square, sitting next to the control it explains.
HELP_ICON_SIZE = 16
HELP_BUTTON_SIZE = 20


class _HoverIconButton(QToolButton):
    """A QToolButton that swaps to a highlight icon while hovered.

    The icon is chosen on enter/leave rather than through a stylesheet, so it
    works with the flat, stylesheet-styled buttons used in the app.
    """

    def __init__(self, icon: QIcon, hover_icon: QIcon, parent=None):
        super().__init__(parent)
        self._icon = icon
        self._hover_icon = hover_icon
        self.setIcon(icon)

    def enterEvent(self, event):
        self.setIcon(self._hover_icon)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setIcon(self._icon)
        super().leaveEvent(event)


def make_help_button(callback=None) -> QToolButton:
    """A "?" help button: gray icon, green while hovered."""
    button = _HoverIconButton(
        QIcon(str(get_resource_path("assets/question.svg"))),
        QIcon(str(get_resource_path("assets/question-hover.svg"))),
    )
    button.setIconSize(QSize(HELP_ICON_SIZE, HELP_ICON_SIZE))
    button.setFixedSize(HELP_BUTTON_SIZE, HELP_BUTTON_SIZE)
    button.setAutoRaise(True)
    button.setStyleSheet(OUTLINE_BUTTON_STYLE)
    if callback is not None:
        button.clicked.connect(callback)
    return button


def make_radio_button(text: str) -> QRadioButton:
    """A QRadioButton with the app's custom indicator icons applied."""
    btn = QRadioButton(text)
    btn.setStyleSheet(RADIO_STYLE)
    return btn


def make_checkbox(text: str) -> QCheckBox:
    """A QCheckBox with the app's custom indicator icons applied."""
    cb = QCheckBox(text)
    cb.setStyleSheet(CHECKBOX_STYLE)
    cb.setFixedHeight(CHECKBOX_HEIGHT)
    return cb

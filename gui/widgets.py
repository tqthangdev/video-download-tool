"""Shared small widget factories used across the GUI panels."""

from PyQt6.QtCore import QPointF, QSize
from PyQt6.QtGui import QBrush, QColor, QIcon, QLinearGradient, QPalette
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QRadioButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
)

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


class _PopupHighlightDelegate(QStyledItemDelegate):
    """Paints the green highlight behind a hovered/selected combo popup item.

    A stylesheet `::item:hover` rule is unreliable on a QComboBox popup, so the
    background is drawn here (and the base style is asked to skip its own
    hover/selection fill, leaving just the text).
    """

    TOP = "#66bb6a"
    BOTTOM = "#4caf50"
    TEXT = "#1e1e1e"

    def paint(self, painter, option, index):
        highlighted = bool(
            option.state
            & (QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_Selected)
        )
        opt = QStyleOptionViewItem(option)
        if highlighted:
            gradient = QLinearGradient(
                QPointF(option.rect.topLeft()), QPointF(option.rect.bottomLeft())
            )
            gradient.setColorAt(0.0, QColor(self.TOP))
            gradient.setColorAt(1.0, QColor(self.BOTTOM))
            painter.fillRect(option.rect, QBrush(gradient))

            opt.state = opt.state & ~(
                QStyle.StateFlag.State_MouseOver | QStyle.StateFlag.State_Selected
            )
            opt.palette.setColor(QPalette.ColorRole.Text, QColor(self.TEXT))
            opt.palette.setColor(QPalette.ColorRole.HighlightedText, QColor(self.TEXT))
        super().paint(painter, opt, index)


class _HoverCombo(QComboBox):
    """A combo box whose popup items highlight with a green gradient.

    A stylesheet `::item` rule makes Qt install its own item delegate, so ours
    is (re)applied right before the popup is shown — the last one wins.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # The view does not own the delegate, so keep a reference or it gets
        # collected and the popup falls back to the default one.
        self._hover_delegate: _PopupHighlightDelegate | None = None

    def showPopup(self):
        super().showPopup()
        # Apply after the popup is up: the stylesheet installs its own item
        # delegate while the popup is being polished.
        view = self.view()
        view.setMouseTracking(True)
        view.viewport().setMouseTracking(True)
        if self._hover_delegate is None:
            self._hover_delegate = _PopupHighlightDelegate(view)
        view.setItemDelegate(self._hover_delegate)
        view.viewport().update()


def make_combo() -> QComboBox:
    """A combo box with the green hover highlight on its popup items."""
    return _HoverCombo()


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

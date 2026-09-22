"""Shared small widget factories used across the GUI panels."""

from PyQt6.QtWidgets import QCheckBox, QRadioButton

from gui.theme import CHECKBOX_STYLE, RADIO_STYLE


def make_radio_button(text: str) -> QRadioButton:
    """A QRadioButton with the app's custom indicator icons applied."""
    btn = QRadioButton(text)
    btn.setStyleSheet(RADIO_STYLE)
    return btn


def make_checkbox(text: str) -> QCheckBox:
    """A QCheckBox with the app's custom indicator icons applied."""
    cb = QCheckBox(text)
    cb.setStyleSheet(CHECKBOX_STYLE)
    return cb

"""Theme palettes and the application stylesheet.

The whole look is generated from a single palette so the app can switch between
the dark and light themes at runtime. `apply_theme()` rebuilds one stylesheet
and sets it on the application, so every widget — including dialogs created
later — follows the current theme.

Widgets do not carry their own stylesheet; they are addressed here through
their class or object name (`QLabel#meta_label`, `QLineEdit#compact_input`, ...).
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import QApplication

from core.utils import get_resource_path

SYSTEM = "system"
LIGHT = "light"
DARK = "dark"
THEMES = (SYSTEM, LIGHT, DARK)

# Qt resolves relative url(...) paths inside a stylesheet against the current
# working directory, not the application directory. In a frozen build the
# assets live under the bundle (_MEIPASS/assets) while the cwd can be anywhere,
# so the icons are always addressed through the absolute assets path.
_ASSETS_DIR = get_resource_path("assets").as_posix()

PALETTES = {
    DARK: {
        "window": "#1e1e1e",
        "text": "#d4d4d4",
        "text_strong": "#e0e0e0",
        "text_dim": "#9e9e9e",
        "title": "#ff9800",
        "badge": "#ff3b30",
        "accent": "#4CAF50",
        "button_bg": "#3a3a3a",
        "button_border": "#555555",
        "button_hover": "#4a4a4a",
        "button_pressed": "#2f2f2f",
        "button_off_bg": "#262626",
        "button_off_border": "#3a3a3a",
        "button_off_text": "#6e6e6e",
        "input_bg": "#2d2d2d",
        "input_border": "#ffffff",
        "input_focus_bg": "#333333",
        "surface": "#1e1e1e",
        "surface_border": "#ffffff",
        "group_border": "#555555",
        "group_title": "#9e9e9e",
        "scroll_handle": "#4a4a4a",
        "scroll_line": "#3a3a3a",
        "menu_bg": "#1e1e1e",
        "menu_border": "#555555",
        "menu_hover": "#3a3a3a",
        "icon_suffix": "",
    },
    LIGHT: {
        "window": "#f4f4f4",
        "text": "#202020",
        "text_strong": "#202020",
        "text_dim": "#6b6b6b",
        "title": "#e07b00",
        "badge": "#d32f2f",
        "accent": "#4CAF50",
        "button_bg": "#e9e9e9",
        "button_border": "#bdbdbd",
        "button_hover": "#dedede",
        "button_pressed": "#d2d2d2",
        "button_off_bg": "#efefef",
        "button_off_border": "#dcdcdc",
        "button_off_text": "#a0a0a0",
        "input_bg": "#ffffff",
        "input_border": "#bdbdbd",
        "input_focus_bg": "#ffffff",
        "surface": "#ffffff",
        "surface_border": "#bdbdbd",
        "group_border": "#c4c4c4",
        "group_title": "#6b6b6b",
        "scroll_handle": "#c0c0c0",
        "scroll_line": "#d8d8d8",
        "menu_bg": "#ffffff",
        "menu_border": "#bdbdbd",
        "menu_hover": "#e6e6e6",
        "icon_suffix": "-light",
    },
}

# Selection gradient shared by menus and combo popups (identical on both themes,
# with dark text drawn on top of it).
_GRADIENT = "qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #66bb6a, stop:1 #4caf50)"

_theme = SYSTEM
_palette = PALETTES[DARK]


def _resolve(name: str) -> str:
    """Turn "system" into the theme the OS asks for."""
    if name != SYSTEM:
        return name if name in PALETTES else DARK
    try:
        if QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Light:
            return LIGHT
    except Exception:  # noqa: BLE001 - older Qt / no style hints available
        pass
    return DARK


def current_theme() -> str:
    """The user's choice: "system", "light" or "dark"."""
    return _theme


def resolved_theme() -> str:
    """The palette actually in use ("light" or "dark")."""
    return LIGHT if _palette is PALETTES[LIGHT] else DARK


def color(key: str) -> str:
    """A palette colour, for painters that cannot use a stylesheet."""
    return _palette[key]


def asset(name: str) -> str:
    """Absolute asset path, using the light variant when one exists."""
    path = get_resource_path("assets") / name
    suffix = _palette["icon_suffix"]
    if suffix:
        alternate = path.with_name(f"{path.stem}{suffix}{path.suffix}")
        if alternate.is_file():
            return str(alternate)
    return str(path)


def apply_theme(name: str | None = None, app=None) -> None:
    """Select a theme (default: the current choice) and restyle the app."""
    global _theme, _palette
    if name is not None:
        _theme = name
    _palette = PALETTES[_resolve(_theme)]

    app = app if app is not None else QApplication.instance()
    if app is not None:
        app.setStyleSheet(stylesheet())


def _resolve_assets(style: str) -> str:
    """Point every url("assets/...") at the absolute bundled assets path."""
    return style.replace('"assets/', f'"{_ASSETS_DIR}/')


def stylesheet() -> str:
    """The full application stylesheet for the current palette."""
    p = _palette
    icon = p["icon_suffix"]
    return _resolve_assets(f"""
QWidget {{
    background-color: {p['window']};
    color: {p['text']};
}}
QPushButton {{
    background-color: {p['button_bg']};
    border: 1px solid {p['button_border']};
    border-radius: 4px;
    padding: 5px 12px;
    color: {p['text_strong']};
}}
QPushButton:hover {{
    background-color: {p['button_hover']};
}}
QPushButton:pressed {{
    background-color: {p['button_pressed']};
}}
QPushButton:disabled {{
    background-color: {p['button_off_bg']};
    border-color: {p['button_off_border']};
    color: {p['button_off_text']};
}}
QLineEdit, QSpinBox, QComboBox {{
    background-color: {p['input_bg']};
    border: 1px solid {p['input_border']};
    border-radius: 4px;
    padding: 5px 8px;
    color: {p['text_strong']};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 2px solid {p['accent']};
    background-color: {p['input_focus_bg']};
}}
QLineEdit#compact_input {{
    border-radius: 3px;
    padding: 0px 4px;
}}
QLineEdit#session_name_input[readOnly="true"] {{
    background: transparent;
    border: none;
    padding: 0px;
    color: {p['text']};
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border: none;
}}
QComboBox::down-arrow {{
    image: url("assets/spin-down{icon}.svg");
    width: 10px;
    height: 6px;
}}
QComboBox QAbstractItemView {{
    background-color: {p['surface']};
    color: {p['text_strong']};
    border: 1px solid {p['surface_border']};
    outline: none;
}}
QComboBox QAbstractItemView::item {{
    padding: 3px 6px;
}}
QComboBox QAbstractItemView::item:hover,
QComboBox QAbstractItemView::item:selected {{
    background: {_GRADIENT};
    color: #1e1e1e;
}}
QSpinBox::up-button, QSpinBox::down-button {{
    background: transparent;
    border: none;
    width: 16px;
}}
QSpinBox::up-arrow {{
    image: url("assets/spin-up{icon}.svg");
    width: 10px;
    height: 6px;
}}
QSpinBox::up-arrow:pressed {{
    image: url("assets/spin-up-active.svg");
}}
QSpinBox::down-arrow {{
    image: url("assets/spin-down{icon}.svg");
    width: 10px;
    height: 6px;
}}
QSpinBox::down-arrow:pressed {{
    image: url("assets/spin-down-active.svg");
}}
QGroupBox {{
    border: 1px solid {p['group_border']};
    border-radius: 4px;
    margin-top: 13px;
    padding: 1px;
    font-weight: bold;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 6px;
    padding: 0px 3px;
    color: {p['group_title']};
}}
QRadioButton::indicator {{
    width: 14px;
    height: 14px;
}}
QRadioButton::indicator:unchecked {{
    image: url("assets/radio-unchecked{icon}.svg");
}}
QRadioButton::indicator:checked {{
    image: url("assets/radio-checked{icon}.svg");
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
}}
QCheckBox::indicator:unchecked {{
    image: url("assets/checkbox-unchecked{icon}.svg");
}}
QCheckBox::indicator:checked {{
    image: url("assets/checkbox-checked{icon}.svg");
}}
QListWidget {{
    background-color: {p['surface']};
    border: 1px solid {p['surface_border']};
    border-radius: 0px;
    color: {p['text_strong']};
}}
QListWidget#queue_list {{
    background: transparent;
}}
QTextEdit {{
    background-color: {p['surface']};
    border: 1px solid {p['surface_border']};
    border-radius: 0px;
    padding: 4px 6px;
    color: {p['text_strong']};
}}
QProgressBar {{
    border: 1px solid {p['group_border']};
    border-radius: 4px;
    background-color: {p['surface']};
}}
QProgressBar::chunk {{
    background-color: {p['accent']};
    border-radius: 3px;
}}
QToolButton {{
    color: {p['text_strong']};
    border: none;
    background: transparent;
}}
QToolButton:hover {{
    color: {p['text_strong']};
    border: none;
    background: transparent;
}}
QLabel#video_title {{
    font-size: 16px;
    font-weight: bold;
    color: {p['title']};
}}
QLabel#dialog_title {{
    font-size: 14px;
    font-weight: bold;
    color: {p['title']};
}}
QLabel#live_badge {{
    font-size: 12px;
    font-weight: bold;
    color: {p['badge']};
}}
QLabel#meta_label {{
    color: {p['text_dim']};
    font-size: 12px;
}}
QMenuBar {{
    background-color: {p['window']};
    color: {p['text']};
}}
QMenuBar::item {{
    background: transparent;
    padding: 4px 8px;
}}
QMenuBar::item:selected {{
    background-color: {p['menu_hover']};
}}
QMenu {{
    background-color: {p['menu_bg']};
    border: 1px solid {p['menu_border']};
}}
QMenu::item {{
    padding: 5px 24px 5px 12px;
    color: {p['text_strong']};
}}
QMenu::item:disabled {{
    color: {p['button_off_text']};
}}
QMenu::item:selected {{
    background: {_GRADIENT};
    color: #1e1e1e;
}}
QMenu::separator {{
    height: 1px;
    background: {p['group_border']};
    margin: 4px 8px;
}}
""") + _scrollbar_stylesheet(p, icon)


def _scrollbar_stylesheet(p: dict, icon: str) -> str:
    """Thin, flat scrollbar matching the current palette."""
    return _resolve_assets(f"""
QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 12px 0px 12px 0px;
}}
QScrollBar::handle:vertical {{
    background: {p['scroll_handle']};
    border-radius: 0px;
    min-height: 36px;
}}
QScrollBar::add-line:vertical {{
    subcontrol-position: bottom;
    subcontrol-origin: margin;
    height: 12px;
    background: {p['scroll_line']};
    border-bottom-left-radius: 4px;
    border-bottom-right-radius: 4px;
}}
QScrollBar::sub-line:vertical {{
    subcontrol-position: top;
    subcontrol-origin: margin;
    height: 12px;
    background: {p['scroll_line']};
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}}
QScrollBar::add-line:vertical:hover, QScrollBar::sub-line:vertical:hover {{
    background: {p['scroll_handle']};
}}
QScrollBar::up-arrow:vertical {{
    image: url("assets/spin-up{icon}.svg");
    width: 8px;
    height: 5px;
}}
QScrollBar::down-arrow:vertical {{
    image: url("assets/spin-down{icon}.svg");
    width: 8px;
    height: 5px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 12px;
    margin: 0px 12px 0px 12px;
}}
QScrollBar::handle:horizontal {{
    background: {p['scroll_handle']};
    border-radius: 5px;
    min-width: 24px;
}}
QScrollBar::add-line:horizontal {{
    subcontrol-position: right;
    subcontrol-origin: margin;
    width: 12px;
    background: {p['scroll_line']};
    border-top-right-radius: 4px;
    border-bottom-right-radius: 4px;
}}
QScrollBar::sub-line:horizontal {{
    subcontrol-position: left;
    subcontrol-origin: margin;
    width: 12px;
    background: {p['scroll_line']};
    border-top-left-radius: 4px;
    border-bottom-left-radius: 4px;
}}
QScrollBar::add-line:horizontal:hover, QScrollBar::sub-line:horizontal:hover {{
    background: {p['scroll_handle']};
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
}}
""")

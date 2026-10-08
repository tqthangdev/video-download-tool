"""Shared Qt Style Sheet fragments.

Every widget stylesheet in the app lives here so the same look (scrollbars,
radio/checkbox indicators, dialogs, ...) doesn't have to be copy-pasted into
every widget's stylesheet across the app.
"""

from core.utils import get_resource_path

# Qt resolves relative url(...) paths inside a stylesheet against the current
# working directory, not the application directory. In a frozen build the
# assets live under the bundle (_MEIPASS/assets) while the cwd can be anywhere,
# so the indicator/spin/trash SVGs would silently fail to load. Resolve them to
# the bundled assets directory instead of relying on the cwd.
_ASSETS_DIR = get_resource_path("assets").as_posix()


def _resolve_assets(style: str) -> str:
    """Point every url("assets/...") at the absolute bundled assets path."""
    return style.replace('"assets/', f'"{_ASSETS_DIR}/')


# Thin, flat scrollbar matching the app's dark theme (#1e1e1e / #4a4a4a),
# with a green highlight on hover to match the app's accent color (#4CAF50).
SCROLLBAR_STYLE = _resolve_assets("""
QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 12px 0px 12px 0px;
}
QScrollBar::handle:vertical {
    background: #4a4a4a;
    border-radius: 0px;
    min-height: 36px;
}
QScrollBar::add-line:vertical {
    subcontrol-position: bottom;
    subcontrol-origin: margin;
    height: 12px;
    background: #3a3a3a;
    border-bottom-left-radius: 4px;
    border-bottom-right-radius: 4px;
}
QScrollBar::sub-line:vertical {
    subcontrol-position: top;
    subcontrol-origin: margin;
    height: 12px;
    background: #3a3a3a;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
}
QScrollBar::add-line:vertical:hover, QScrollBar::sub-line:vertical:hover {
    background: #4a4a4a;
}
QScrollBar::up-arrow:vertical {
    image: url("assets/spin-up.svg");
    width: 8px;
    height: 5px;
}
QScrollBar::down-arrow:vertical {
    image: url("assets/spin-down.svg");
    width: 8px;
    height: 5px;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: transparent;
}

QScrollBar:horizontal {
    background: transparent;
    height: 12px;
    margin: 0px 12px 0px 12px;
}
QScrollBar::handle:horizontal {
    background: #4a4a4a;
    border-radius: 5px;
    min-width: 24px;
}
QScrollBar::add-line:horizontal {
    subcontrol-position: right;
    subcontrol-origin: margin;
    width: 12px;
    background: #3a3a3a;
    border-top-right-radius: 4px;
    border-bottom-right-radius: 4px;
}
QScrollBar::sub-line:horizontal {
    subcontrol-position: left;
    subcontrol-origin: margin;
    width: 12px;
    background: #3a3a3a;
    border-top-left-radius: 4px;
    border-bottom-left-radius: 4px;
}
QScrollBar::add-line:horizontal:hover, QScrollBar::sub-line:horizontal:hover {
    background: #4a4a4a;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: transparent;
}
""")

# Base look applied to the main window: dark background, flat buttons and
# input fields with a green focus ring.
MAIN_WINDOW_STYLE = """
QWidget {
    background-color: #1e1e1e;
    color: #d4d4d4;
}
QPushButton {
    background-color: #3a3a3a;
    border: 1px solid #555555;
    border-radius: 4px;
    padding: 5px 12px;
    color: #e0e0e0;
}
QPushButton:hover {
    background-color: #4a4a4a;
}
QPushButton:pressed {
    background-color: #2f2f2f;
}
QPushButton:disabled {
    background-color: #262626;
    border-color: #3a3a3a;
    color: #6e6e6e;
}
QLineEdit {
    background-color: #2d2d2d;
    border: 1px solid #ffffff;
    border-radius: 4px;
    padding: 5px 8px;
    color: #e0e0e0;
}
QLineEdit:focus {
    border: 2px solid #4CAF50;
    background-color: #333333;
}
"""

# Radio buttons with the app's custom indicator icons (checked/unchecked SVGs).
RADIO_STYLE = _resolve_assets("""
QRadioButton::indicator {
    width: 14px;
    height: 14px;
}
QRadioButton::indicator:unchecked {
    image: url("assets/radio-unchecked.svg");
}
QRadioButton::indicator:checked {
    image: url("assets/radio-checked.svg");
}
""")

# Check boxes with the app's custom indicator icons (checked/unchecked SVGs).
CHECKBOX_STYLE = _resolve_assets("""
QCheckBox::indicator {
    width: 18px;
    height: 18px;
}
QCheckBox::indicator:unchecked {
    image: url("assets/checkbox-unchecked.svg");
}
QCheckBox::indicator:checked {
    image: url("assets/checkbox-checked.svg");
}
""")

# Border for the left panel's preview box (metadata + format picker).
PREVIEW_PANEL_STYLE = """
QWidget#video_preview {
    background: transparent;
    border: 1px solid #adadad;
}
"""

# Format picker in the video preview (single combo box, white border like the
# other inputs, shared thin scrollbar for the popup list).
PREVIEW_COMBO_STYLE = _resolve_assets("""
QComboBox {
    background-color: #1e1e1e;
    border: 1px solid #ffffff;
    border-radius: 4px;
    padding: 4px 6px;
    color: #e0e0e0;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border: none;
}
QComboBox::down-arrow {
    image: url("assets/spin-down.svg");
    width: 10px;
    height: 6px;
}
QComboBox QAbstractItemView {
    background-color: #1e1e1e;
    color: #e0e0e0;
    border: 1px solid #ffffff;
    outline: none;
}
QComboBox QAbstractItemView::item {
    padding: 3px 6px;
}
QComboBox QAbstractItemView::item:hover,
QComboBox QAbstractItemView::item:selected {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #66bb6a, stop:1 #4caf50);
    color: #1e1e1e;
}
""") + SCROLLBAR_STYLE

# Queue list in the right panel: transparent background + thin white border.
QUEUE_LIST_STYLE = """
QWidget#queue_list {
    background: transparent;
    border: 1px solid #ffffff;
}
""" + SCROLLBAR_STYLE

# Progress bar (restore / add-jobs / update dialogs).
PROGRESS_STYLE = """
QProgressBar {
    border: 1px solid #555555;
    border-radius: 4px;
    background-color: #1e1e1e;
}

QProgressBar::chunk {
    background-color: #4caf50;
    border-radius: 3px;
}
"""

# Input fields of the settings dialog (config.json editor).
CONFIG_DIALOG_STYLE = _resolve_assets("""
QLineEdit, QSpinBox, QComboBox {
    height: 16px;
    background-color: #1e1e1e;
    border: 1px solid #ffffff;
    border-radius: 4px;
    padding: 4px 6px;
    color: #e0e0e0;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 2px solid #4CAF50;
    background-color: #1e1e1e;
}
QLineEdit:focus, QSpinBox:focus {
    padding: 2px 4px;
}
QComboBox:on {
    color: #4CAF50;
}
QSpinBox::up-button, QSpinBox::down-button {
    background-color: #1e1e1e;
    border: none;
    width: 16px;
}
QSpinBox::up-button {
    subcontrol-position: top right;
    border-top-right-radius: 4px;
}
QSpinBox::down-button {
    subcontrol-position: bottom right;
    border-bottom-right-radius: 4px;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background-color: #1e1e1e;
}
QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {
    background-color: #1e1e1e;
}
QSpinBox::up-arrow {
    image: url("assets/spin-up.svg");
    width: 10px;
    height: 6px;
}
QSpinBox::up-arrow:pressed {
    image: url("assets/spin-up-active.svg");
}
QSpinBox::down-arrow {
    image: url("assets/spin-down.svg");
    width: 10px;
    height: 6px;
}
QSpinBox::down-arrow:pressed {
    image: url("assets/spin-down-active.svg");
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
    border-left: 1px solid #1e1e1e;
    background-color: #1e1e1e;
    border-top-right-radius: 4px;
    border-bottom-right-radius: 4px;
}
QComboBox::drop-down:hover {
    background-color: #1e1e1e;
}
QComboBox::down-arrow {
    image: url("assets/spin-down.svg");
    width: 10px;
    height: 6px;
}
QComboBox QAbstractItemView {
    background-color: #1e1e1e;
    color: #e0e0e0;
    border: 1px solid #ffffff;
    outline: none;
}
QComboBox QAbstractItemView::item {
    padding: 3px 6px;
}
QComboBox QAbstractItemView::item:hover,
QComboBox QAbstractItemView::item:selected {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #66bb6a, stop:1 #4caf50);
    color: #1e1e1e;
}
""")

# Section titles: large (manga title, left panel) / small (help dialog).
MANGA_TITLE_STYLE = "font-size:16px; font-weight:bold; color:#ff9800;"
HELP_TITLE_STYLE = "font-size:14px; font-weight:bold; color:#ff9800;"

# "LIVE" badge in the preview, next to a live stream's metadata.
LIVE_BADGE_STYLE = "font-size:12px; font-weight:bold; color:#ff3b30;"

# Generic list box (QListWidget) used across the dialogs: white border like the
# other inputs, dark background and the shared thin scrollbar.
LIST_STYLE = """
QListWidget {
    background-color: #1e1e1e;
    border: 1px solid #ffffff;
    border-radius: 0px;
    color: #e0e0e0;
}
""" + SCROLLBAR_STYLE

# Video preview: metadata text.
PREVIEW_META_STYLE = "color:#9e9e9e; font-size:12px;"

# Session name in the sessions dialog: while read-only it is drawn as a plain
# label (transparent background + no border) instead of a text box.
SESSION_NAME_READONLY_STYLE = """
QLineEdit {
    background: transparent;
    border: none;
    padding: 0px;
    color: #d4d4d4;
}
"""

# Compact input (shutdown countdown box in the sidebar): same colors as the
# regular inputs but with minimal padding so it stays small.
COMPACT_INPUT_STYLE = """
QLineEdit {
    background-color: #2d2d2d;
    border: 1px solid #ffffff;
    border-radius: 3px;
    padding: 0px 4px;
    color: #e0e0e0;
}
QLineEdit:focus {
    border: 2px solid #4CAF50;
    background-color: #333333;
}
"""

# Read-only text area (release notes in the version dialog): dark background
# with a light border so it reads as an input, same palette as the app.
TEXT_AREA_STYLE = """
QTextEdit {
    background-color: #1e1e1e;
    border: 1px solid #ffffff;
    border-radius: 0px;
    padding: 4px 6px;
    color: #e0e0e0;
}
""" + SCROLLBAR_STYLE

# Borderless, transparent button used for secondary actions that should not
# look like the regular push buttons: the "?" help buttons (icon swapped on
# hover by gui.widgets.make_help_button) and the "What's new" toggle.
OUTLINE_BUTTON_STYLE = """
QToolButton,
QToolButton:hover {
    color: #e0e0e0;
    border: none;
    background: transparent;
}
"""
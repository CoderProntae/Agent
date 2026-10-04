"""Dark enterprise theme (GitHub-dark inspired) applied via Qt stylesheets."""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase

# Palette constants reused across custom-painted widgets.
BG_BASE = "#0d1117"
BG_PANEL = "#161b22"
BG_RAISED = "#1c2129"
BG_INPUT = "#0b0f14"
BORDER = "#30363d"
BORDER_LIGHT = "#3d444d"
TEXT_PRIMARY = "#e6edf3"
TEXT_MUTED = "#8b949e"
ACCENT = "#2f81f7"
ACCENT_HOVER = "#4c8eff"
GREEN = "#3fb950"
RED = "#f85149"
YELLOW = "#d29922"
DIFF_ADD_BG = "#0d2818"
DIFF_DEL_BG = "#2d1215"
CODE_BG = "#0b0f14"

CHAT_CSS = f"""
<style>
body {{ color: {TEXT_PRIMARY}; }}
p {{ margin: 4px 0; }}
h1 {{ font-size: 18px; margin: 8px 0 4px; color: {TEXT_PRIMARY}; }}
h2 {{ font-size: 16px; margin: 8px 0 4px; }}
h3 {{ font-size: 14px; margin: 6px 0 3px; }}
h4 {{ font-size: 13px; margin: 6px 0 3px; }}
a {{ color: {ACCENT}; text-decoration: none; }}
ul, ol {{ margin: 4px 0; padding-left: 22px; }}
li {{ margin: 2px 0; }}
blockquote {{ border-left: 3px solid {BORDER_LIGHT}; margin: 6px 0; padding: 2px 10px; color: {TEXT_MUTED}; }}
hr {{ border: none; border-top: 1px solid {BORDER}; margin: 8px 0; }}
code.inline-code {{ background: {CODE_BG}; border: 1px solid {BORDER}; border-radius: 4px; padding: 1px 5px; font-family: Consolas, 'Cascadia Mono', monospace; font-size: 12px; color: #ffa657; }}
div.code-block {{ background: {CODE_BG}; border: 1px solid {BORDER}; border-radius: 6px; margin: 6px 0; }}
div.code-lang {{ color: {TEXT_MUTED}; font-size: 11px; padding: 3px 10px 0; text-transform: lowercase; }}
pre {{ margin: 4px 0; padding: 8px 10px; font-family: Consolas, 'Cascadia Mono', monospace; font-size: 12px; color: {TEXT_PRIMARY}; white-space: pre-wrap; }}
</style>
"""


#: Monospace families tried in order across Windows / macOS / Linux.
_MONO_CANDIDATES = (
    "Cascadia Mono", "Consolas", "JetBrains Mono", "Fira Code",
    "DejaVu Sans Mono", "Ubuntu Mono", "Menlo", "Monaco", "monospace",
)


def mono_font(size: int = 11) -> QFont:
    """Monospace font used by editor and console widgets.

    Resolves the first installed family from :data:`_MONO_CANDIDATES`;
    falls back to the Qt type-writer style hint so rendering always works.
    """
    try:
        db = QFontDatabase()
        available = set(db.families())
        family = next((f for f in _MONO_CANDIDATES if f in available), _MONO_CANDIDATES[1])
    except Exception:  # noqa: BLE001 — font DB unavailable (headless)
        family = _MONO_CANDIDATES[1]
    font = QFont(family, size)
    font.setStyleHint(QFont.TypeWriter)
    return font


DARK_QSS = f"""
* {{
    font-family: 'Segoe UI', 'SF Pro Text', 'Ubuntu', sans-serif;
    font-size: 13px;
    color: {TEXT_PRIMARY};
}}
QMainWindow, QDialog {{ background: {BG_BASE}; }}
QWidget {{ background: transparent; }}

/* ---------- menus ---------- */
QMenuBar {{ background: {BG_PANEL}; border-bottom: 1px solid {BORDER}; padding: 2px; }}
QMenuBar::item {{ padding: 5px 10px; border-radius: 6px; }}
QMenuBar::item:selected {{ background: {BG_RAISED}; }}
QMenu {{ background: {BG_PANEL}; border: 1px solid {BORDER}; border-radius: 8px; padding: 4px; }}
QMenu::item {{ padding: 6px 24px; border-radius: 6px; }}
QMenu::item:selected {{ background: {ACCENT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}

/* ---------- splitters ---------- */
QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 2px; }}
QSplitter::handle:vertical {{ height: 2px; }}

/* ---------- sidebar ---------- */
#sidebar {{ background: {BG_PANEL}; border-right: 1px solid {BORDER}; }}
#sidebarTitle {{ font-size: 11px; font-weight: 600; color: {TEXT_MUTED}; letter-spacing: 1px; padding: 4px 2px; }}
QListView, QTreeView {{
    background: {BG_PANEL}; border: none; outline: 0;
    alternate-background-color: {BG_PANEL};
}}
QListView::item, QTreeView::item {{ padding: 3px 4px; border-radius: 5px; }}
QListView::item:selected, QTreeView::item:selected {{ background: #1f3b63; }}
QListView::item:hover, QTreeView::item:hover {{ background: {BG_RAISED}; }}
QHeaderView::section {{ background: {BG_PANEL}; border: none; padding: 4px; color: {TEXT_MUTED}; }}

/* ---------- buttons ---------- */
QPushButton {{
    background: {BG_RAISED}; border: 1px solid {BORDER}; border-radius: 7px;
    padding: 6px 14px;
}}
QPushButton:hover {{ border-color: {BORDER_LIGHT}; background: #21262d; }}
QPushButton:pressed {{ background: #1a1f26; }}
QPushButton:disabled {{ color: {TEXT_MUTED}; background: {BG_PANEL}; }}
QPushButton#primaryBtn {{ background: #238636; border-color: #2ea043; font-weight: 600; }}
QPushButton#primaryBtn:hover {{ background: #2ea043; }}
QPushButton#dangerBtn {{ background: #6e2325; border-color: {RED}; }}
QPushButton#accentBtn {{ background: #1f6feb; border-color: {ACCENT}; }}

/* ---------- inputs ---------- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {BG_INPUT}; border: 1px solid {BORDER}; border-radius: 7px; padding: 5px 8px;
    selection-background-color: #1f6feb;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {BG_PANEL}; border: 1px solid {BORDER}; selection-background-color: #1f6feb; }}

/* ---------- tabs ---------- */
QTabWidget::pane {{ border: 1px solid {BORDER}; background: {BG_BASE}; }}
QTabBar::tab {{
    background: {BG_PANEL}; border: 1px solid {BORDER}; border-bottom: none;
    padding: 6px 14px; margin-right: 2px; border-top-left-radius: 7px; border-top-right-radius: 7px;
    color: {TEXT_MUTED};
}}
QTabBar::tab:selected {{ background: {BG_BASE}; color: {TEXT_PRIMARY}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover:!selected {{ background: {BG_RAISED}; }}

/* ---------- scrollbars ---------- */
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #2d333b; border-radius: 5px; min-height: 24px; border: 2px solid {BG_BASE}; }}
QScrollBar::handle:vertical:hover {{ background: #3d444d; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: #2d333b; border-radius: 5px; min-width: 24px; border: 2px solid {BG_BASE}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---------- progress bars ---------- */
QProgressBar {{ background: {BG_INPUT}; border: 1px solid {BORDER}; border-radius: 6px; height: 12px; text-align: center; font-size: 10px; color: {TEXT_MUTED}; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
QProgressBar#warnBar::chunk {{ background: {YELLOW}; }}
QProgressBar#critBar::chunk {{ background: {RED}; }}

/* ---------- status bar ---------- */
QStatusBar {{ background: {BG_PANEL}; border-top: 1px solid {BORDER}; color: {TEXT_MUTED}; }}
QStatusBar QLabel {{ color: {TEXT_MUTED}; padding: 0 6px; }}

/* ---------- group boxes / labels ---------- */
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 8px; margin-top: 12px; padding-top: 6px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {TEXT_MUTED}; }}
QLabel#mutedLabel {{ color: {TEXT_MUTED}; font-size: 12px; }}
QLabel#warningBanner {{
    background: #3a2a0f; color: #ffd966; border: 1px solid {YELLOW};
    border-radius: 7px; padding: 8px 12px; font-weight: 600;
}}
QLabel#errorBanner {{
    background: #33141a; color: #ff9b95; border: 1px solid {RED};
    border-radius: 7px; padding: 8px 12px; font-weight: 600;
}}
QLabel#toolCardTitle {{ font-weight: 600; font-size: 12px; }}
QToolTip {{ background: {BG_PANEL}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER}; padding: 4px 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 15px; height: 15px; border: 1px solid {BORDER_LIGHT}; border-radius: 4px; background: {BG_INPUT}; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QDockWidget::title {{ background: {BG_PANEL}; padding: 5px; border-bottom: 1px solid {BORDER}; }}
"""


def accent_color() -> QColor:
    return QColor(ACCENT)

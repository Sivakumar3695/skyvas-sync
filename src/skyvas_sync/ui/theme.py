"""Application-wide Qt stylesheet.

Keeping styles in one place makes it easy to tweak the look without touching
individual view files.  Apply once with ``QApplication.setStyleSheet(APP_QSS)``.
"""

from __future__ import annotations

# Colour palette ──────────────────────────────────────────────────────────────
_BG          = "#FFFFFF"        # window / widget background
_BG_ALT      = "#F5F7FA"        # subtle alternate rows, input areas
_BORDER      = "#DDE1E7"        # neutral border
_TEXT        = "#1A1A2E"        # primary text
_TEXT_MUTED  = "#6B7280"        # secondary / hint text

_ACCENT      = "#4A6FE3"        # primary action colour (blue)
_ACCENT_DARK = "#3558C8"        # hover / pressed state
_ACCENT_TEXT = "#FFFFFF"        # text on accent background

_DANGER      = "#E53935"        # destructive / logout
_DANGER_DARK = "#C62828"
_SUCCESS     = "#2E7D32"        # success indicator

_RADIUS      = "6px"
_RADIUS_SM   = "4px"

# ─────────────────────────────────────────────────────────────────────────────
APP_QSS: str = f"""

/* ── Global ────────────────────────────────────────────────────────────── */
QWidget {{
    background-color: {_BG};
    color: {_TEXT};
    font-family: "Segoe UI", "Inter", "Helvetica Neue", Sans-Serif;
    font-size: 15px;
}}

QMainWindow {{
    background-color: {_BG};
}}

/* ── Buttons ────────────────────────────────────────────────────────────── */
QPushButton {{
    background-color: {_ACCENT};
    color: {_ACCENT_TEXT};
    border: none;
    border-radius: {_RADIUS};
    padding: 6px 16px;
    font-weight: 600;
    min-height: 30px;
}}
QPushButton:hover {{
    background-color: {_ACCENT_DARK};
}}
QPushButton:pressed {{
    background-color: {_ACCENT_DARK};
    padding-top: 7px;
    padding-bottom: 5px;
}}
QPushButton:disabled {{
    background-color: {_BORDER};
    color: {_TEXT_MUTED};
}}

/* Secondary (outline) buttons — applied via property or object-name */
QPushButton[styleClass="secondary"] {{
    background-color: transparent;
    color: {_ACCENT};
    border: 1.5px solid {_ACCENT};
}}
QPushButton[styleClass="secondary"]:hover {{
    background-color: #EEF2FC;
}}
QPushButton[styleClass="secondary"]:disabled {{
    color: {_TEXT_MUTED};
    border-color: {_BORDER};
}}

/* Danger / Logout buttons */
QPushButton#logoutBtn, QPushButton[styleClass="danger"] {{
    background-color: transparent;
    color: {_DANGER};
    border: 1.5px solid {_DANGER};
}}
QPushButton#logoutBtn:hover, QPushButton[styleClass="danger"]:hover {{
    background-color: #FEECEC;
}}

/* Ghost / icon-only buttons (remove ✕, clear ✕) */
QPushButton[styleClass="ghost"] {{
    background-color: transparent;
    color: {_TEXT_MUTED};
    border: none;
    padding: 0;
    font-size: 15px;
    min-height: 0;
    font-weight: normal;
}}
QPushButton[styleClass="ghost"]:hover {{
    color: {_DANGER};
    background-color: transparent;
}}

/* ── Labels ─────────────────────────────────────────────────────────────── */
QLabel {{
    background-color: transparent;
    color: {_TEXT};
}}

/* ── Table ──────────────────────────────────────────────────────────────── */
QTableWidget {{
    background-color: {_BG};
    border: 1px solid {_BORDER};
    border-radius: {_RADIUS};
    gridline-color: {_BORDER};
    selection-background-color: #EEF2FC;
    selection-color: {_TEXT};
    outline: none;
}}
QTableWidget::item {{
    padding: 6px 8px;
    border: none;
}}
QTableWidget::item:selected {{
    background-color: #EEF2FC;
    color: {_TEXT};
}}
QHeaderView::section {{
    background-color: {_BG_ALT};
    color: {_TEXT_MUTED};
    font-weight: 600;
    font-size: 14px;
    border: none;
    border-bottom: 1px solid {_BORDER};
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
QTableWidget QTableCornerButton::section {{
    background-color: {_BG_ALT};
    border: none;
    border-bottom: 1px solid {_BORDER};
}}

/* ── Tabs ───────────────────────────────────────────────────────────────── */
QTabWidget::pane {{
    border: 1px solid {_BORDER};
    border-radius: {_RADIUS};
    background: {_BG};
    top: -1px;
}}
QTabBar::tab {{
    background: {_BG_ALT};
    color: {_TEXT_MUTED};
    border: 1px solid {_BORDER};
    border-bottom: none;
    border-top-left-radius: {_RADIUS_SM};
    border-top-right-radius: {_RADIUS_SM};
    padding: 6px 18px;
    min-width: 80px;
    font-weight: 500;
}}
QTabBar::tab:selected {{
    background: {_BG};
    color: {_ACCENT};
    font-weight: 600;
    border-bottom: 2px solid {_ACCENT};
}}
QTabBar::tab:hover:!selected {{
    background: #EEF2FC;
    color: {_TEXT};
}}

/* ── Progress bar ───────────────────────────────────────────────────────── */
QProgressBar {{
    background-color: {_BG_ALT};
    border: 1px solid {_BORDER};
    border-radius: {_RADIUS_SM};
    height: 10px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background-color: {_ACCENT};
    border-radius: {_RADIUS_SM};
}}

/* ── Text / log areas ───────────────────────────────────────────────────── */
QTextEdit {{
    background-color: {_BG_ALT};
    border: 1px solid {_BORDER};
    border-radius: {_RADIUS_SM};
    color: {_TEXT};
    font-size: 13px;
    font-family: "Consolas", "Courier New", monospace;
    padding: 4px;
}}

/* ── Scroll bars ────────────────────────────────────────────────────────── */
QScrollBar:vertical {{
    background: {_BG_ALT};
    width: 8px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {_BORDER};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background: #B0B7C3;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: {_BG_ALT};
    height: 8px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {_BORDER};
    border-radius: 4px;
    min-width: 20px;
}}
QScrollBar::handle:horizontal:hover {{
    background: #B0B7C3;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ── Stacked widget ─────────────────────────────────────────────────────── */
QStackedWidget {{
    background-color: {_BG};
}}

"""

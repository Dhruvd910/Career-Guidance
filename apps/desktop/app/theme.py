"""Central color tokens + a global Qt stylesheet, mirroring the palette used in the
(still-present) web app's globals.css so both surfaces feel like the same product."""

from app.config import ASSETS_DIR

CHEVRON = (ASSETS_DIR / "icons" / "chevron-down.svg").as_posix()

BACKGROUND = "#eef4fd"
CARD = "#ffffff"
CARD_BORDER = "#dde6f3"
FOREGROUND = "#0f1f3d"
MUTED = "#5f6f8f"
PRIMARY = "#2563eb"
PRIMARY_HOVER = "#1d4ed8"
PRIMARY_SOFT = "#e8f0fe"
PRIMARY_FOREGROUND = "#ffffff"
CHOICE_BG = "#f1f5fb"
# Poppins is bundled (assets/fonts); it has no Devanagari, so Hindi falls through to Noto.
FONT_FAMILY = '"Poppins", "Noto Sans Devanagari", "Noto Sans", "DejaVu Sans"'
HAND_FONT = "Caveat"

# The dashboard's five tiles, as in the design: (tile background, icon circle, icon colour).
TILE_COLORS = {
    "blue": ("#dbeafe", "#2563eb", "#ffffff"),
    "green": ("#d1fae5", "#10b981", "#ffffff"),
    "red": ("#fee2e2", "#ef4444", "#ffffff"),
    "purple": ("#ede9fe", "#7c3aed", "#ffffff"),
    "yellow": ("#fef3c7", "#f59e0b", "#ffffff"),
}

CHANCE_HIGH_BG = "#dcfce7"
CHANCE_HIGH_FG = "#15803d"
CHANCE_POSSIBLE_BG = "#fef9c3"
CHANCE_POSSIBLE_FG = "#a16207"
CHANCE_AMBITIOUS_BG = "#fee2e2"
CHANCE_AMBITIOUS_FG = "#b91c1c"
DEMO_BADGE_BG = "#fef3c7"
DEMO_BADGE_FG = "#92400e"

CHANCE_COLORS = {
    "high_probability": (CHANCE_HIGH_BG, CHANCE_HIGH_FG),
    "possible": (CHANCE_POSSIBLE_BG, CHANCE_POSSIBLE_FG),
    "ambitious": (CHANCE_AMBITIOUS_BG, CHANCE_AMBITIOUS_FG),
}

STYLESHEET = f"""
/* Transparent by default, so a label inside a white card is white too; the page colour
   comes from the window. Pop-ups (dropdown lists, the calendar) get their own below. */
QWidget {{
    background: transparent;
    color: {FOREGROUND};
    font-family: {FONT_FAMILY};
    font-size: 14px;
}}

QMainWindow {{
    background: {BACKGROUND};
}}
QAbstractItemView, QCalendarWidget QWidget {{
    background: {CARD};
    selection-background-color: {PRIMARY_SOFT};
    selection-color: {FOREGROUND};
}}

#Sidebar {{
    background: {CARD};
    border-right: 1px solid {CARD_BORDER};
}}

#SidebarButton {{
    text-align: left;
    padding: 10px 16px;
    border: none;
    border-radius: 8px;
    background: transparent;
    color: {MUTED};
    font-weight: 500;
}}
#SidebarButton:hover {{
    background: {BACKGROUND};
}}
#SidebarButton[active="true"] {{
    background: {PRIMARY};
    color: {PRIMARY_FOREGROUND};
}}

QFrame#Card {{
    background: {CARD};
    border: 1px solid {CARD_BORDER};
    border-radius: 16px;
}}

QPushButton {{
    padding: 8px 16px;
    border-radius: 10px;
    font-weight: 600;
    background: {PRIMARY};
    color: {PRIMARY_FOREGROUND};
    border: none;
}}
QPushButton:hover {{ background: {PRIMARY_HOVER}; }}
QPushButton:pressed {{ background: #1e40af; }}
QPushButton:disabled {{ background: #9dbcf5; color: #f1f6ff; }}
QPushButton[variant="secondary"] {{
    background: {BACKGROUND};
    color: {FOREGROUND};
    border: 1px solid {CARD_BORDER};
}}
QPushButton[variant="secondary"]:hover {{ background: {CARD_BORDER}; }}
/* A secondary button used as a tab: the selected one is filled. */
QPushButton[variant="secondary"]:checked {{ background: {PRIMARY}; color: {PRIMARY_FOREGROUND}; border-color: {PRIMARY}; }}

QCheckBox {{ spacing: 10px; padding: 4px 0; }}
QCheckBox::indicator {{
    width: 24px; height: 24px; border: 2px solid {CARD_BORDER}; border-radius: 6px; background: white;
}}
QCheckBox::indicator:checked {{ background: {PRIMARY}; border-color: {PRIMARY}; }}
QPushButton[variant="ghost"] {{
    background: transparent;
    color: {PRIMARY};
    border: none;
    font-weight: 500;
}}
QPushButton[variant="ghost"]:hover {{ text-decoration: underline; }}
QPushButton[variant="danger"] {{
    background: {CHANCE_AMBITIOUS_FG};
    color: white;
}}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {{
    padding: 8px 10px;
    border-radius: 10px;
    border: 1px solid {CARD_BORDER};
    background: {CARD};
    color: {FOREGROUND};
}}
QComboBox::drop-down {{
    border: none;
    width: 28px;
}}
QComboBox::down-arrow {{
    image: url("{CHEVRON}");
    width: 14px;
    height: 14px;
}}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QDateEdit::up-button, QDateEdit::down-button {{
    border: none;
    width: 0;
}}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus {{
    border: 1px solid {PRIMARY};
}}

QLabel[role="heading"] {{
    font-size: 19px;
    font-weight: 700;
    color: {FOREGROUND};
}}
QLabel[role="subtitle"] {{
    color: {MUTED};
}}
QLabel[role="muted"] {{
    color: {MUTED};
    font-size: 12px;
}}
QLabel[role="error"] {{
    background: {CHANCE_AMBITIOUS_BG};
    color: {CHANCE_AMBITIOUS_FG};
    padding: 8px 12px;
    border-radius: 8px;
}}
QLabel[role="demo-badge"] {{
    background: {DEMO_BADGE_BG};
    color: {DEMO_BADGE_FG};
    font-weight: 700;
    font-size: 10px;
    padding: 2px 8px;
    border-radius: 4px;
}}
QLabel[role="chance-badge"] {{
    font-weight: 700;
    font-size: 11px;
    padding: 3px 10px;
    border-radius: 10px;
}}

QTabWidget::pane {{
    border: 1px solid {CARD_BORDER};
    border-radius: 8px;
    top: -1px;
}}
QTabBar::tab {{
    padding: 8px 14px;
    margin-right: 2px;
    color: {MUTED};
}}
QTabBar::tab:selected {{
    color: {PRIMARY};
    font-weight: 600;
    border-bottom: 2px solid {PRIMARY};
}}

QScrollArea {{ border: none; }}
/* Fat enough to hit with a finger, and always visible so it's clear a page scrolls. */
QScrollBar:vertical {{
    background: transparent;
    width: 14px;
    margin: 2px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 14px;
    margin: 2px;
}}
QScrollBar::handle {{
    background: #c3cad8;
    border-radius: 5px;
    min-height: 40px;
    min-width: 40px;
}}
QScrollBar::handle:hover {{ background: #9aa5b8; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QTableWidget {{
    background: {CARD};
    border: 1px solid {CARD_BORDER};
    border-radius: 8px;
    gridline-color: {CARD_BORDER};
}}
QHeaderView::section {{
    background: {BACKGROUND};
    color: {MUTED};
    padding: 6px;
    border: none;
    font-weight: 600;
}}

/* ---- top bar: Back, logo, title or progress, MAYA's wake button, Exit ---- */
QPushButton#BackButton {{
    background: {CARD};
    color: {FOREGROUND};
    border: 1px solid {CARD_BORDER};
    border-radius: 10px;
    padding: 6px 14px;
    font-weight: 500;
}}
QPushButton#BackButton:hover {{ background: {PRIMARY_SOFT}; }}
QPushButton#BackButton:disabled {{ color: #b8c2d6; }}
QLabel#HeaderTitle {{
    font-size: 17px;
    font-weight: 700;
}}
QLabel#HeaderWelcome {{
    font-size: 18px;
    font-weight: 500;
}}
QLabel#Clock {{
    font-size: 11px;
    font-weight: 600;
    color: {FOREGROUND};
}}
QLabel#WakeHint {{
    color: {MUTED};
    font-size: 11px;
}}
QLabel#ProgressText {{
    color: {FOREGROUND};
    font-size: 11px;
    font-weight: 500;
}}
QLabel#StepPill {{
    background: {CARD};
    border: 1px solid {CARD_BORDER};
    border-radius: 10px;
    padding: 4px 12px;
    font-size: 11px;
    font-weight: 500;
}}
QPushButton#WakeButton {{
    background: {PRIMARY_SOFT};
    color: {PRIMARY};
    border: 1px solid #c5d7fb;
    border-radius: 17px;  /* Qt drops the rounding entirely past half the height */
    min-height: 34px;
    max-height: 34px;
    padding: 0 14px 0 3px;
    font-weight: 700;
}}
QPushButton#WakeButton:hover {{ background: #dbe7fd; }}
QPushButton#IconButton {{
    background: transparent;
    border: none;
    padding: 4px;
}}
QPushButton#IconButton:pressed {{ background: {PRIMARY_SOFT}; border-radius: 18px; }}

/* ---- big pill buttons from the design ---- */
QPushButton[variant="hero"] {{
    font-size: 17px;
    font-weight: 600;
    border-radius: 24px;
    padding: 10px 30px;
}}
QPushButton[variant="next"] {{
    font-size: 15px;
    font-weight: 600;
    border-radius: 12px;
    padding: 9px 22px;
}}
QPushButton[variant="soft"] {{
    background: {PRIMARY_SOFT};
    color: {FOREGROUND};
    border: 1px solid #d3e0f7;
    font-size: 16px;
    border-radius: 12px;
    padding: 12px 18px;
}}
QPushButton[variant="soft"]:hover {{ background: #dbe7fd; }}
QPushButton[variant="pill"] {{
    background: {CARD};
    color: {PRIMARY};
    border: 1px solid {CARD_BORDER};
    border-radius: 23px;
    padding: 5px 18px 5px 6px;
    font-weight: 500;
    font-size: 13px;
}}
QPushButton[variant="pill"]:hover {{ background: {PRIMARY_SOFT}; }}
QPushButton[variant="pill"]:disabled {{ color: #9aa9c4; }}
QPushButton[variant="link"] {{
    background: transparent;
    color: {PRIMARY};
    border: none;
    padding: 2px 6px;
    font-weight: 500;
    font-size: 12px;
}}

/* ---- setup questions ---- */
QPushButton[variant="choice"] {{
    background: {CHOICE_BG};
    color: {FOREGROUND};
    border: 1px solid {CARD_BORDER};
    border-radius: 10px;
    font-size: 15px;
    font-weight: 600;
}}
QPushButton[variant="choice"]:hover {{ background: {PRIMARY_SOFT}; }}
QPushButton[variant="choice"][selected="true"] {{
    background: {PRIMARY};
    color: {PRIMARY_FOREGROUND};
    border: 1px solid {PRIMARY};
}}
QLineEdit[variant="big"] {{
    font-size: 17px;
    font-weight: 500;
    padding: 10px 14px;
    border-radius: 12px;
}}
QLabel[role="question"] {{
    font-size: 19px;
    font-weight: 700;
}}
QLabel[role="hint"] {{
    color: {MUTED};
    font-size: 12px;
}}
QLabel[role="review-key"] {{ color: {FOREGROUND}; font-size: 12px; }}
QLabel[role="review-value"] {{ color: {FOREGROUND}; font-size: 12px; font-weight: 600; }}
QFrame#ReviewRow {{ border: none; border-bottom: 1px solid #e8eef8; background: transparent; }}

/* ---- dashboard tiles and ask bar ---- */
QFrame#AskBar {{
    background: {CARD};
    border: 1px solid {CARD_BORDER};
    border-radius: 14px;
}}
QFrame#AskBar QLineEdit {{
    border: none;
    background: transparent;
    font-size: 12px;
    color: {FOREGROUND};
}}
QPushButton#SendButton {{
    background: {PRIMARY};
    border-radius: 12px;
    padding: 0;
}}
QPushButton#MicButton {{
    background: {PRIMARY_SOFT};
    border-radius: 12px;
    padding: 0;
}}

/* ---- practice papers ---- */
QPushButton[variant="option"] {{
    background: {CARD};
    color: {FOREGROUND};
    border: 1px solid {CARD_BORDER};
    text-align: left;
    padding: 10px 14px;
    font-weight: 500;
    font-size: 15px;
}}
QPushButton[variant="option"]:hover {{ background: {PRIMARY_SOFT}; }}
QPushButton[variant="option"][selected="true"] {{
    background: {PRIMARY_SOFT};
    border: 2px solid {PRIMARY};
    color: {PRIMARY};
    font-weight: 700;
}}
QLabel#TestClock {{
    background: {PRIMARY_SOFT};
    color: {PRIMARY};
    font-weight: 700;
    padding: 4px 10px;
    border-radius: 8px;
}}
QLabel#TestClock[warning="true"] {{
    background: {CHANCE_AMBITIOUS_BG};
    color: {CHANCE_AMBITIOUS_FG};
}}
QPushButton#PaletteKey {{
    background: {CARD};
    color: {MUTED};
    border: 1px solid {CARD_BORDER};
    border-radius: 6px;
    font-weight: 600;
    padding: 0;
}}
QPushButton#PaletteKey[state="answered"] {{
    background: {CHANCE_HIGH_BG};
    color: {CHANCE_HIGH_FG};
    border: 1px solid {CHANCE_HIGH_FG};
}}
QPushButton#PaletteKey[state="current"] {{
    background: {PRIMARY};
    color: {PRIMARY_FOREGROUND};
    border: 1px solid {PRIMARY};
}}

QLabel#PredictionSummary {{
    background: {PRIMARY_SOFT};
    color: {FOREGROUND};
    border: 1px solid #c7d2fe;
    border-radius: 10px;
    padding: 10px 12px;
    font-weight: 600;
}}
QProgressBar {{
    background: {CARD_BORDER};
    border: none;
    border-radius: 3px;
}}
QProgressBar::chunk {{
    background: {PRIMARY};
    border-radius: 3px;
}}

/* ---- on-screen keyboard ---- */
#Osk {{
    background: #d7dbe3;
    border-top: 1px solid #b8bfcc;
}}
QPushButton#OskKey {{
    background: #ffffff;
    color: {FOREGROUND};
    border: none;
    border-bottom: 2px solid #aab2c0;
    border-radius: 7px;
    font-family: "DejaVu Sans";
    font-size: 18px;
    font-weight: 500;
    padding: 0px;
}}
QPushButton#OskKey:pressed {{ background: #c7d2fe; }}
QPushButton#OskKey[special="true"] {{ background: #b9c1ce; font-size: 16px; }}
QPushButton#OskKey[special="true"]:pressed {{ background: #9aa5b8; }}
QPushButton#OskKey[active="true"] {{ background: {PRIMARY}; color: {PRIMARY_FOREGROUND}; }}
QPushButton#OskKey[listening="true"] {{ background: #dc2626; }}

/* ---- MAYA voice status ---- */
QLabel#MayaStatusText {{
    color: {PRIMARY};
    font-weight: 600;
}}

QSlider::groove:horizontal {{
    height: 6px;
    background: {CARD_BORDER};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {PRIMARY};
    width: 16px;
    margin: -6px 0;
    border-radius: 8px;
}}
QSlider::sub-page:horizontal {{
    background: {PRIMARY};
    border-radius: 3px;
}}
"""


def chance_style(band: str) -> str:
    bg, fg = CHANCE_COLORS.get(band, CHANCE_COLORS["possible"])
    return f"background:{bg}; color:{fg}; font-weight:700; font-size:11px; padding:3px 10px; border-radius:10px;"

"""The ONE visual theme of the admin desktop (light, professional).

Why it exists: on Windows with dark mode, Qt's native style hands dialogs a
dark system palette while the old style sheet painted text dark — dark text
on a near-black dialog. The theme now owns everything:
- Fusion style (identical rendering on every OS, ignores the system dark mode);
- an explicit light QPalette (dialogs, menus, combo popups, message boxes,
  tooltips inherit it);
- one style sheet generated from the tokens below.

Every colour and font size used by the UI comes from TOKENS / TYPE; pages
and dialogs never define their own. Text / background pairs are checked
against WCAG 2.1 contrast (tests/test_theme.py): 4.5:1 for text, 3:1 for
field borders, focus ring and other UI boundaries.
"""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

ASSETS = Path(__file__).resolve().parent / "assets"


@dataclass(frozen=True)
class Tokens:
    # Surfaces
    background: str = "#F3F5F8"  # application background
    panel: str = "#FFFFFF"  # header, dialogs, toolbars
    card: str = "#FFFFFF"
    field: str = "#FFFFFF"
    field_disabled: str = "#EEF1F5"
    row_alt: str = "#F7F9FC"
    # Brand / actions
    primary: str = "#1D4ED8"
    primary_hover: str = "#1E40AF"
    primary_pressed: str = "#1E3A8A"
    primary_soft: str = "#DBEAFE"  # table selection, focus halo
    on_primary: str = "#FFFFFF"
    danger: str = "#B91C1C"
    danger_hover: str = "#991B1B"
    danger_pressed: str = "#7F1D1D"
    secondary_hover: str = "#EEF2F7"
    secondary_pressed: str = "#E2E8F0"
    disabled_fill: str = "#E2E8F0"
    # Text
    text: str = "#111827"
    text_secondary: str = "#4B5563"
    placeholder: str = "#6B7280"
    text_disabled: str = "#5B6573"
    # Lines
    border: str = "#D5DCE5"  # decorative separators
    field_border: str = "#7B8794"  # input / button outlines (≥ 3:1)
    focus: str = "#1D4ED8"
    # Feedback (foreground on its own soft background)
    error: str = "#B91C1C"
    error_bg: str = "#FEF2F2"
    success: str = "#166534"
    success_bg: str = "#F0FDF4"
    warning: str = "#92400E"
    warning_bg: str = "#FFFBEB"
    info: str = "#1E40AF"
    info_bg: str = "#EFF6FF"
    # Sidebar (dark navy, light text)
    sidebar: str = "#0F2747"
    sidebar_text: str = "#E5ECF6"
    sidebar_muted: str = "#A9B8CC"  # sections, "bientôt" entries
    sidebar_hover: str = "#1A3A66"
    sidebar_selected: str = "#1D4ED8"
    # Charts: few colours, each >= 3:1 on a white card (graphical objects).
    chart_1: str = "#1D4ED8"  # main series (= primary blue)
    chart_2: str = "#0F766E"  # second series (teal)
    chart_3: str = "#B45309"  # third series / attention (amber)
    chart_soft: str = "#BFDBFE"  # bar under the cursor, area under a line
    chart_grid: str = "#E5E9F0"  # gridlines (decorative)


TOKENS = Tokens()


@dataclass(frozen=True)
class TypeScale:
    family: str = "Segoe UI"
    base: float = 10.5  # normal text, fields, table
    small: float = 9.5  # help, secondary
    label: float = 10.0  # form labels (semibold)
    button: float = 10.0
    section: float = 8.5  # sidebar section headers (uppercase, spaced)
    dialog_title: float = 14.0
    page_title: float = 18.0
    app_title: float = 20.0  # login
    metric: float = 22.0  # dashboard numbers


TYPE = TypeScale()


# --- contrast (WCAG 2.1) -------------------------------------------------------


def _luminance(hex_color):
    color = QColor(hex_color)
    channels = []
    for value in (color.redF(), color.greenF(), color.blueF()):
        channels.append(value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(foreground, background):
    lighter, darker = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


# --- palette / style sheet ---------------------------------------------------------


def build_palette(t=TOKENS):
    palette = QPalette()
    roles = {
        QPalette.Window: t.background,
        QPalette.WindowText: t.text,
        QPalette.Base: t.field,
        QPalette.AlternateBase: t.row_alt,
        QPalette.Text: t.text,
        QPalette.PlaceholderText: t.placeholder,
        QPalette.Button: t.panel,
        QPalette.ButtonText: t.text,
        QPalette.BrightText: t.on_primary,
        QPalette.Highlight: t.primary,
        QPalette.HighlightedText: t.on_primary,
        QPalette.ToolTipBase: t.text,
        QPalette.ToolTipText: t.panel,
        QPalette.Link: t.primary,
        QPalette.Light: t.panel,
        QPalette.Midlight: t.row_alt,
        QPalette.Mid: t.border,
        QPalette.Dark: t.field_border,
        QPalette.Shadow: t.text_secondary,
    }
    for role, value in roles.items():
        palette.setColor(QPalette.All, role, QColor(value))
    for role, value in {
        QPalette.WindowText: t.text_disabled,
        QPalette.Text: t.text_disabled,
        QPalette.ButtonText: t.text_disabled,
        QPalette.Base: t.field_disabled,
    }.items():
        palette.setColor(QPalette.Disabled, role, QColor(value))
    return palette


def _asset(name):
    return (ASSETS / name).as_posix()


def build_stylesheet(t=TOKENS, s=TYPE):
    return f"""
* {{ font-family: "{s.family}", "Noto Sans", "Helvetica Neue", sans-serif; }}
QWidget {{ font-size: {s.base}pt; color: {t.text}; }}
QMainWindow, #page, #loginBackground {{ background: {t.background}; }}
QDialog, QMessageBox {{ background: {t.panel}; }}
#dialogContent, #dialogHeader {{ background: {t.panel}; }}
#dialogScroll {{ background: {t.panel}; border: none; }}
#dialogFooter {{ background: {t.panel}; border-top: 1px solid {t.border}; }}
#dashboardContent {{ background: {t.background}; }}
QLabel {{ background: transparent; }}

/* ---------- typography roles ---------- */
#appTitle {{ font-size: {s.app_title}pt; font-weight: 600; color: {t.text}; }}
#pageTitle {{ font-size: {s.page_title}pt; font-weight: 600; color: {t.text}; }}
#dialogTitle {{ font-size: {s.dialog_title}pt; font-weight: 600; color: {t.text}; }}
#subtitle, #muted {{ color: {t.text_secondary}; }}
#fieldLabel {{ font-size: {s.label}pt; font-weight: 600; color: {t.text}; }}
#required {{ color: {t.error}; font-weight: 600; }}
#help {{ font-size: {s.small}pt; color: {t.text_secondary}; }}
#fieldError {{ font-size: {s.small}pt; color: {t.error}; }}
#countLabel {{ color: {t.text_secondary}; }}

/* ---------- sidebar ---------- */
#sidebar {{ background: {t.sidebar}; border: none; }}
#brand {{ color: #FFFFFF; font-size: 13pt; font-weight: 600; padding: 18px 18px 2px 18px; }}
#brandSub {{ color: {t.sidebar_muted}; font-size: {s.small}pt; padding: 0 18px 14px 18px; }}
#sidebar QListWidget {{ background: transparent; border: none; outline: none; color: {t.sidebar_text}; }}
/* no colour on ::item: per-entry colours (muted sections, "Bientôt") must apply */
#sidebar QListWidget::item {{ padding: 9px 12px; margin: 1px 10px; border-radius: 6px;
    border-left: 3px solid transparent; }}
#sidebar QListWidget::item:hover {{ background: {t.sidebar_hover}; }}
#sidebar QListWidget::item:selected {{ background: {t.sidebar_selected}; color: #FFFFFF;
    border-left: 3px solid #FFFFFF; font-weight: 600; }}

/* ---------- header ---------- */
#header {{ background: {t.panel}; border-bottom: 1px solid {t.border}; }}
#schoolName {{ font-size: 13pt; font-weight: 600; color: {t.text}; }}
#schoolCode {{ color: {t.info}; background: {t.info_bg}; border: 1px solid {t.primary_soft};
    border-radius: 10px; padding: 2px 10px; font-size: {s.small}pt; font-weight: 600; }}
#userName {{ font-weight: 600; color: {t.text}; }}
#userRole {{ color: {t.text_secondary}; font-size: {s.small}pt; }}
#avatar {{ background: {t.primary}; color: {t.on_primary}; border-radius: 18px; font-weight: 600; }}

/* ---------- cards ---------- */
#card {{ background: {t.card}; border: 1px solid {t.border}; border-radius: 10px; }}
#cardLabel {{ color: {t.text_secondary}; font-weight: 600; }}
#cardValue {{ font-size: {s.metric}pt; font-weight: 600; color: {t.text}; }}
#cardError {{ font-size: 13pt; font-weight: 600; color: {t.warning}; }}
#emptyState {{ color: {t.text_secondary}; padding: 24px; }}
#sectionTitle {{ font-size: {s.section}pt; font-weight: 600; color: {t.text_secondary}; letter-spacing: 1px;
    padding-top: 10px; border-top: 1px solid {t.border}; }}
#photoFrame {{ background: {t.row_alt}; border: 1px solid {t.border}; border-radius: 8px; color: {t.text_secondary}; }}
#fieldValue {{ color: {t.text}; }}
#chartTitle {{ font-size: 11pt; font-weight: 600; color: {t.text}; }}
#chartState {{ color: {t.text_secondary}; padding: 12px; }}
#chartError {{ color: {t.warning}; padding: 12px; }}
#legend {{ color: {t.text_secondary}; font-size: {s.small}pt; }}
#activityTime {{ color: {t.text_secondary}; font-size: {s.small}pt; }}

/* ---------- banners ---------- */
#banner {{ border-radius: 8px; padding: 10px 14px; border: 1px solid transparent; }}
#banner[kind="error"] {{ background: {t.error_bg}; color: {t.error}; border-color: #FECACA; }}
#banner[kind="warning"] {{ background: {t.warning_bg}; color: {t.warning}; border-color: #FDE68A; }}
#banner[kind="success"] {{ background: {t.success_bg}; color: {t.success}; border-color: #BBF7D0; }}
#banner[kind="info"] {{ background: {t.info_bg}; color: {t.info}; border-color: {t.primary_soft}; }}

/* ---------- buttons: primary / secondary / danger ---------- */
QPushButton {{ font-size: {s.button}pt; font-weight: 600; min-height: 34px; padding: 0 16px; border-radius: 6px;
    background: {t.panel}; color: {t.text}; border: 1px solid {t.field_border}; }}
QPushButton:hover {{ background: {t.secondary_hover}; }}
QPushButton:pressed {{ background: {t.secondary_pressed}; }}
QPushButton:focus {{ border: 2px solid {t.focus}; }}
QPushButton:disabled {{ background: {t.disabled_fill}; color: {t.text_disabled}; border: 1px dashed {t.field_border}; }}
QPushButton[variant="primary"] {{ background: {t.primary}; color: {t.on_primary}; border: 1px solid {t.primary}; }}
QPushButton[variant="primary"]:hover {{ background: {t.primary_hover}; border-color: {t.primary_hover}; }}
QPushButton[variant="primary"]:pressed {{ background: {t.primary_pressed}; }}
QPushButton[variant="primary"]:focus {{ border: 2px solid {t.primary_pressed}; }}
QPushButton[variant="primary"]:disabled {{ background: {t.disabled_fill}; color: {t.text_disabled};
    border: 1px dashed {t.field_border}; }}
QPushButton[variant="danger"] {{ background: {t.panel}; color: {t.danger}; border: 1px solid {t.danger}; }}
QPushButton[variant="danger"]:hover {{ background: {t.error_bg}; }}
QPushButton[variant="danger"]:pressed {{ background: #FEE2E2; }}
QPushButton[variant="danger"]:focus {{ border: 2px solid {t.danger}; }}
QPushButton[variant="danger-solid"] {{ background: {t.danger}; color: {t.on_primary}; border: 1px solid {t.danger}; }}
QPushButton[variant="danger-solid"]:hover {{ background: {t.danger_hover}; }}
QPushButton[variant="danger-solid"]:pressed {{ background: {t.danger_pressed}; }}
QPushButton[variant="danger-solid"]:focus {{ border: 2px solid {t.danger_pressed}; }}
QPushButton[variant="danger"]:disabled, QPushButton[variant="danger-solid"]:disabled {{
    background: {t.disabled_fill}; color: {t.text_disabled}; border: 1px dashed {t.field_border}; }}

/* ---------- inputs ---------- */
QLineEdit, QPlainTextEdit, QComboBox, QDateEdit {{ background: {t.field}; color: {t.text};
    border: 1px solid {t.field_border}; border-radius: 6px; padding: 6px 10px; min-height: 22px;
    selection-background-color: {t.primary};
    selection-color: {t.on_primary}; }}
QLineEdit:hover, QPlainTextEdit:hover, QComboBox:hover, QDateEdit:hover {{ border-color: {t.text_secondary}; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QDateEdit:focus {{ border: 2px solid {t.focus};
    padding: 5px 9px; }}
QLineEdit:read-only {{ background: {t.field_disabled}; color: {t.text_secondary}; }}
QLineEdit:disabled, QComboBox:disabled, QPlainTextEdit:disabled, QDateEdit:disabled {{ background: {t.field_disabled};
    color: {t.text_disabled}; }}
QLineEdit[invalid="true"], QComboBox[invalid="true"] {{ border: 2px solid {t.error}; padding: 5px 9px; }}
QComboBox, QDateEdit {{ padding-right: 30px; }}
QDateEdit::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 28px;
    border: none; border-left: 1px solid {t.border}; }}
QDateEdit::down-arrow {{ image: url("{_asset("chevron-down.svg")}"); width: 12px; height: 12px; }}
QCalendarWidget QWidget {{ alternate-background-color: {t.row_alt}; }}
QCalendarWidget QToolButton {{ color: {t.text}; background: transparent; font-weight: 600; padding: 4px 8px; }}
QCalendarWidget QAbstractItemView {{ selection-background-color: {t.primary}; selection-color: {t.on_primary}; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 28px;
    border: none; border-left: 1px solid {t.border}; }}
QComboBox::down-arrow {{ image: url("{_asset("chevron-down.svg")}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {t.panel}; color: {t.text}; border: 1px solid {t.field_border};
    outline: none; padding: 4px; selection-background-color: {t.primary_soft}; selection-color: {t.text}; }}
QComboBox QAbstractItemView::item {{ min-height: 30px; padding: 4px 8px; }}
QCheckBox {{ spacing: 8px; color: {t.text}; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border: 1px solid {t.field_border}; border-radius: 4px;
    background: {t.field}; }}
QCheckBox::indicator:hover {{ border-color: {t.focus}; }}
QCheckBox::indicator:focus {{ border: 2px solid {t.focus}; }}
QCheckBox::indicator:checked {{ background: {t.primary}; border-color: {t.primary};
    image: url("{_asset("check.svg")}"); }}

/* ---------- tables ---------- */
QTableView {{ background: {t.card}; alternate-background-color: {t.row_alt}; color: {t.text};
    border: 1px solid {t.border}; border-radius: 8px; gridline-color: transparent;
    selection-background-color: {t.primary_soft}; selection-color: {t.text}; }}
QTableView::item {{ padding: 0 10px; border-bottom: 1px solid #EDF1F6; }}
QTableView::item:selected {{ background: {t.primary_soft}; color: {t.text}; }}
QTableView:focus {{ border: 1px solid {t.focus}; }}
QHeaderView::section {{ background: #EEF2F7; color: {t.text}; padding: 8px 10px; border: none;
    border-bottom: 1px solid {t.border}; font-weight: 600; }}

/* ---------- misc ---------- */
QToolTip {{ background: {t.text}; color: #FFFFFF; border: none; padding: 6px 8px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #C3CCD7; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollArea#pageScroll {{ background: transparent; border: none; }}
"""


def apply_theme(app):
    """Install style, palette, font and style sheet on the QApplication."""
    style = QStyleFactory.create("Fusion")
    app.setStyle(style)
    # Once a style sheet is set, Qt wraps the style (QStyleSheetStyle):
    # remember the base style for diagnostics and tests.
    app.setProperty("theme_base_style", style.metaObject().className())
    app.setPalette(build_palette())
    font = QFont(TYPE.family)
    font.setPointSizeF(TYPE.base)
    app.setFont(font)
    app.setStyleSheet(build_stylesheet())


def ensure_app():
    """The running QApplication (created and themed if needed — tests)."""
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app

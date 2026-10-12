"""The visual theme of the admin desktop: light (default) or dark, chosen in
« Mon compte » (Système / Clair / Sombre; desktop.json) — see the end of this module.

Why it exists: on Windows with dark mode, Qt's native style hands dialogs a
dark system palette while the old style sheet painted text dark — dark text
on a near-black dialog. The theme now owns everything:
- Fusion style (identical rendering on every OS, ignores the system dark mode);
- an explicit QPalette from the active tokens (dialogs, menus, combo popups,
  message boxes, tooltips inherit it);
- one style sheet generated from the tokens below.

Every colour and font size used by the UI comes from TOKENS / TYPE; pages
and dialogs never define their own. TOKENS always reads the ACTIVE palette
(LIGHT or DARK), so a colour looked up when painting follows a theme change. Text / background pairs are checked
against WCAG 2.1 contrast (tests/test_theme.py): 4.5:1 for text, 3:1 for
field borders, focus ring and other UI boundaries.
"""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QDate, QLocale, QObject, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QGuiApplication, QPalette, QTextCharFormat
from PySide6.QtWidgets import QApplication, QCalendarWidget, QStyleFactory

ASSETS = Path(__file__).resolve().parent / "assets"


@dataclass(frozen=True)
class Tokens:
    name: str = "light"
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
    # Date picker: weekends keep the usual red, but readable (Qt's default #FF0000 is ~4:1);
    # today = dark blue, bold, underlined text — distinct from the selected day (solid primary
    # tile, white text). (A background on today is not painted: the style sheet owns cell fills.)
    calendar_weekend: str = "#B91C1C"
    calendar_today_text: str = "#1E3A8A"
    # Former literals of the style sheet
    error_border: str = "#FECACA"
    warning_border: str = "#FDE68A"
    success_border: str = "#BBF7D0"
    danger_pressed_bg: str = "#FEE2E2"
    row_line: str = "#EDF1F6"
    header_section: str = "#EEF2F7"
    tooltip_text: str = "#FFFFFF"
    scroll_handle: str = "#C3CCD7"
    # Icons: "" = dark strokes (assets/x.svg), "-dark" = variants drawn for the dark theme.
    icon_suffix: str = ""


LIGHT = Tokens()

# Dark: same roles, light text on slate surfaces; every text / UI pair keeps the
# WCAG ratios of the light theme (tests/test_theme_modes.py). The primary blue is
# lighter (readable as text on a dark panel) and carries DARK text when filled.
DARK = Tokens(
    name="dark",
    background="#111827",
    panel="#1F2937",
    card="#1F2937",
    field="#111827",
    field_disabled="#273244",
    row_alt="#243041",
    primary="#60A5FA",
    primary_hover="#93C5FD",
    primary_pressed="#BFDBFE",
    primary_soft="#1E3A5F",
    on_primary="#0B1220",
    danger="#F87171",
    danger_hover="#FCA5A5",
    danger_pressed="#FECACA",
    secondary_hover="#2B3A4F",
    secondary_pressed="#334155",
    disabled_fill="#273244",
    text="#E5E7EB",
    text_secondary="#AAB4C3",
    placeholder="#94A3B8",
    text_disabled="#8F9BAE",
    border="#334155",
    field_border="#6B7A90",
    focus="#60A5FA",
    error="#FCA5A5",
    error_bg="#3B1418",
    success="#86EFAC",
    success_bg="#12301F",
    warning="#FCD34D",
    warning_bg="#3A2A0B",
    info="#93C5FD",
    info_bg="#172B4A",
    sidebar="#0B1A33",
    sidebar_text="#E5ECF6",
    sidebar_muted="#A9B8CC",
    sidebar_hover="#1A3A66",
    sidebar_selected="#1D4ED8",
    chart_1="#60A5FA",
    chart_2="#2DD4BF",
    chart_3="#FBBF24",
    chart_soft="#1E3A5F",
    chart_grid="#334155",
    calendar_weekend="#FCA5A5",
    calendar_today_text="#93C5FD",
    error_border="#7F1D1D",
    warning_border="#78350F",
    success_border="#14532D",
    danger_pressed_bg="#4C1D1D",
    row_line="#2B3646",
    header_section="#273244",
    tooltip_text="#111827",
    scroll_handle="#4B5563",
    icon_suffix="-dark",
)


class _ActiveTokens:
    """TOKENS: the active palette. Attributes are read at use time, so code
    that looks a colour up when painting / filling a cell follows a switch."""

    def __init__(self, tokens):
        object.__setattr__(self, "_tokens", tokens)

    def __getattr__(self, name):
        return getattr(self._tokens, name)

    def __setattr__(self, name, value):
        raise AttributeError("TOKENS is read only: use set_active_tokens()")

    @property
    def current(self):
        return self._tokens


TOKENS = _ActiveTokens(LIGHT)


def set_active_tokens(tokens):
    object.__setattr__(TOKENS, "_tokens", tokens)


class TokenColours:
    """status -> token NAME, resolved when used: a module-level table of
    status colours that still follows a theme switch."""

    def __init__(self, **names):
        self.names = names

    def get(self, key, default=None):
        name = self.names.get(key)
        return getattr(TOKENS, name) if name else default


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


def _asset(name, t=TOKENS):
    """Icon for the theme `t` (x.svg, or its x-dark.svg variant for the dark theme)."""
    stem, dot, ext = name.rpartition(".")
    themed = ASSETS / f"{stem}{t.icon_suffix}{dot}{ext}"
    return (themed if themed.exists() else ASSETS / name).as_posix()


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
#softwareBrandLogin {{ font-size: {s.app_title}pt; font-weight: 700; color: {t.primary}; }}
#aboutLink {{ background: transparent; border: none; color: {t.sidebar_muted}; text-align: left;
    padding: 6px 22px; font-weight: 400; min-height: 24px; }}
#aboutLink:hover {{ color: #FFFFFF; text-decoration: underline; background: transparent; }}
#aboutLink:focus {{ color: #FFFFFF; border: 1px solid #FFFFFF; }}
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
QTabWidget::pane {{ border: none; background: {t.background}; }}
QTabBar::tab {{ background: transparent; color: {t.text_secondary}; padding: 8px 16px; margin-right: 2px;
    border: none; border-bottom: 3px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: {t.primary}; border-bottom: 3px solid {t.primary}; }}
QTabBar::tab:hover {{ color: {t.text}; }}
QTabBar::tab:focus {{ outline: none; }}
#legendChip {{ border-radius: 4px; padding: 2px 8px; font-size: {s.small}pt; color: {t.text}; }}
#weekLabel {{ font-size: 12pt; font-weight: 600; color: {t.text}; }}
#chartTitle {{ font-size: 11pt; font-weight: 600; color: {t.text}; }}
#chartState {{ color: {t.text_secondary}; padding: 12px; }}
#chartError {{ color: {t.warning}; padding: 12px; }}
#legend {{ color: {t.text_secondary}; font-size: {s.small}pt; }}
#activityTime {{ color: {t.text_secondary}; font-size: {s.small}pt; }}

/* ---------- banners ---------- */
#banner {{ border-radius: 8px; padding: 10px 14px; border: 1px solid transparent; }}
#banner[kind="error"] {{ background: {t.error_bg}; color: {t.error}; border-color: {t.error_border}; }}
#banner[kind="warning"] {{ background: {t.warning_bg}; color: {t.warning}; border-color: {t.warning_border}; }}
#banner[kind="success"] {{ background: {t.success_bg}; color: {t.success}; border-color: {t.success_border}; }}
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
QPushButton[variant="danger"]:pressed {{ background: {t.danger_pressed_bg}; }}
QPushButton[variant="danger"]:focus {{ border: 2px solid {t.danger}; }}
QPushButton[variant="danger-solid"] {{ background: {t.danger}; color: {t.on_primary}; border: 1px solid {t.danger}; }}
QPushButton[variant="danger-solid"]:hover {{ background: {t.danger_hover}; }}
QPushButton[variant="danger-solid"]:pressed {{ background: {t.danger_pressed}; }}
QPushButton[variant="danger-solid"]:focus {{ border: 2px solid {t.danger_pressed}; }}
QPushButton[variant="danger"]:disabled, QPushButton[variant="danger-solid"]:disabled {{
    background: {t.disabled_fill}; color: {t.text_disabled}; border: 1px dashed {t.field_border}; }}

/* ---------- inputs ---------- */
QLineEdit, QPlainTextEdit, QComboBox, QDateEdit, QTimeEdit {{ background: {t.field}; color: {t.text};
    border: 1px solid {t.field_border}; border-radius: 6px; padding: 6px 10px; min-height: 22px;
    selection-background-color: {t.primary};
    selection-color: {t.on_primary}; }}
QLineEdit:hover, QPlainTextEdit:hover, QComboBox:hover, QDateEdit:hover, QTimeEdit:hover {{
    border-color: {t.text_secondary}; }}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QDateEdit:focus, QTimeEdit:focus {{ border: 2px solid {t.focus};
    padding: 5px 9px; }}
QLineEdit:read-only {{ background: {t.field_disabled}; color: {t.text_secondary}; }}
QLineEdit:disabled, QComboBox:disabled, QPlainTextEdit:disabled, QDateEdit:disabled,
QTimeEdit:disabled {{ background: {t.field_disabled};
    color: {t.text_disabled}; }}
QLineEdit[invalid="true"], QComboBox[invalid="true"] {{ border: 2px solid {t.error}; padding: 5px 9px; }}
QComboBox, QDateEdit {{ padding-right: 30px; }}
QDateEdit::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 28px;
    border: none; border-left: 1px solid {t.border}; }}
QDateEdit::down-arrow {{ image: url("{_asset("chevron-down.svg", t)}"); width: 12px; height: 12px; }}
QCalendarWidget QWidget {{ alternate-background-color: {t.row_alt}; }}
/* Fusion paints the navigation bar with QPalette::Highlight (primary blue): own it, light,
   so the month / year buttons (dark text) stay readable. */
QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {t.panel};
    border-bottom: 1px solid {t.border}; }}
QCalendarWidget QToolButton {{ color: {t.text}; background: transparent; font-weight: 600; padding: 4px 8px;
    border: none; border-radius: 6px; }}
QCalendarWidget QToolButton:hover {{ background: {t.secondary_hover}; }}
QCalendarWidget QToolButton:pressed {{ background: {t.secondary_pressed}; }}
QCalendarWidget QToolButton:focus {{ border: 2px solid {t.focus}; }}
QCalendarWidget QToolButton#qt_calendar_prevmonth {{ qproperty-icon: url("{_asset("chevron-left.svg", t)}"); }}
QCalendarWidget QToolButton#qt_calendar_nextmonth {{ qproperty-icon: url("{_asset("chevron-right.svg", t)}"); }}
QCalendarWidget QToolButton::menu-indicator {{ image: none; width: 0; }}
QCalendarWidget QMenu {{ background: {t.panel}; color: {t.text}; border: 1px solid {t.field_border}; }}
QCalendarWidget QMenu::item:selected {{ background: {t.primary_soft}; color: {t.text}; }}
QCalendarWidget QSpinBox {{ background: {t.field}; color: {t.text}; border: 1px solid {t.field_border};
    border-radius: 4px; selection-background-color: {t.primary}; selection-color: {t.on_primary}; }}
QCalendarWidget QAbstractItemView:enabled {{ background: {t.field}; color: {t.text}; outline: none;
    selection-background-color: {t.primary}; selection-color: {t.on_primary}; }}
QCalendarWidget QAbstractItemView:disabled {{ color: {t.text_disabled}; }}
/* The data-table rule below (QTableView::item padding 0 10px + bottom border) must not reach the
   calendar's own table: it elided the day numbers to "…" and hid the weekday header. */
QCalendarWidget QTableView {{ border: none; border-radius: 0; }}
QCalendarWidget QTableView::item {{ padding: 0; border: none; }}
QCalendarWidget QTableView::item:selected {{ background: {t.primary}; color: {t.on_primary}; }}
QComboBox::drop-down {{ subcontrol-origin: padding; subcontrol-position: center right; width: 28px;
    border: none; border-left: 1px solid {t.border}; }}
QComboBox::down-arrow {{ image: url("{_asset("chevron-down.svg", t)}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background: {t.panel}; color: {t.text}; border: 1px solid {t.field_border};
    outline: none; padding: 4px; selection-background-color: {t.primary_soft}; selection-color: {t.text}; }}
QComboBox QAbstractItemView::item {{ min-height: 30px; padding: 4px 8px; }}
QCheckBox {{ spacing: 8px; color: {t.text}; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border: 1px solid {t.field_border}; border-radius: 4px;
    background: {t.field}; }}
QCheckBox::indicator:hover {{ border-color: {t.focus}; }}
QCheckBox::indicator:focus {{ border: 2px solid {t.focus}; }}
QCheckBox::indicator:checked {{ background: {t.primary}; border-color: {t.primary};
    image: url("{_asset("check.svg", t)}"); }}

/* ---------- tables ---------- */
QTableView {{ background: {t.card}; alternate-background-color: {t.row_alt}; color: {t.text};
    border: 1px solid {t.border}; border-radius: 8px; gridline-color: transparent;
    selection-background-color: {t.primary_soft}; selection-color: {t.text}; }}
QTableView::item {{ padding: 0 10px; border-bottom: 1px solid {t.row_line}; }}
QTableView::item:selected {{ background: {t.primary_soft}; color: {t.text}; }}
QTableView:focus {{ border: 1px solid {t.focus}; }}
QHeaderView::section {{ background: {t.header_section}; color: {t.text}; padding: 8px 10px; border: none;
    border-bottom: 1px solid {t.border}; font-weight: 600; }}

/* ---------- misc ---------- */
QToolTip {{ background: {t.text}; color: {t.tooltip_text}; border: none; padding: 6px 8px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t.scroll_handle}; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollArea#pageScroll {{ background: transparent; border: none; }}
"""


def _char_format(foreground, background=None, *, bold=False, underline=False):
    fmt = QTextCharFormat()
    fmt.setForeground(QBrush(QColor(foreground)))
    if background:
        fmt.setBackground(QBrush(QColor(background)))
    if bold:
        fmt.setFontWeight(QFont.Bold)
    fmt.setFontUnderline(underline)
    return fmt


def style_calendar(calendar: QCalendarWidget, t=TOKENS, today=None):
    """What the style sheet cannot say about a date picker, from the same
    tokens: French locale with Monday first, readable weekday headers,
    weekends in `calendar_weekend`, and TODAY marked (dark blue, bold,
    underlined) so it never looks like the SELECTED day (solid primary tile).
    Display only: the selected date and its format are untouched."""
    calendar.setLocale(QLocale(QLocale.French, QLocale.France))
    calendar.setFirstDayOfWeek(Qt.Monday)
    calendar.setGridVisible(False)
    calendar.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
    calendar.setHorizontalHeaderFormat(QCalendarWidget.ShortDayNames)
    calendar.setHeaderTextFormat(_char_format(t.text_secondary, bold=True))
    for day in (Qt.Saturday, Qt.Sunday):
        calendar.setWeekdayTextFormat(day, _char_format(t.calendar_weekend))
    for day in (Qt.Monday, Qt.Tuesday, Qt.Wednesday, Qt.Thursday, Qt.Friday):
        calendar.setWeekdayTextFormat(day, _char_format(t.text))
    calendar.setDateTextFormat(QDate(), QTextCharFormat())  # forget a previous "today"
    calendar.setDateTextFormat(
        today or QDate.currentDate(),
        _char_format(t.calendar_today_text, bold=True, underline=True),
    )
    return calendar


# --- modes: Système / Clair / Sombre ----------------------------------------------------


class _ThemeEvents(QObject):
    changed = Signal(str)  # "light" | "dark", after the palette is installed


_EVENTS = None


def theme_events():
    global _EVENTS
    if _EVENTS is None:
        _EVENTS = _ThemeEvents()
    return _EVENTS


THEME_MODES = {"system": "Système", "light": "Clair", "dark": "Sombre"}


def system_prefers_dark(app=None):
    """Windows (Qt 6.5+ colour scheme) asks for dark; unknown = light."""
    hints = (app or QGuiApplication.instance()).styleHints()
    return hints.colorScheme() == Qt.ColorScheme.Dark


def resolve_mode(mode, app=None):
    """ "system" | "light" | "dark" -> the palette to use."""
    if mode == "dark" or (mode == "system" and system_prefers_dark(app)):
        return DARK
    return LIGHT


def apply_theme(app, mode="light"):
    """Install style, palette, font and style sheet on the QApplication, for
    `mode` ("system", "light" or "dark"). Can be called again at any time:
    open windows are re-polished, calendars restyled; pages that coloured
    table cells reload them (MainWindow.refresh_theme)."""
    set_active_tokens(resolve_mode(mode, app))
    style = QStyleFactory.create("Fusion")
    app.setStyle(style)
    # Once a style sheet is set, Qt wraps the style (QStyleSheetStyle):
    # remember the base style for diagnostics and tests.
    app.setProperty("theme_base_style", style.metaObject().className())
    app.setProperty("theme_mode", mode if mode in THEME_MODES else "light")
    app.setProperty("theme_name", TOKENS.name)
    app.setPalette(build_palette(TOKENS.current))
    font = QFont(TYPE.family)
    font.setPointSizeF(TYPE.base)
    app.setFont(font)
    app.setStyleSheet(build_stylesheet(TOKENS.current))
    for widget in app.allWidgets():
        if isinstance(widget, QCalendarWidget):
            style_calendar(widget, TOKENS.current)
    theme_events().changed.emit(TOKENS.name)


def follow_system_scheme(app):
    """In « Système » mode, a Windows light/dark switch is applied at once."""

    def changed(_scheme):
        if app.property("theme_mode") == "system":
            apply_theme(app, "system")

    app.styleHints().colorSchemeChanged.connect(changed)


def ensure_app():
    """The running QApplication (created and themed if needed — tests)."""
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app

"""Shared building blocks: buttons with a role, message banner, form dialog,
confirmation dialog, page base class. Pages and dialogs use only these and
the theme (ui/theme.py) — no local colours."""

from html import escape

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QDateEdit,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from .feedback import describe
from .theme import style_calendar

ICONS = {"success": "✓", "error": "✕", "warning": "!", "info": "i"}


def button(text, variant="secondary", *, tooltip=None):
    """QPushButton with a visual role: "primary", "secondary", "danger", "danger-solid"."""
    widget = QPushButton(text)
    widget.setProperty("variant", variant)
    widget.setCursor(Qt.PointingHandCursor)
    if tooltip:
        widget.setToolTip(tooltip)
    return widget


def set_variant(widget, variant):
    widget.setProperty("variant", variant)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def set_invalid(widget, invalid):
    widget.setProperty("invalid", "true" if invalid else "false")
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class Banner(QLabel):
    """Non-modal message strip: icon, short title, explanation, optional
    technical detail (smaller). Success messages fade after a few seconds."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("banner")
        self.setWordWrap(True)
        self.setTextFormat(Qt.RichText)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.hide()
        self._timer = QTimer(self, singleShot=True, timeout=self.hide)
        self.title = ""
        self.message = ""

    def show_message(self, kind, text, *, title="", detail="", autohide=False):
        self.title, self.message = title, text
        self.setProperty("kind", kind)
        self.style().unpolish(self)
        self.style().polish(self)
        html = f"<b>{ICONS.get(kind, '')}&nbsp;&nbsp;{escape(title)}</b>" if title else f"<b>{ICONS.get(kind, '')}</b>"
        html += f"&nbsp;&nbsp;{escape(text)}"
        if detail:
            html += f"<br><span style='font-size:9pt'>Détail technique : {escape(detail)}</span>"
        self.setText(html)
        self.setAccessibleName(f"{title} {text}".strip())
        self.show()
        if autohide:
            self._timer.start(5000)
        else:
            self._timer.stop()

    def plain_text(self):
        return f"{self.title} — {self.message}" if self.title else self.message

    @property
    def kind(self):
        return self.property("kind")


# Field widths by kind of data: a code needs a few characters, a name a
# medium field, a description the full width. None = the whole column.
FIELD_WIDTHS = {"short": 170, "medium": 320, "long": None}

# Space kept between a dialog and the screen edges (taskbar, window frame).
SCREEN_MARGIN = 48


class DateField(QDateEdit):
    """QDateEdit where Tab / Maj+Tab go to the next / previous FIELD, like
    every other input (Qt's default moves between day, month and year, and
    stays stuck on an empty date). Inside the field: arrows, typing, or the
    calendar."""

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Tab, Qt.Key_Backtab) and not event.modifiers() & ~Qt.ShiftModifier:
            QWidget.focusNextPrevChild(self, event.key() == Qt.Key_Tab)
            return
        super().keyPressEvent(event)

    def focusNextPrevChild(self, next_child):
        return QWidget.focusNextPrevChild(self, next_child)


class TimeField(QTimeEdit):
    """QTimeEdit with the same Tab behaviour as DateField."""

    keyPressEvent = DateField.keyPressEvent
    focusNextPrevChild = DateField.focusNextPrevChild


def time_field(value=None):
    """Time input HH:MM (school's local time)."""
    widget = TimeField()
    widget.setDisplayFormat("HH:mm")
    if value is not None:
        widget.setTime(value)
    return widget


def date_field():
    """Date input with a calendar popup, French format; the popup is styled
    from the theme tokens (readable navigation bar, weekends, today)."""
    widget = DateField(calendarPopup=True)
    widget.setDisplayFormat("dd/MM/yyyy")
    style_calendar(widget.calendarWidget())
    return widget


def _fit_combo(combo):
    """A long item (« R12 — Salle 12 · 40 places ») must not widen the whole
    form: the field keeps a reasonable width, the open list shows the full
    texts, and the tooltip repeats the selected one."""
    combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(10)
    metrics = combo.fontMetrics()
    widest = max((metrics.horizontalAdvance(combo.itemText(i)) for i in range(combo.count())), default=0)
    combo.view().setMinimumWidth(widest + 40)
    combo.setToolTip(combo.currentText())
    combo.currentTextChanged.connect(combo.setToolTip)


def _height_for(widget, width):
    height = widget.heightForWidth(width) if widget.hasHeightForWidth() else -1
    return height if height > 0 else widget.sizeHint().height()


class FieldRow(QWidget):
    """One or several fields side by side. Below `STACK_BELOW` pixels the
    fields stack on one column (small screens), so nothing is squeezed."""

    STACK_BELOW = 440

    def __init__(self, parent=None):
        super().__init__(parent)
        self.box = QBoxLayout(QBoxLayout.LeftToRight, self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(16)
        self.blocks = []

    def add(self, block):
        self.blocks.append(block)
        self.box.addWidget(block, 1, Qt.AlignTop)

    @property
    def stacked(self):
        return self.box.direction() == QBoxLayout.TopToBottom

    def arrange(self, width):
        stack = len(self.blocks) > 1 and width < self.STACK_BELOW
        direction = QBoxLayout.TopToBottom if stack else QBoxLayout.LeftToRight
        if self.box.direction() != direction:
            self.box.setDirection(direction)
            self.box.setSpacing(12 if stack else 16)

    def resizeEvent(self, event):
        self.arrange(event.size().width())
        super().resizeEvent(event)


class FormScrollArea(QScrollArea):
    """Scroll area sized like its content: the dialog opens at the natural
    size of the form and scrolls only when the screen is too small."""

    def sizeHint(self):
        content = self.widget()
        if content is None:
            return super().sizeHint()
        hint = content.sizeHint()
        return QSize(hint.width() + self.verticalScrollBar().sizeHint().width(), hint.height())

    def minimumSizeHint(self):
        return QSize(super().minimumSizeHint().width(), 96)


class FormDialog(QDialog):
    """Dialog layout used by every form (fits 1280×720 and smaller screens):

        ┌──────────────────────────────────────────┐
        │ Title                                    │  fixed
        │ Instruction (optional)                   │
        ├──────────────────────────────────────────┤
        │ Label *            Label                 │  scrollable when the
        │ [ field ]          [ field ]             │  screen is too small
        │ help               help                  │
        │ …                                        │
        ├──────────────────────────────────────────┤
        │ * champ obligatoire                      │  fixed: always visible
        │ Why the main action is disabled          │
        │                  [ Annuler ] [ Enregistrer ]
        └──────────────────────────────────────────┘

    The scroll bar belongs to the form, never to the whole window, so the
    buttons stay reachable (mouse and keyboard) whatever the screen size.
    Fields get a width that matches their data (`width="short" | "medium"
    | "long"`) and can sit side by side (`beside=True`); side-by-side fields
    stack on one column when the dialog is narrow.
    Esc / Annuler closes, Enter saves when the form is valid, Tab moves
    through the fields (the form scrolls to the focused one).
    """

    def __init__(self, title, instruction="", parent=None, *, save_text="Enregistrer", width=560):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.preferred_width = width
        self.setMinimumWidth(min(width, 420))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header = QWidget(objectName="dialogHeader")
        head = QVBoxLayout(self.header)
        head.setContentsMargins(24, 20, 24, 8)
        head.setSpacing(4)
        head.addWidget(QLabel(title, objectName="dialogTitle"))
        if instruction:
            sub = QLabel(instruction, objectName="subtitle")
            sub.setWordWrap(True)
            head.addWidget(sub)
        outer.addWidget(self.header)

        self.content = QWidget(objectName="dialogContent")
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(24, 8, 24, 12)
        self.body.setSpacing(14)
        self.scroll = FormScrollArea(objectName="dialogScroll")
        self.scroll.setWidget(self.content)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setFocusPolicy(Qt.NoFocus)  # not a Tab stop: fields are
        outer.addWidget(self.scroll, 1)

        self.footer = QFrame(objectName="dialogFooter")
        self.footer_layout = QVBoxLayout(self.footer)
        self.footer_layout.setContentsMargins(24, 10, 24, 16)
        self.footer_layout.setSpacing(6)
        outer.addWidget(self.footer)

        self.labels = {}
        self.rows = []
        self._row_break = False
        self.status = QLabel("", objectName="help")
        self.status.setWordWrap(True)
        self.cancel_button = button("Annuler", "secondary")
        self.save_button = button(save_text, "primary")
        self.save_button.setDefault(True)
        self.cancel_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self._save)
        self._fitted = False

    def add_field(self, key, label, widget, *, required=False, help_text="", width="long", beside=False):
        """Add a labelled field. `width`: "short" (codes, numbers, dates),
        "medium" (names), "long" (full column). `beside=True` puts it on the
        same row as the previous field."""
        caption = QLabel(f"{label}{' *' if required else ''}", objectName="fieldLabel")
        caption.setBuddy(widget)  # Alt+letter focus and screen readers
        widget.setAccessibleName(label)
        self.labels[key] = caption
        block = QWidget()
        column = QVBoxLayout(block)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)
        column.addWidget(caption)
        column.addWidget(widget)
        limit = FIELD_WIDTHS.get(width)
        if limit:
            widget.setMaximumWidth(limit)
        if isinstance(widget, QComboBox):
            _fit_combo(widget)
        if help_text:
            hint = QLabel(help_text, objectName="help")
            hint.setWordWrap(True)
            column.addWidget(hint)
        if not (beside and self.rows and not self._row_break):
            self.rows.append(FieldRow())
            self.body.addWidget(self.rows[-1])
        self._row_break = False
        self.rows[-1].add(block)
        return widget

    def add_section(self, title, note=""):
        """Section heading inside a long form (IDENTITÉ, SCOLARITÉ…): a
        title and an optional short note, separated from the fields above."""
        heading = QLabel(title.upper(), objectName="sectionTitle")
        self.body.addWidget(heading)
        if note:
            hint = QLabel(note, objectName="help")
            hint.setWordWrap(True)
            self.body.addWidget(hint)
        self._row_break = True  # the next field starts a new row
        return heading

    def finish(self, *, required_note=True):
        """Call once the fields are added: footer (note, status, buttons)."""
        self.body.addStretch()
        if required_note:
            self.footer_layout.addWidget(QLabel("* champ obligatoire", objectName="help"))
        self.footer_layout.addWidget(self.status)
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch()
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.save_button)
        self.footer_layout.addLayout(actions)
        QShortcut(QKeySequence(Qt.CTRL | Qt.Key_Return), self, activated=self._save)
        self.refresh_state()
        self.fit_to(self._available_size())

    # --- size -----------------------------------------------------------------
    def _available_size(self):
        parent = self.parentWidget()
        screen = (parent.screen() if parent is not None else None) or self.screen() or QGuiApplication.primaryScreen()
        return screen.availableGeometry().size() if screen is not None else QSize(1280, 720)

    def natural_height(self, width):
        """Height the dialog needs at `width` to show the whole form."""
        return (
            _height_for(self.header, width)
            + _height_for(self.content, width - self.scroll.verticalScrollBar().sizeHint().width())
            + _height_for(self.footer, width)
        )

    def fit_to(self, available):
        """Size the dialog for a screen of `available` size: a reasonable
        width, the height of the form, never larger than the screen (the
        form scrolls instead)."""
        max_width = max(320, available.width() - SCREEN_MARGIN)
        max_height = max(260, available.height() - SCREEN_MARGIN)
        self.setMaximumSize(max_width, max_height)
        self.setMinimumWidth(min(self.minimumWidth(), max_width))
        width = min(max(self.preferred_width, self.minimumWidth()), max_width)
        height = min(self.natural_height(width), max_height)
        self.resize(width, height)

    def showEvent(self, event):
        if not self._fitted:  # once: later, the user may resize freely (within the screen)
            self._fitted = True
            self.fit_to(self._available_size())
        super().showEvent(event)

    # --- state ------------------------------------------------------------------
    def missing_fields(self):
        """Labels of the required fields still empty / unselected."""
        return []

    def refresh_state(self):
        missing = self.missing_fields()
        self.save_button.setEnabled(not missing)
        reason = f"Pour enregistrer, complétez : {', '.join(missing)}." if missing else ""
        self.status.setText(reason)
        self.status.setVisible(bool(reason))
        self.save_button.setToolTip(reason or "Enregistrer (Entrée)")

    def _save(self):
        if self.save_button.isEnabled():
            self.accept()

    @property
    def save_enabled(self):
        return self.save_button.isEnabled()


class ConfirmDialog(FormDialog):
    """Confirmation of a consequential action (themed, explicit button names)."""

    def __init__(self, title, text, parent=None, *, confirm_text="Confirmer", danger=False):
        super().__init__(title, parent=parent, save_text=confirm_text, width=480)
        self.message = QLabel(text)
        self.message.setWordWrap(True)
        self.body.addWidget(self.message)
        if danger:
            set_variant(self.save_button, "danger-solid")
        self.finish(required_note=False)
        self.cancel_button.setFocus()  # the safe choice is focused
        self.save_button.setDefault(False)
        self.cancel_button.setDefault(True)


def ask_confirmation(parent, title, text, *, confirm_text="Confirmer", danger=False):
    return ConfirmDialog(title, text, parent, confirm_text=confirm_text, danger=danger).exec() == QDialog.Accepted


class Page(QWidget):
    """A screen of the shell. Subclasses call `self.call(fn, on_success,
    action=...)`: the API call runs off the UI thread and every error is
    handled the same way (401 -> session_expired, others -> banner whose
    title is `action`)."""

    session_expired = Signal()

    def __init__(self, runner, parent=None, *, confirm=ask_confirmation):
        super().__init__(parent)
        self.setObjectName("page")
        self.runner = runner
        self.confirm = confirm
        self.banner = Banner(self)
        self.busy = False
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(28, 22, 28, 22)
        self.layout_.setSpacing(14)

    def call(self, fn, on_success, *, action=None):
        self.set_busy(True)

        def ok(result):
            self.set_busy(False)
            on_success(result)

        self.runner.run(fn, ok, lambda exc: self.handle_error(exc, action))

    def handle_error(self, exc, action=None):
        self.set_busy(False)
        feedback = describe(exc, action)
        if feedback.session_expired:
            self.session_expired.emit()
            return
        self.banner.show_message(feedback.kind, feedback.text, title=feedback.title, detail=feedback.detail)
        if feedback.reload:
            self.reload()

    def success(self, text):
        self.banner.show_message("success", text, autohide=True)

    def set_busy(self, busy):
        self.busy = busy
        self.setCursor(Qt.BusyCursor if busy else Qt.ArrowCursor)

    def reload(self):  # pages with data override it
        pass

    def activate(self):
        """Called when the page becomes visible."""
        self.reload()

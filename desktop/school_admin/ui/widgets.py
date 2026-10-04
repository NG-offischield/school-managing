"""Shared building blocks: buttons with a role, message banner, form dialog,
confirmation dialog, page base class. Pages and dialogs use only these and
the theme (ui/theme.py) — no local colours."""

from html import escape

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .feedback import describe

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


class FormDialog(QDialog):
    """Dialog layout used by every form:

        Title
        Instruction (optional)
        Label *
        [ field ]
        help (optional)
        ...
        Why the main action is disabled (if it is)
                                  [ Annuler ] [ Enregistrer ]

    Esc / Annuler closes, Enter saves when the form is valid. Subclasses
    add rows with `add_field` and implement `missing_fields()`.
    """

    def __init__(self, title, instruction="", parent=None, *, save_text="Enregistrer"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(480)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(24, 22, 24, 20)
        self.body.setSpacing(6)
        heading = QLabel(title, objectName="dialogTitle")
        self.body.addWidget(heading)
        if instruction:
            sub = QLabel(instruction, objectName="subtitle")
            sub.setWordWrap(True)
            self.body.addWidget(sub)
        self.body.addSpacing(10)
        self.labels = {}
        self.status = QLabel("", objectName="help")
        self.status.setWordWrap(True)
        self.cancel_button = button("Annuler", "secondary")
        self.save_button = button(save_text, "primary")
        self.save_button.setDefault(True)
        self.cancel_button.clicked.connect(self.reject)
        self.save_button.clicked.connect(self._save)
        self._fields_end = None

    def add_field(self, key, label, widget, *, required=False, help_text=""):
        caption = QLabel(f"{label}{' *' if required else ''}", objectName="fieldLabel")
        caption.setBuddy(widget)  # Alt+letter focus and screen readers
        widget.setAccessibleName(label)
        self.labels[key] = caption
        self.body.addWidget(caption)
        self.body.addWidget(widget)
        if help_text:
            hint = QLabel(help_text, objectName="help")
            hint.setWordWrap(True)
            self.body.addWidget(hint)
        self.body.addSpacing(8)
        return widget

    def finish(self):
        """Call once the fields are added: status line + buttons."""
        self.body.addWidget(QLabel("* champ obligatoire", objectName="help"))
        self.body.addWidget(self.status)
        self.body.addSpacing(6)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self.cancel_button)
        row.addWidget(self.save_button)
        self.body.addLayout(row)
        QShortcut(QKeySequence(Qt.CTRL | Qt.Key_Return), self, activated=self._save)
        self.refresh_state()

    def missing_fields(self):
        """Labels of the required fields still empty / unselected."""
        return []

    def refresh_state(self):
        missing = self.missing_fields()
        self.save_button.setEnabled(not missing)
        reason = f"Pour enregistrer, complétez : {', '.join(missing)}." if missing else ""
        self.status.setText(reason)
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
        super().__init__(title, parent=parent, save_text=confirm_text)
        message = QLabel(text)
        message.setWordWrap(True)
        self.body.addWidget(message)
        self.body.addSpacing(10)
        if danger:
            set_variant(self.save_button, "danger-solid")
        self.cancel_button.setFocus()  # the safe choice is focused
        self.save_button.setDefault(False)
        self.cancel_button.setDefault(True)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self.cancel_button)
        row.addWidget(self.save_button)
        self.body.addLayout(row)


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

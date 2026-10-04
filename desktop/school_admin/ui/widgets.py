"""Small shared widgets: message banner and page base class."""

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QLabel, QMessageBox, QVBoxLayout, QWidget

from .feedback import describe


class Banner(QLabel):
    """Non-modal message strip (success / info / warning / error)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("banner")
        self.setWordWrap(True)
        self.hide()
        self._timer = QTimer(self, singleShot=True, timeout=self.hide)

    def show_message(self, kind, text, *, autohide=False):
        self.setProperty("kind", kind)
        self.style().unpolish(self)
        self.style().polish(self)
        self.setText(text)
        self.show()
        if autohide:
            self._timer.start(4000)
        else:
            self._timer.stop()

    @property
    def kind(self):
        return self.property("kind")


def ask_confirmation(parent, title, text):
    answer = QMessageBox.question(parent, title, text, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
    return answer == QMessageBox.Yes


class Page(QWidget):
    """A screen of the shell. Subclasses call `self.call(fn, on_success)`:
    the API call runs off the UI thread and every error is handled the same
    way (401 -> session_expired, others -> banner)."""

    session_expired = Signal()

    def __init__(self, runner, parent=None, *, confirm=ask_confirmation):
        super().__init__(parent)
        self.setObjectName("page")
        self.runner = runner
        self.confirm = confirm
        self.banner = Banner(self)
        self.busy = False
        self.layout_ = QVBoxLayout(self)
        self.layout_.setContentsMargins(20, 16, 20, 16)
        self.layout_.setSpacing(10)

    def call(self, fn, on_success):
        self.set_busy(True)

        def ok(result):
            self.set_busy(False)
            on_success(result)

        self.runner.run(fn, ok, self.handle_error)

    def handle_error(self, exc):
        self.set_busy(False)
        feedback = describe(exc)
        if feedback.session_expired:
            self.session_expired.emit()
            return
        self.banner.show_message(feedback.kind, f"{feedback.title} — {feedback.text}")
        if feedback.reload:
            self.reload()

    def success(self, text):
        self.banner.show_message("success", text, autohide=True)

    def set_busy(self, busy):
        self.busy = busy

    def reload(self):  # pages with data override it
        pass

    def activate(self):
        """Called when the page becomes visible."""
        self.reload()

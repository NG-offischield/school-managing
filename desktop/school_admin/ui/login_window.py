"""Login screen: identifier, password, "rester connecté", loading state,
clear errors. The password field is cleared as soon as the request leaves."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .feedback import describe
from .widgets import Banner


class LoginWindow(QWidget):
    logged_in = Signal(object)  # Identity

    def __init__(self, auth, runner, config, parent=None):
        super().__init__(parent)
        self.auth, self.runner, self.config = auth, runner, config
        self.setWindowTitle("Administration scolaire — Connexion")
        self.setObjectName("page")
        self.resize(460, 520)

        card = QFrame(objectName="card")
        form = QVBoxLayout(card)
        form.setContentsMargins(28, 28, 28, 28)
        form.setSpacing(10)
        title = QLabel("Administration scolaire", objectName="pageTitle")
        subtitle = QLabel("Connectez-vous avec votre compte administrateur.", objectName="muted")
        self.identifier = QLineEdit(placeholderText="Identifiant ou e-mail")
        self.password = QLineEdit(placeholderText="Mot de passe", echoMode=QLineEdit.Password)
        self.remember = QCheckBox("Rester connecté sur ce poste")
        self.remember.setToolTip(
            "Conserve uniquement un jeton de session dans le coffre sécurisé du système, jamais le mot de passe."
        )
        self.submit = QPushButton("Se connecter", objectName="primary")
        self.submit.setDefault(True)
        self.banner = Banner(self)
        server = QLabel(f"Serveur : {config.api_url}", objectName="muted")
        server.setTextInteractionFlags(Qt.TextSelectableByMouse)
        for widget in (
            title,
            subtitle,
            self.identifier,
            self.password,
            self.remember,
            self.submit,
            self.banner,
            server,
        ):
            form.addWidget(widget)
        if config.insecure_transport:
            warning = Banner(self)
            warning.show_message(
                "warning",
                "Connexion non chiffrée (HTTP) vers un autre poste : à réserver au "
                "réseau de développement. Utilisez HTTPS en production.",
            )
            form.addWidget(warning)

        outer = QVBoxLayout(self)
        outer.addStretch()
        outer.addWidget(card, alignment=Qt.AlignHCenter)
        outer.addStretch()
        card.setFixedWidth(400)

        self.submit.clicked.connect(self.attempt)
        self.password.returnPressed.connect(self.attempt)
        self.identifier.returnPressed.connect(self.password.setFocus)
        self.identifier.textChanged.connect(self._update_state)
        self.password.textChanged.connect(self._update_state)
        self._loading = False
        self._update_state()

    def _update_state(self):
        ready = bool(self.identifier.text().strip() and self.password.text()) and not self._loading
        self.submit.setEnabled(ready)
        self.submit.setText("Connexion…" if self._loading else "Se connecter")
        for widget in (self.identifier, self.password, self.remember):
            widget.setEnabled(not self._loading)

    def attempt(self):
        if not self.submit.isEnabled():
            return
        identifier, password = self.identifier.text(), self.password.text()
        remember = self.remember.isChecked()
        self.password.clear()  # the form does not keep it either
        self._loading = True
        self.banner.hide()
        self._update_state()
        self.runner.run(lambda: self.auth.login(identifier, password, remember=remember), self._done, self._failed)

    def _done(self, identity):
        self._loading = False
        self._update_state()
        self.logged_in.emit(identity)

    def _failed(self, exc):
        self._loading = False
        self._update_state()
        feedback = describe(exc)
        text = exc.message if getattr(exc, "status", None) == 401 else f"{feedback.title} — {feedback.text}"
        self.banner.show_message("error", text)
        self.password.setFocus()

    def reset(self, message=None):
        self.password.clear()
        self.banner.hide()
        if message:
            self.banner.show_message("info", message)

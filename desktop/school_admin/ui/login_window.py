"""Login screen: identifier, password, "rester connecté", loading state,
clear errors. The password field is cleared as soon as the request leaves."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QFrame, QLabel, QLineEdit, QVBoxLayout, QWidget

from ..i18n import tr
from .branding import SOFTWARE_NAME, brand_mark, software_icon
from .feedback import describe
from .widgets import Banner, button


class LoginWindow(QWidget):
    logged_in = Signal(object)  # Identity

    def __init__(self, auth, runner, config, parent=None):
        super().__init__(parent)
        self.auth, self.runner, self.config = auth, runner, config
        self.setWindowTitle(tr("{0} — Connexion", SOFTWARE_NAME))
        self.setWindowIcon(software_icon())
        self.setObjectName("loginBackground")
        self.setMinimumSize(520, 600)

        card = QFrame(objectName="card")
        form = QVBoxLayout(card)
        form.setContentsMargins(32, 30, 32, 28)
        form.setSpacing(6)
        self.brand = brand_mark("horizontal", 44, object_name="softwareBrandLogin")  # the SOFTWARE's identity
        form.addWidget(self.brand)
        form.addWidget(QLabel(tr("Administration scolaire"), objectName="appTitle"))
        subtitle = QLabel(tr("Connectez-vous avec votre compte administrateur."), objectName="subtitle")
        subtitle.setWordWrap(True)
        form.addWidget(subtitle)
        form.addSpacing(14)

        self.identifier = QLineEdit(placeholderText=tr("ex. admin ou admin@ecole.cm"))
        self.password = QLineEdit(placeholderText=tr("Votre mot de passe"), echoMode=QLineEdit.Password)
        for caption, field, name in (
            (tr("Identifiant ou e-mail"), self.identifier, tr("Identifiant")),
            (tr("Mot de passe"), self.password, tr("Mot de passe")),
        ):
            label = QLabel(caption, objectName="fieldLabel")
            label.setBuddy(field)
            field.setAccessibleName(name)
            form.addWidget(label)
            form.addWidget(field)
            form.addSpacing(8)
        self.remember = QCheckBox(tr("Rester connecté sur ce poste"))
        self.remember.setToolTip(
            tr("Conserve uniquement un jeton de session dans le coffre sécurisé du système, jamais le mot de passe.")
        )
        form.addWidget(self.remember)
        form.addSpacing(10)
        self.submit = button(tr("Se connecter"), "primary")
        self.submit.setDefault(True)
        self.submit.setMinimumHeight(40)
        form.addWidget(self.submit)
        self.banner = Banner(self)
        form.addSpacing(6)
        form.addWidget(self.banner)
        form.addSpacing(6)
        server = QLabel(tr("Serveur : {0}", config.api_url), objectName="help")
        server.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addWidget(server)
        if config.insecure_transport:
            warning = Banner(self)
            warning.show_message(
                "warning",
                tr(
                    "connexion non chiffrée vers un autre poste. À réserver au réseau de développement ; utilisez "
                    "HTTPS en production."
                ),
                title="HTTP",
            )
            form.addWidget(warning)

        outer = QVBoxLayout(self)
        outer.addStretch()
        outer.addWidget(card, alignment=Qt.AlignHCenter)
        outer.addStretch()
        card.setFixedWidth(440)
        self.setTabOrder(self.identifier, self.password)
        self.setTabOrder(self.password, self.remember)
        self.setTabOrder(self.remember, self.submit)

        self.submit.clicked.connect(self.attempt)
        self.password.returnPressed.connect(self.attempt)
        self.identifier.returnPressed.connect(self.password.setFocus)
        self.identifier.textChanged.connect(self._update_state)
        self.password.textChanged.connect(self._update_state)
        self._loading = False
        self._update_state()
        self.identifier.setFocus()

    def _update_state(self):
        ready = bool(self.identifier.text().strip() and self.password.text()) and not self._loading
        self.submit.setEnabled(ready)
        self.submit.setText(tr("Connexion en cours…") if self._loading else tr("Se connecter"))
        self.submit.setToolTip("" if ready or self._loading else tr("Saisissez l'identifiant et le mot de passe."))
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
        if getattr(exc, "status", None) == 401:
            self.banner.show_message("error", exc.message, title=tr("Connexion refusée"))
        else:
            feedback = describe(exc, tr("Connexion impossible"))
            self.banner.show_message("error", feedback.text, title=feedback.title, detail=feedback.detail)
        self.password.setFocus()

    def reset(self, message=None):
        self.password.clear()
        self.banner.hide()
        if message:
            self.banner.show_message("info", message)

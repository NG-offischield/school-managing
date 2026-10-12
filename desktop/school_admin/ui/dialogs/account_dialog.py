"""« Mon compte »: the connected administrator's own account.

Identity (name, e-mail, role, school) is shown, never edited here: it is
administrative data. The contact details are the fields the SERVER declares
editable; photo, password (the other devices are then disconnected) and
connected devices complete it. Every call runs off the UI thread through the
page runner; errors are shown in the dialog's banner (it is modal).
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...services.me import FIELD_LABELS, PHOTO_FILTER
from ..feedback import describe
from ..widgets import Banner, FormDialog, ask_confirmation, button

ROLE_LABELS = {"ADMIN": "Administrateur", "SUPER_ADMIN": "Super-administrateur", "TEACHER": "Enseignant"}
PHOTO_MESSAGES = {
    "photo_invalid": "Ce fichier n'est pas une image lisible.",
    "photo_format": "Utilisez une photo JPEG, PNG ou WebP.",
    "photo_too_small": "La photo est trop petite (120 px minimum de côté).",
    "photo_too_large": "La photo est trop grande (3 Mo maximum).",
}


def choose_photo_file(parent):
    path, _ = QFileDialog.getOpenFileName(parent, "Choisir une photo", "", PHOTO_FILTER)
    return path


class AccountDialog(FormDialog):
    signed_out = Signal()  # every device disconnected, this one included
    session_expired = Signal()

    def __init__(self, service, runner, parent=None, *, choose_photo=choose_photo_file, confirm=ask_confirmation):
        super().__init__(
            "Mon compte",
            "Vos coordonnées, votre photo, votre mot de passe et vos appareils connectés.",
            parent,
            save_text="Fermer",
            width=640,
        )
        self.service, self.runner = service, runner
        self.choose_photo, self.confirm = choose_photo, confirm
        self.profile = None
        self.inputs = {}
        self.sessions = []
        self.cancel_button.hide()

        self.banner = Banner()
        self.body.addWidget(self.banner)

        self.add_section("Identité", "Gérés par l'administration de l'école : nom, e-mail, rôle, établissement.")
        identity = QWidget()
        row = QHBoxLayout(identity)
        row.setContentsMargins(0, 0, 0, 0)
        self.photo = QLabel("…", alignment=Qt.AlignCenter, objectName="avatar")
        self.photo.setFixedSize(96, 96)
        row.addWidget(self.photo)
        text = QVBoxLayout()
        self.name_label = QLabel("", objectName="dialogTitle")
        self.email_label = QLabel("", objectName="help")
        self.role_label = QLabel("")
        for widget in (self.name_label, self.email_label, self.role_label):
            widget.setWordWrap(True)
            text.addWidget(widget)
        photo_actions = QHBoxLayout()
        self.photo_button = button("Changer la photo…", "secondary")
        self.remove_photo_button = button("Retirer la photo", "secondary")
        self.photo_button.clicked.connect(self.change_photo)
        self.remove_photo_button.clicked.connect(self.remove_photo)
        photo_actions.addWidget(self.photo_button)
        photo_actions.addWidget(self.remove_photo_button)
        photo_actions.addStretch()
        text.addLayout(photo_actions)
        row.addLayout(text, 1)
        self.body.addWidget(identity)

        self.add_section("Coordonnées")
        self.fields_box = QVBoxLayout()
        holder = QWidget()
        holder.setLayout(self.fields_box)
        self.fields_box.setContentsMargins(0, 0, 0, 0)
        self.body.addWidget(holder)
        self.save_details_button = button("Enregistrer les coordonnées", "primary")
        self.save_details_button.clicked.connect(self.save_details)
        self.body.addWidget(self.save_details_button, 0, Qt.AlignLeft)

        self.add_section(
            "Mot de passe", "Après le changement, vos autres appareils sont déconnectés ; ce poste reste connecté."
        )
        self.current_password = self._password("Mot de passe actuel")
        self.new_password = self._password("Nouveau mot de passe (10 caractères au minimum)")
        self.confirm_password = self._password("Confirmer le nouveau mot de passe")
        self.password_button = button("Changer le mot de passe", "secondary")
        self.password_button.clicked.connect(self.change_password)
        self.body.addWidget(self.password_button, 0, Qt.AlignLeft)

        self.add_section("Appareils connectés")
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Appareil", "Dernière activité", ""])
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setMinimumHeight(140)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.body.addWidget(self.table)
        sessions_actions = QHBoxLayout()
        self.revoke_button = button("Déconnecter cet appareil", "secondary")
        self.revoke_all_button = button("Déconnecter tous mes appareils", "danger")
        self.revoke_button.clicked.connect(self.revoke_selected)
        self.revoke_all_button.clicked.connect(self.revoke_all)
        sessions_actions.addWidget(self.revoke_button)
        sessions_actions.addStretch()
        sessions_actions.addWidget(self.revoke_all_button)
        holder2 = QWidget()
        holder2.setLayout(sessions_actions)
        sessions_actions.setContentsMargins(0, 0, 0, 0)
        self.body.addWidget(holder2)

        self.finish(required_note=False)
        self._set_busy(True)
        self.reload()

    # --- helpers ------------------------------------------------------------------------
    def _password(self, label):
        field = QLineEdit()
        field.setEchoMode(QLineEdit.Password)
        return self.add_field(f"pw:{label}", label, field, width="medium")

    def _set_busy(self, busy):
        for widget in (
            self.photo_button,
            self.remove_photo_button,
            self.save_details_button,
            self.password_button,
            self.revoke_all_button,
        ):
            widget.setEnabled(not busy)
        if not busy and self.profile is not None:
            self.remove_photo_button.setEnabled(self.profile.has_photo)
        self._selection_changed(busy)

    def _call(self, fn, ok, action):
        self._set_busy(True)

        def done(result):
            self._set_busy(False)
            ok(result)

        def failed(exc):
            self._set_busy(False)
            feedback = describe(exc, action)
            if feedback.session_expired:
                self.reject()
                self.session_expired.emit()
                return
            text = PHOTO_MESSAGES.get(getattr(exc, "rule", None), feedback.text)
            self.banner.show_message(feedback.kind, text, title=feedback.title)

        self.runner.run(fn, done, failed)

    def show_message(self, kind, text):
        self.banner.show_message(kind, text, autohide=kind == "success")

    # --- load -----------------------------------------------------------------------------
    def reload(self):
        def load():
            profile = self.service.profile()
            photo = self.service.photo() if profile.has_photo else None
            return profile, photo, self.service.sessions()

        self._call(load, self._loaded, "Impossible de charger votre compte")

    def _loaded(self, result):
        profile, photo, sessions = result
        self._show_profile(profile, photo)
        self._show_sessions(sessions)

    def _show_profile(self, profile, photo=None):
        self.profile = profile
        self.name_label.setText(profile.full_name)
        self.email_label.setText(profile.email)
        roles = ", ".join(ROLE_LABELS.get(r, r) for r in profile.roles)
        self.role_label.setText(f"{roles} · {profile.school_name}")
        self._show_photo(photo)
        self.remove_photo_button.setEnabled(profile.has_photo)
        self.photo_button.setText("Changer la photo…" if profile.has_photo else "Ajouter une photo…")
        if not self.inputs:  # the editable fields come from the server
            for name in profile.editable:
                if name == "preferred_language":
                    widget = QComboBox()
                    for code, label in profile.languages.items():
                        widget.addItem(label, code)
                elif name == "address":
                    widget = QPlainTextEdit()
                    widget.setFixedHeight(70)
                else:
                    widget = QLineEdit()
                caption = QLabel(FIELD_LABELS.get(name, name), objectName="fieldLabel")
                caption.setBuddy(widget)
                widget.setAccessibleName(FIELD_LABELS.get(name, name))
                self.fields_box.addWidget(caption)
                self.fields_box.addWidget(widget)
                self.inputs[name] = widget
        for name, widget in self.inputs.items():
            value = profile.values.get(name, "")
            if isinstance(widget, QComboBox):
                widget.setCurrentIndex(max(0, widget.findData(value)))
            elif isinstance(widget, QPlainTextEdit):
                widget.setPlainText(value)
            else:
                widget.setText(value)

    def _show_photo(self, content):
        pixmap = QPixmap()
        if content and pixmap.loadFromData(content):
            self.photo.setPixmap(pixmap.scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.photo.setPixmap(QPixmap())
            initials = "".join(p[0] for p in (self.profile.full_name.split() if self.profile else [])[:2]).upper()
            self.photo.setText(initials or "?")

    def _show_sessions(self, sessions):
        self.sessions = sessions
        self.table.setRowCount(len(sessions))
        for row, session in enumerate(sessions):
            when = f"{session.last_used_at:%d/%m/%Y %H:%M}" if session.last_used_at else "—"
            for column, text in enumerate([session.device_name, when, "Ce poste" if session.current else ""]):
                self.table.setItem(row, column, QTableWidgetItem(text))
        self._selection_changed()

    def _selection_changed(self, busy=False):
        session = self.selected_session()
        self.revoke_button.setEnabled(bool(session) and not session.current and not busy)

    def selected_session(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return self.sessions[rows[0].row()] if rows else None

    # --- actions ----------------------------------------------------------------------------
    def values(self):
        result = {}
        for name, widget in self.inputs.items():
            if isinstance(widget, QComboBox):
                result[name] = widget.currentData() or ""
            elif isinstance(widget, QPlainTextEdit):
                result[name] = widget.toPlainText().strip()
            else:
                result[name] = widget.text().strip()
        return result

    def save_details(self):
        if self.profile is None:
            return
        changes = {k: v for k, v in self.values().items() if v != self.profile.values.get(k, "")}
        if not changes:
            self.show_message("info", "Aucune modification à enregistrer.")
            return

        def saved(profile):
            self._show_profile(profile)
            self.show_message("success", "Coordonnées enregistrées.")

        self._call(lambda: self.service.update(changes), saved, "Coordonnées refusées")

    def change_photo(self):
        path = self.choose_photo(self)
        if not path:
            return

        def upload():
            profile = self.service.upload_photo(path)
            return profile, self.service.photo()

        def done(result):
            self._show_profile(result[0], result[1])
            self.show_message("success", "Photo mise à jour.")

        self._call(upload, done, "Photo refusée")

    def remove_photo(self):
        def done(profile):
            self._show_profile(profile, None)
            self.show_message("success", "Photo retirée.")

        self._call(self.service.delete_photo, done, "Impossible de retirer la photo")

    def change_password(self):
        current, new, again = (
            self.current_password.text(),
            self.new_password.text(),
            self.confirm_password.text(),
        )
        if not current or not new:
            self.show_message("warning", "Saisissez le mot de passe actuel et le nouveau.")
            return
        if new != again:
            self.show_message("warning", "La confirmation ne correspond pas au nouveau mot de passe.")
            return

        def done(_):
            for field in (self.current_password, self.new_password, self.confirm_password):
                field.clear()
            self.show_message("success", "Mot de passe changé. Vos autres appareils ont été déconnectés.")
            self._call(self.service.sessions, self._show_sessions, "Impossible d'actualiser les appareils")

        self._call(lambda: self.service.change_password(current, new), done, "Mot de passe refusé")

    def revoke_selected(self):
        session = self.selected_session()
        if session is None or session.current:
            return

        def done(sessions):
            self._show_sessions(sessions)
            self.show_message("success", f"« {session.device_name} » est déconnecté.")

        def revoke():
            self.service.revoke(session.id)
            return self.service.sessions()

        self._call(revoke, done, "Impossible de déconnecter l'appareil")

    def revoke_all(self):
        if not self.confirm(
            self,
            "Déconnecter tous mes appareils",
            "Tous vos appareils, ce poste compris, devront se reconnecter.",
            confirm_text="Tout déconnecter",
            danger=True,
        ):
            return

        def done(_):
            self.accept()
            self.signed_out.emit()

        self._call(self.service.revoke_all, done, "Impossible de déconnecter vos appareils")

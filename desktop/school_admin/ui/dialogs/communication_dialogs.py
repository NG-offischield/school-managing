"""Communication dialogs (ADR 0023). Forms collect what the API needs; the
server decides visibility, transitions, moderation and checks attachments
(PDF / PNG / JPEG, real content, size). Files: only the bare name and the
bytes leave the computer (services/communication.read_attachment)."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...models import (
    COMPLAINT_CATEGORIES,
    COMPLAINT_NEXT,
    COMPLAINT_PRIORITIES,
    COMPLAINT_STATUSES,
    FORUM_ROLES,
    NOTIFICATION_TYPES,
    SEVERITIES,
    SPACE_AUDIENCES,
)
from ...services.communication import read_attachment
from ..widgets import FormDialog, button
from .teacher_dialogs import _grid

FILE_FILTER = "Documents (*.pdf *.png *.jpg *.jpeg)"


def _when(moment):
    return f"{moment:%d/%m/%Y %H:%M}" if moment else "—"


def choose_files(parent):
    """Local files chosen by the user (PDF / PNG / JPEG); the server re-checks the content."""
    paths, _ = QFileDialog.getOpenFileNames(parent, "Joindre des fichiers", "", FILE_FILTER)
    return paths


def _text(placeholder, height=96):
    widget = QPlainTextEdit(placeholderText=placeholder)
    widget.setFixedHeight(height)
    widget.setTabChangesFocus(True)
    return widget


class AttachmentPicker(QWidget):
    """« Joindre… » + the list of chosen files (names only)."""

    def __init__(self, choose=choose_files, parent=None):
        super().__init__(parent)
        self.choose = choose
        self.paths = []
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.add_button = button("Joindre…", tooltip="PDF, PNG ou JPEG (vérifiés par le serveur)")
        self.label = QLabel("Aucun fichier", objectName="help")
        self.label.setWordWrap(True)
        row.addWidget(self.add_button)
        row.addWidget(self.label, 1)
        self.add_button.clicked.connect(self.pick)

    def pick(self):
        self.paths += [p for p in self.choose(self) if p not in self.paths]
        self.label.setText(", ".join(Path(p).name for p in self.paths) or "Aucun fichier")

    def files(self):
        return [read_attachment(path) for path in self.paths]


class NotificationDialog(FormDialog):
    def __init__(self, notification, parent=None):
        super().__init__(notification.title, "", parent, save_text="Fermer", width=520)
        self.cancel_button.hide()
        self.body.addWidget(
            _grid(
                [
                    ("Type", NOTIFICATION_TYPES.get(notification.kind, notification.kind)),
                    ("Importance", SEVERITIES.get(notification.severity, notification.severity)),
                    ("Reçue le", _when(notification.created_at)),
                    ("Statut", f"Lue le {_when(notification.read_at)}" if notification.is_read else "Non lue"),
                ]
            )
        )
        message = QLabel(notification.message or "—")
        message.setWordWrap(True)
        message.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.add_section("Message")
        self.body.addWidget(message)
        self.finish(required_note=False)


class MemberList(QWidget):
    """Searchable checklist of school members (the administration directory)."""

    def __init__(self, members, parent=None):
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        self.filter = QLineEdit(placeholderText="Filtrer par nom")
        self.list = QListWidget()
        self.list.setMaximumHeight(150)
        for member in members:
            item = QListWidgetItem(member.label)
            item.setData(Qt.UserRole, member.id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.list.addItem(item)
        column.addWidget(self.filter)
        column.addWidget(self.list)
        self.filter.textChanged.connect(self._filter)

    def _filter(self, text):
        for index in range(self.list.count()):
            item = self.list.item(index)
            item.setHidden(text.strip().lower() not in item.text().lower())

    def check(self, member_id):
        for index in range(self.list.count()):
            if self.list.item(index).data(Qt.UserRole) == member_id:
                self.list.item(index).setCheckState(Qt.Checked)

    @property
    def ids(self):
        return [
            self.list.item(i).data(Qt.UserRole)
            for i in range(self.list.count())
            if self.list.item(i).checkState() == Qt.Checked
        ]


class NewConversationDialog(FormDialog):
    def __init__(self, members, parent=None, *, choose=choose_files):
        super().__init__(
            "Nouvelle conversation",
            "Message de l'administration. Les participants verront la conversation et ses pièces jointes.",
            parent,
            save_text="Envoyer",
            width=600,
        )
        self.people = self.add_field("participants", "Participants", MemberList(members), required=True)
        self.title = self.add_field("title", "Objet", QLineEdit(placeholderText="ex. Réunion de rentrée"))
        self.message = self.add_field("body", "Message", _text("Votre message"), required=True)
        self.files = self.add_field("files", "Pièces jointes", AttachmentPicker(choose))
        self.people.list.itemChanged.connect(lambda _: self.refresh_state())
        self.message.textChanged.connect(self.refresh_state)
        self.finish()

    def missing_fields(self):
        missing = [] if self.people.ids else ["Participants"]
        return missing + ([] if self.message.toPlainText().strip() else ["Message"])

    def values(self):
        return {
            "participant_ids": self.people.ids,
            "title": self.title.text().strip(),
            "body": self.message.toPlainText().strip(),
            "files": self.files.files(),
        }


class AddParticipantDialog(FormDialog):
    """The administration brings in a colleague (the server only accepts administrators here)."""

    def __init__(self, members, parent=None):
        super().__init__("Ajouter un participant", "Seuls les administrateurs peuvent rejoindre.", parent, width=520)
        self.member = QComboBox()
        self.member.addItem("— choisir —", None)
        for member in members:
            self.member.addItem(member.label, member.id)
        self.member = self.add_field("member", "Membre", self.member, required=True)
        self.member.currentIndexChanged.connect(lambda _: self.refresh_state())
        self.finish()

    def missing_fields(self):
        return [] if self.member.currentData() else ["Membre"]

    def values(self):
        return {"member_id": self.member.currentData()}


class SpaceDialog(FormDialog):
    def __init__(self, classes, parent=None):
        super().__init__(
            "Nouvel espace de forum",
            "Les membres sont calculés par le serveur (rôles choisis, ou communauté d'une classe).",
            parent,
            width=560,
        )
        self.name = self.add_field("name", "Nom", QLineEdit(), required=True, width="medium")
        self.audience = QComboBox()
        for code, label in SPACE_AUDIENCES.items():
            self.audience.addItem(label, code)
        self.audience = self.add_field("audience", "Public", self.audience, required=True, width="medium")
        self.roles = {}
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        for code, label in FORUM_ROLES.items():
            self.roles[code] = QCheckBox(label)
            row.addWidget(self.roles[code])
        row.addStretch()
        self.add_field("roles", "Rôles (école)", holder)
        self.school_class = QComboBox()
        self.school_class.addItem("— choisir —", None)
        for school_class in classes:
            self.school_class.addItem(school_class.name, school_class.id)
        self.school_class = self.add_field("class", "Classe", self.school_class, width="medium")
        self.announcements = self.add_field(
            "announcements", "Usage", QCheckBox("Annonces seulement (seule l'administration publie)")
        )
        self.description = self.add_field("description", "Description", QLineEdit())
        self.name.textChanged.connect(self.refresh_state)
        self.audience.currentIndexChanged.connect(lambda _: self._audience())
        self.school_class.currentIndexChanged.connect(lambda _: self.refresh_state())
        for box in self.roles.values():
            box.toggled.connect(lambda _: self.refresh_state())
        self._audience()
        self.finish()

    def _audience(self):
        school = self.audience.currentData() == "SCHOOL"
        for box in self.roles.values():
            box.setEnabled(school)
        self.school_class.setEnabled(not school)
        self.refresh_state()

    def missing_fields(self):
        missing = [] if self.name.text().strip() else ["Nom"]
        if self.audience.currentData() == "SCHOOL" and not any(b.isChecked() for b in self.roles.values()):
            missing.append("Rôles")
        if self.audience.currentData() == "CLASS" and not self.school_class.currentData():
            missing.append("Classe")
        return missing

    def values(self):
        school = self.audience.currentData() == "SCHOOL"
        return {
            "name": self.name.text().strip(),
            "audience": self.audience.currentData(),
            "roles": [code for code, box in self.roles.items() if box.isChecked()] if school else [],
            "class_id": None if school else self.school_class.currentData(),
            "announcements_only": self.announcements.isChecked(),
            "description": self.description.text().strip(),
        }


class ThreadDialog(FormDialog):
    def __init__(self, spaces, parent=None, *, space_id=None):
        super().__init__("Publier", "Annonce ou discussion dans un espace du forum.", parent, save_text="Publier")
        self.space = QComboBox()
        for space in spaces:
            self.space.addItem(space.name, space.id)
        if space_id:
            self.space.setCurrentIndex(max(0, self.space.findData(space_id)))
        self.space = self.add_field("space", "Espace", self.space, required=True, width="medium")
        self.announcement = self.add_field("kind", "Type", QCheckBox("Annonce officielle"))
        self.announcement.setChecked(True)
        self.title = self.add_field("title", "Titre", QLineEdit(), required=True)
        self.message = self.add_field("body", "Texte", _text("Texte de la publication", 120), required=True)
        self.title.textChanged.connect(self.refresh_state)
        self.message.textChanged.connect(self.refresh_state)
        self.finish()

    def missing_fields(self):
        missing = [] if self.space.currentData() else ["Espace"]
        missing += [] if self.title.text().strip() else ["Titre"]
        return missing + ([] if self.message.toPlainText().strip() else ["Texte"])

    def values(self):
        return {
            "space_id": self.space.currentData(),
            "title": self.title.text().strip(),
            "body": self.message.toPlainText().strip(),
            "announcement": self.announcement.isChecked(),
        }


class ThreadViewDialog(FormDialog):
    """A thread and its posts. Buttons close it with `action` (reply, moderate,
    LOCKED / ARCHIVED / OPEN) — `post_id` for moderation, `text` for a reply."""

    def __init__(self, thread, posts, parent=None):
        super().__init__(
            thread.title,
            f"Par {thread.author_name} · {_when(thread.created_at)}",
            parent,
            save_text="Fermer",
            width=640,
        )
        self.cancel_button.hide()
        self.action = self.post_id = None
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.setMinimumHeight(180)
        for post in posts:
            if post.deleted:
                text = f"[Masqué par la modération{' : ' + post.deletion_reason if post.deletion_reason else ''}]"
                text = f"{post.author_name} · {_when(post.created_at)}\n{text}\n{post.body or ''}".rstrip()
            else:
                text = f"{post.author_name} · {_when(post.created_at)}\n{post.body}"
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, post.id)
            if post.deleted:
                item.setForeground(Qt.gray)
            self.list.addItem(item)
        self.add_field("posts", "Messages", self.list)
        self.reply_text = self.add_field("reply", "Répondre", _text("Votre réponse", 72))
        actions = QWidget()
        row = QHBoxLayout(actions)
        row.setContentsMargins(0, 0, 0, 0)
        self.buttons = {}
        for name, text, variant in (
            ("reply", "Répondre", "primary"),
            ("moderate", "Masquer le message…", "danger"),
            ("LOCKED", "Verrouiller", "secondary"),
            ("ARCHIVED", "Archiver", "secondary"),
            ("OPEN", "Rouvrir", "secondary"),
        ):
            widget = button(text, variant)
            widget.clicked.connect(lambda _=False, n=name: self._start(n))
            self.buttons[name] = widget
            row.addWidget(widget)
        row.addStretch()
        self.body.addWidget(actions)
        self.buttons["reply"].setEnabled(False)
        self.buttons["moderate"].setEnabled(False)
        if thread.status in self.buttons:  # already in that state
            self.buttons[thread.status].setEnabled(False)
        self.reply_text.textChanged.connect(
            lambda: self.buttons["reply"].setEnabled(bool(self.reply_text.toPlainText().strip()) and thread.active)
        )
        self.list.itemSelectionChanged.connect(
            lambda: self.buttons["moderate"].setEnabled(bool(self.list.selectedItems()))
        )
        self.finish(required_note=False)

    def _start(self, action):
        self.action = action
        items = self.list.selectedItems()
        self.post_id = items[0].data(Qt.UserRole) if items else None
        self.text = self.reply_text.toPlainText().strip()
        self.accept()


class ComplaintDialog(FormDialog):
    """Detail and history of a complaint. Buttons close it with `action`
    (status / cancel / attach) or `download` = the chosen attachment."""

    def __init__(self, complaint, names, parent=None):
        super().__init__(complaint.subject, "", parent, save_text="Fermer", width=640)
        self.cancel_button.hide()
        self.action = self.download = None
        name = lambda member: names.get(member, "—") if member else "—"  # noqa: E731
        self.body.addWidget(
            _grid(
                [
                    ("Statut", COMPLAINT_STATUSES.get(complaint.status, complaint.status)),
                    ("Catégorie", COMPLAINT_CATEGORIES.get(complaint.category, complaint.category)),
                    ("Priorité", COMPLAINT_PRIORITIES.get(complaint.priority, complaint.priority)),
                    ("Auteur", name(complaint.author_id)),
                    ("Assignée à", name(complaint.assigned_to)),
                    ("Créée le", _when(complaint.created_at)),
                ]
            )
        )
        description = QLabel(complaint.description)
        description.setWordWrap(True)
        self.add_section("Description")
        self.body.addWidget(description)
        self.add_section("Historique", "Chaque changement est conservé.")
        self.body.addWidget(
            _grid(
                [
                    (
                        _when(at),
                        f"{COMPLAINT_STATUSES.get(old, old or '—')} → {COMPLAINT_STATUSES.get(new, new)}"
                        f" · {name(by)}" + (f" — {comment}" if comment else ""),
                    )
                    for old, new, by, comment, at in complaint.history
                ]
            )
            if complaint.history
            else QLabel("Aucun changement.", objectName="help")
        )
        self.add_section("Pièces jointes")
        for attachment in complaint.attachments:
            link = button(f"Télécharger « {attachment.name} » ({attachment.size_label})")
            link.clicked.connect(lambda _=False, a=attachment: self._download(a))
            self.body.addWidget(link, 0, Qt.AlignLeft)
        if not complaint.attachments:
            self.body.addWidget(QLabel("Aucune pièce jointe.", objectName="help"))
        actions = QWidget()
        row = QHBoxLayout(actions)
        row.setContentsMargins(0, 0, 0, 0)
        self.buttons = {}
        for name_, text, variant in (
            ("status", "Changer le statut…", "primary"),
            ("attach", "Joindre…", "secondary"),
            ("cancel", "Annuler la réclamation…", "danger"),
        ):
            widget = button(text, variant)
            widget.clicked.connect(lambda _=False, n=name_: self._start(n))
            widget.setEnabled(complaint.status not in ("CANCELLED", "CLOSED"))
            self.buttons[name_] = widget
            row.addWidget(widget)
        row.addStretch()
        self.body.addWidget(actions)
        self.finish(required_note=False)

    def _start(self, action):
        self.action = action
        self.accept()

    def _download(self, attachment):
        self.action, self.download = "download", attachment
        self.accept()


class ComplaintStatusDialog(FormDialog):
    def __init__(self, complaint, assignees, parent=None):
        super().__init__(
            f"Réclamation — {complaint.subject}",
            "Le serveur vérifie la transition. Un motif est exigé pour résoudre, clôturer ou rouvrir.",
            parent,
            width=560,
        )
        self.new_status = QComboBox()
        self.new_status.addItem("— inchangé —", None)
        for code in COMPLAINT_NEXT.get(complaint.status, ()):
            self.new_status.addItem(COMPLAINT_STATUSES[code], code)
        self.new_status = self.add_field("status", "Nouveau statut", self.new_status, width="medium")
        self.assignee = QComboBox()
        self.assignee.addItem("— inchangé —", None)
        for member in assignees:
            self.assignee.addItem(member.label, member.id)
        self.assignee = self.add_field("assignee", "Assigner à", self.assignee, width="medium")
        self.reason = self.add_field("reason", "Motif / commentaire", _text("Motif", 72))
        self.new_status.currentIndexChanged.connect(lambda _: self.refresh_state())
        self.assignee.currentIndexChanged.connect(lambda _: self.refresh_state())
        self.finish(required_note=False)

    def missing_fields(self):
        return [] if (self.new_status.currentData() or self.assignee.currentData()) else ["Statut ou assignation"]

    def values(self):
        return {
            "status": self.new_status.currentData(),
            "assigned_to": self.assignee.currentData(),
            "reason": self.reason.toPlainText().strip(),
        }

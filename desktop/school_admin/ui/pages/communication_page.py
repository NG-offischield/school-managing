"""Gestion → Communication (ADR 0023): the admin face of the EXISTING
communication domain (ADR 0015). Tabs:

    Notifications   own notifications: unread / read, type filter, detail (marks read), all read
    Messagerie      conversations, participants, messages (+ private attachments), send,
                    read / unread, new conversation, add an administrator, hide a message
    Forum           spaces, announcements and threads: publish, reply, moderate, lock / archive
    Réclamations    list, detail with history and attachments, status / assignment, cancel, attach

Real time: the EXISTING `ws/v1/realtime/` endpoint (realtime.py) pushes
notifications and messages; after a reconnection the client resyncs what
it missed. Nothing is deleted: messages and posts are hidden, complaints
cancelled. Every permission is the server's.
"""

import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...api.errors import NetworkError
from ...i18n import Tr, tr
from ...models import (
    COMPLAINT_CATEGORIES,
    COMPLAINT_PRIORITIES,
    COMPLAINT_STATUSES,
    CONVERSATION_TYPES,
    NOTIFICATION_TYPES,
    SEVERITIES,
    THREAD_STATUSES,
    THREAD_TYPES,
    ChatMessage,
    Notification,
)
from ..dialogs.communication_dialogs import (
    AddParticipantDialog,
    AttachmentPicker,
    ComplaintDialog,
    ComplaintStatusDialog,
    NewConversationDialog,
    NotificationDialog,
    SpaceDialog,
    ThreadDialog,
    ThreadViewDialog,
    choose_files,
)
from ..dialogs.teacher_dialogs import ask_reason
from ..theme import TOKENS
from ..widgets import Page, button
from .catalog_base import STATUS_COLUMN_TITLE, CatalogPage, PagedCatalogPage
from .finance_page import coloured
from .planning_page import _combo, _refill


def _when(moment):
    return f"{moment:%d/%m/%Y %H:%M}" if moment else "—"


def _sort_key(moment):
    return moment.isoformat() if moment else ""


def ask_save_path(parent, name):
    path, _ = QFileDialog.getSaveFileName(parent, tr("Enregistrer le fichier"), name)
    return path


def save_bytes(path, content):
    with open(path, "wb") as handle:
        handle.write(content)


# =============================================================================
# Notifications
# =============================================================================


class NotificationsPage(PagedCatalogPage):
    title = Tr("Notifications")
    description = Tr("Vos notifications (paiements, réclamations, messages…). Elles arrivent en temps réel.")
    columns = Tr(["Reçue le", "Type", "Titre", "Message", "Importance", STATUS_COLUMN_TITLE])
    noun = "notification"
    search_placeholder = Tr("Filtrer l'affichage par titre…")
    status_filters = Tr([("Toutes", None), ("Non lues", False), ("Lues", True)])
    has_toggle = False
    narrow_hidden = (3, 4)

    def __init__(self, communication, runner, parent=None, **kwargs):
        self.communication = communication
        self.unread = 0
        super().__init__(runner, parent, **kwargs)
        self.add_button.hide()
        self.edit_button.hide()
        self.detail_button.clicked.connect(self.open_row)
        self.read_button.clicked.connect(self.mark_read)
        self.all_button.clicked.connect(self.mark_all)

    def stretch_columns(self):
        return {2, 3}

    def leading_actions(self):
        self.detail_button = button(tr("Détail"), tooltip=tr("Lire la notification (Entrée)"))
        return [self.detail_button]

    def extra_actions(self):
        self.read_button = button(tr("Marquer comme lue"))
        self.all_button = button(tr("Tout marquer comme lu"))
        return [self.read_button, self.all_button]

    def add_filters(self, layout):
        self.type_filter = _combo(tr("Filtrer par type"), tr("Type : tous"), 140)
        for code, label in NOTIFICATION_TYPES.items():
            self.type_filter.addItem(label, code)
        self.type_filter.currentIndexChanged.connect(lambda _: self.reload_first_page())
        layout.addWidget(self.type_filter)

    def update_extra_actions(self, row):
        if hasattr(self, "read_button"):
            self.detail_button.setEnabled(row is not None)
            self.read_button.setEnabled(row is not None and not row.is_read)

    def is_filtered(self):
        return self.status.currentData() is not None or bool(self.type_filter.currentData())

    def status_cell(self, row):
        return coloured(
            tr("Lue") if row.is_read else tr("●  Non lue"), TOKENS.text_secondary if row.is_read else TOKENS.primary
        )

    def fetch(self):
        rows, total = self.communication.notifications(
            page=self.page_number, is_read=self.status.currentData(), kind=self.type_filter.currentData()
        )
        search = self.search.text().strip().lower()
        if search:
            rows = [r for r in rows if search in r.title.lower()]
        return rows, total

    def cells(self, row):
        return [
            (_when(row.created_at), _sort_key(row.created_at)),
            row.kind_label,
            row.title,
            row.message,
            SEVERITIES.get(row.severity, row.severity),
            "",
        ]

    def ask(self, notification):
        NotificationDialog(notification, self).exec()

    def open_row(self):
        row = self.selected()
        if row is None:
            return
        self.ask(row)
        if not row.is_read:
            self.mark_read()

    def edit(self):
        self.open_row()

    def mark_read(self):
        row = self.selected()
        if row is not None and not row.is_read:
            self.call(
                lambda: self.communication.mark_read(row.id),
                lambda saved: self._reselect(saved.id, tr("Notification marquée comme lue.")),
                action=tr("Impossible de marquer la notification"),
            )

    def mark_all(self):
        self.call(
            self.communication.mark_all_read,
            lambda count: (self.success(tr("{0} notification(s) marquée(s) comme lue(s).", count)), self.reload()),
            action=tr("Impossible de marquer les notifications"),
        )

    # --- real time ---
    def pushed(self, data):
        """A notification pushed by the server: shown at once (first page)."""
        notification = Notification.from_api(data)
        self.banner.show_message("info", notification.message or notification.title, title=notification.title)
        if self.isVisible():
            self.reload()


# =============================================================================
# Messaging
# =============================================================================


class MessagingPage(Page):
    title = Tr("Messagerie")

    def __init__(self, communication, runner, parent=None, *, realtime=None, **kwargs):
        super().__init__(runner, parent, **kwargs)
        self.communication, self.realtime = communication, realtime
        self.conversations, self.messages, self.current = [], [], None
        self.pending = None  # (conversation, body, client_id): a send whose outcome is unknown
        self.choose_files, self.save_path = choose_files, ask_save_path

        head = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(QLabel(tr("Messagerie"), objectName="pageTitle"))
        subtitle = QLabel(tr("Conversations privées. Les pièces jointes restent privées."), objectName="subtitle")
        subtitle.setWordWrap(True)
        titles.addWidget(subtitle)
        head.addLayout(titles, 1)
        self.refresh_button = button(tr("Actualiser"), tooltip=tr("Recharger (F5)"))
        self.new_button = button(tr("Nouvelle conversation…"), "primary")
        for widget in (self.refresh_button, self.new_button):
            head.addWidget(widget, 0, Qt.AlignTop)
        self.layout_.addLayout(head)
        self.layout_.addWidget(self.banner)

        self.splitter = QSplitter(Qt.Horizontal)
        self.list = QListWidget()
        self.list.setAccessibleName(tr("Conversations"))
        self.list.setMinimumWidth(200)
        self.list.setWordWrap(True)  # long titles wrap: no horizontal scrolling
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        right = QWidget()
        column = QVBoxLayout(right)
        column.setContentsMargins(8, 0, 0, 0)
        self.header = QLabel(tr("Choisissez une conversation."), objectName="sectionTitle")
        self.header.setWordWrap(True)
        self.participants = QLabel("", objectName="help")
        self.participants.setWordWrap(True)
        self.thread = QListWidget()
        self.thread.setAccessibleName(tr("Messages"))
        self.thread.setWordWrap(True)
        self.thread.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        tools = QHBoxLayout()
        self.download_button = button(tr("Télécharger la pièce jointe…"))
        self.hide_button = button(tr("Masquer le message"), "danger")
        self.join_button = button(tr("Ajouter un administrateur…"))
        for widget in (self.download_button, self.hide_button, self.join_button):
            tools.addWidget(widget)
        tools.addStretch()
        self.compose = QPlainTextEdit(placeholderText=tr("Votre message"))
        self.compose.setFixedHeight(64)
        self.compose.setTabChangesFocus(True)
        self.attachments = AttachmentPicker(lambda parent: self.choose_files(parent))
        send_row = QHBoxLayout()
        send_row.addWidget(self.attachments, 1)
        self.send_button = button(tr("Envoyer"), "primary")
        send_row.addWidget(self.send_button)
        for widget in (self.header, self.participants, self.thread):
            column.addWidget(widget, 1 if widget is self.thread else 0)
        column.addLayout(tools)
        column.addWidget(self.compose)
        column.addLayout(send_row)
        self.splitter.addWidget(self.list)
        self.splitter.addWidget(right)
        self.splitter.setStretchFactor(1, 3)
        self.layout_.addWidget(self.splitter, 1)

        self.refresh_button.clicked.connect(self.reload)
        self.new_button.clicked.connect(self.new_conversation)
        self.list.currentRowChanged.connect(lambda _: self.open_current())
        self.thread.itemSelectionChanged.connect(self._update_actions)
        self.compose.textChanged.connect(self._update_actions)
        self.send_button.clicked.connect(self.send)
        self.download_button.clicked.connect(self.download)
        self.hide_button.clicked.connect(self.hide_message)
        self.join_button.clicked.connect(self.add_participant)
        if realtime is not None:
            realtime.message_created.connect(self.pushed)
            realtime.conversation_synced.connect(lambda cid, rows: [self.pushed(r) for r in rows])
        self._update_actions()

    def set_busy(self, busy):
        super().set_busy(busy)
        self.refresh_button.setEnabled(not busy)
        self._update_actions()

    def _update_actions(self):
        if not hasattr(self, "send_button"):
            return
        message = self.selected_message()
        self.send_button.setEnabled(
            self.current is not None and bool(self.compose.toPlainText().strip()) and not self.busy
        )
        self.download_button.setEnabled(bool(message and message.attachments))
        self.hide_button.setEnabled(bool(message and not message.deleted))
        self.join_button.setEnabled(self.current is not None)
        self.new_button.setEnabled(not self.busy)

    # --- conversations ---
    def reload(self):
        self.call(
            self.communication.conversations,
            self.show_conversations,
            action=tr("Impossible de charger les conversations"),
        )

    def show_conversations(self, conversations):
        chosen = self.current.id if self.current else None
        self.conversations = conversations
        self.list.blockSignals(True)
        self.list.clear()
        for conversation in conversations:
            unread = f"  ●{conversation.unread}" if conversation.unread else ""
            item = QListWidgetItem(
                f"{conversation.label}{unread}\n{CONVERSATION_TYPES.get(conversation.kind, conversation.kind)}"
                f" · {_when(conversation.last_message_at)}"
            )
            item.setData(Qt.UserRole, conversation.id)
            self.list.addItem(item)
            if conversation.id == chosen:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        if not conversations:
            self.header.setText(tr("Aucune conversation. « Nouvelle conversation… » pour écrire."))

    def select(self, conversation_id):
        for index in range(self.list.count()):
            if self.list.item(index).data(Qt.UserRole) == conversation_id:
                self.list.setCurrentRow(index)
                return

    def open_current(self):
        item = self.list.currentItem()
        conversation = next((c for c in self.conversations if item and c.id == item.data(Qt.UserRole)), None)
        if conversation is None:
            return
        if self.current is not None and self.realtime is not None and self.current.id != conversation.id:
            self.realtime.unwatch(self.current.id)
        self.current = conversation
        self.header.setText(f"{conversation.label} — {CONVERSATION_TYPES.get(conversation.kind, conversation.kind)}")
        self.participants.setText(tr("Participants : ") + ", ".join(name for _, name, _ in conversation.participants))
        self.call(
            lambda: (
                self.communication.messages(conversation.id),
                self.communication.mark_conversation_read(conversation.id),
            ),
            lambda loaded: self.show_messages(loaded[0]),
            action=tr("Impossible de charger les messages"),
        )

    def show_messages(self, messages):
        self.messages = messages
        self.thread.clear()
        for message in messages:
            self._append(message)
        if self.realtime is not None and self.current is not None:
            last = messages[-1].created_at.isoformat() if messages and messages[-1].created_at else None
            self.realtime.watch(self.current.id, since=last)
        self._update_actions()

    def _append(self, message):
        files = "".join(f"\n📎 {a.name} ({a.size_label})" for a in message.attachments)
        body = tr("[Message masqué]") if message.deleted and message.body is None else (message.body or "")
        if message.deleted and message.body is not None:
            body = tr("[Masqué — visible par l'administration] {0}", body)
        item = QListWidgetItem(f"{message.sender_name} · {_when(message.created_at)}\n{body}{files}")
        item.setData(Qt.UserRole, message.id)
        if message.deleted:
            item.setForeground(Qt.gray)
        self.thread.addItem(item)
        self.thread.scrollToBottom()

    def selected_message(self):
        items = self.thread.selectedItems() if hasattr(self, "thread") else []
        if not items:
            return None
        return next((m for m in self.messages if m.id == items[0].data(Qt.UserRole)), None)

    # --- real time ---
    def pushed(self, data):
        message = ChatMessage.from_api(data)
        if self.current is not None and message.conversation_id == self.current.id:
            if all(m.id != message.id for m in self.messages):
                self.messages.append(message)
                self._append(message)
                if self.realtime is not None:
                    self.realtime._send({"type": "read", "conversation": self.current.id})
        elif self.isVisible():
            self.reload()  # unread counters of the other conversations

    # --- actions ---
    def ask(self, kind, **context):
        if kind == "new":
            dialog = NewConversationDialog(context["members"], self, choose=lambda parent: self.choose_files(parent))
        else:
            dialog = AddParticipantDialog(context["members"], self)
        return dialog.values() if dialog.exec() == QDialog.Accepted else None

    def new_conversation(self):
        def open_form(members):
            values = self.ask("new", members=members)
            if values:
                self.call(
                    lambda: self.communication.start_conversation(**values),
                    lambda conversation: self._started(conversation),
                    action=tr("Impossible de créer la conversation"),
                )

        self.call(self.communication.members, open_form, action=tr("Impossible de charger les membres"))

    def _started(self, conversation):
        self.success(tr("Conversation « {0} » créée.", conversation.label))
        self.call(
            self.communication.conversations,
            lambda rows: (self.show_conversations(rows), self.select(conversation.id)),
            action=tr("Impossible de charger les conversations"),
        )

    def send(self):
        if self.current is None:
            return
        body = self.compose.toPlainText().strip()
        conversation = self.current
        same = self.pending and self.pending[0] == conversation.id and self.pending[1] == body
        client_id = self.pending[2] if same else str(uuid.uuid4())
        files = self.attachments.files()

        def attempt():
            try:
                return self.communication.send(conversation.id, body, files=files, client_id=client_id)
            except NetworkError:
                self.pending = (conversation.id, body, client_id)  # resend = same client_id, no duplicate
                raise

        self.call(attempt, self._sent, action=tr("Message non envoyé"))

    def _sent(self, message):
        self.pending = None
        self.compose.clear()
        self.attachments.paths = []
        self.attachments.label.setText(tr("Aucun fichier"))
        if all(m.id != message.id for m in self.messages):
            self.messages.append(message)
            self._append(message)
        self._update_actions()

    def download(self):
        message = self.selected_message()
        if message is None or not message.attachments:
            return
        for attachment in message.attachments:
            path = self.save_path(self, attachment.name)
            if not path:
                continue
            self.call(
                lambda a=attachment: self.communication.download(a),
                lambda content, p=path: (save_bytes(p, content), self.success(tr("Pièce jointe enregistrée."))),
                action=tr("Impossible de télécharger la pièce jointe"),
            )

    def hide_message(self):
        message = self.selected_message()
        if message is None:
            return
        if not self.confirm(
            self,
            tr("Masquer ce message ?"),
            tr("Il ne sera plus visible des participants. Il reste conservé pour l'administration (jamais détruit)."),
            confirm_text=tr("Masquer"),
            danger=True,
        ):
            return
        self.call(
            lambda: self.communication.hide_message(message.id),
            lambda _: (self.success(tr("Message masqué (conservé).")), self.open_current()),
            action=tr("Impossible de masquer le message"),
        )

    def add_participant(self):
        if self.current is None:
            return
        conversation = self.current

        def open_form(members):
            values = self.ask("join", members=members)
            if values:
                self.call(
                    lambda: self.communication.add_participant(conversation.id, values["member_id"]),
                    lambda saved: (self.success(tr("Participant ajouté.")), self.reload()),
                    action=tr("Impossible d'ajouter le participant"),
                )

        self.call(
            lambda: self.communication.members(role="ADMIN"), open_form, action=tr("Impossible de charger les membres")
        )


# =============================================================================
# Forum
# =============================================================================


class ForumPage(CatalogPage):
    title = Tr("Forum et annonces")
    description = Tr("Espaces de discussion et annonces. La modération masque un message sans le détruire.")
    columns = Tr(["Titre", "Espace", "Type", "Auteur", "Dernier message", STATUS_COLUMN_TITLE])
    noun = "sujet"
    feminine = False
    search_placeholder = Tr("Rechercher un sujet…")
    status_filters = Tr([("Statut : tous", None), *((label, code) for code, label in THREAD_STATUSES.items())])
    has_toggle = False
    narrow_hidden = (3,)

    def __init__(self, communication, references, runner, parent=None, **kwargs):
        self.communication, self.references = communication, references
        self.spaces = []
        super().__init__(runner, parent, **kwargs)
        self.edit_button.hide()
        self.add_button.setText(tr("Publier…"))
        self.open_button.clicked.connect(self.open_row)
        self.space_button.clicked.connect(self.new_space)

    def stretch_columns(self):
        return {0}

    def leading_actions(self):
        self.open_button = button(tr("Ouvrir"), tooltip=tr("Lire, répondre, modérer (Entrée)"))
        return [self.open_button]

    def extra_actions(self):
        self.space_button = button(tr("Nouvel espace…"))
        return [self.space_button]

    def add_filters(self, layout):
        self.space_filter = _combo(tr("Filtrer par espace"), tr("Espace : tous"), 150)
        self.space_filter.currentIndexChanged.connect(lambda _: self.reload())
        layout.addWidget(self.space_filter)

    def update_extra_actions(self, row):
        if hasattr(self, "open_button"):
            self.open_button.setEnabled(row is not None)

    def is_filtered(self):
        return super().is_filtered() or bool(self.space_filter.currentData())

    def status_cell(self, row):
        return coloured(
            THREAD_STATUSES.get(row.status, row.status), TOKENS.success if row.active else TOKENS.text_secondary
        )

    def fetch(self):
        self.spaces = self.communication.spaces()
        _refill(self.space_filter, tr("Espace : tous"), [(s.name, s.id) for s in self.spaces])
        rows = self.communication.threads(space_id=self.space_filter.currentData())
        wanted = self.status.currentData()
        if wanted:
            rows = [r for r in rows if r.status == wanted]
        search = self.search.text().strip().lower()
        return [r for r in rows if search in r.title.lower()] if search else rows

    def cells(self, row):
        names = {s.id: s.name for s in self.spaces}
        return [
            row.title,
            names.get(row.space_id, "—"),
            THREAD_TYPES.get(row.kind, row.kind),
            row.author_name,
            (_when(row.last_post_at or row.created_at), _sort_key(row.last_post_at or row.created_at)),
            "",
        ]

    def ask(self, kind, **context):
        if kind == "space":
            dialog = SpaceDialog(context["classes"], self)
            return dialog.values() if dialog.exec() == QDialog.Accepted else None
        if kind == "publish":
            dialog = ThreadDialog(self.spaces, self, space_id=self.space_filter.currentData())
            return dialog.values() if dialog.exec() == QDialog.Accepted else None
        if kind == "moderate":
            return ask_reason(self, tr("Masquer ce message ?"), tr("Il reste conservé, avec le motif."), danger=True)
        dialog = ThreadViewDialog(context["thread"], context["posts"], self)
        if dialog.exec() != QDialog.Accepted or not dialog.action:
            return None
        return {"action": dialog.action, "post_id": dialog.post_id, "text": dialog.text}

    def add(self):
        if not self.spaces:
            self.banner.show_message("warning", tr("Créez d'abord un espace (« Nouvel espace… »)."))
            return
        values = self.ask("publish")
        if values:
            self.call(
                lambda: self.communication.publish(**values),
                lambda thread: self._saved(thread, tr("publié")),
                action=tr("Impossible de publier"),
            )

    def new_space(self):
        def open_form(classes):
            values = self.ask("space", classes=classes)
            if values:
                self.call(
                    lambda: self.communication.create_space(**values),
                    lambda space: (self.success(tr("Espace « {0} » créé.", space.name)), self.reload()),
                    action=tr("Impossible de créer l'espace"),
                )

        self.call(self.references.classes, open_form, action=tr("Impossible de charger les classes"))

    def open_row(self):
        row = self.selected()
        if row is None:
            return

        def show(posts):
            choice = self.ask("thread", thread=row, posts=posts)
            if choice:
                self.thread_action(row, choice)

        self.call(lambda: self.communication.posts(row.id), show, action=tr("Impossible de charger le sujet"))

    def edit(self):
        self.open_row()

    def thread_action(self, thread, choice):
        action = choice["action"]
        if action == "reply":
            self.call(
                lambda: self.communication.reply(thread.id, choice["text"]),
                lambda _: self._saved(thread, tr("complété (réponse publiée)")),
                action=tr("Impossible de répondre"),
            )
        elif action == "moderate":
            values = self.ask("moderate")
            if values and choice.get("post_id"):
                self.call(
                    lambda: self.communication.moderate_post(choice["post_id"], values["reason"]),
                    lambda _: self.success(tr("Message masqué par la modération (conservé).")),
                    action=tr("Impossible de modérer le message"),
                )
        else:
            self.call(
                lambda: self.communication.set_thread_status(thread.id, action, choice.get("text")),
                lambda saved: self._saved(saved, THREAD_STATUSES.get(saved.status, saved.status).lower()),
                action=tr("Impossible de changer le statut du sujet"),
            )

    def _saved(self, saved, verb):
        self.success(tr("Sujet « {0} » {1}.", saved.title, verb))
        self.call(
            self.fetch,
            lambda rows: (self.show_rows(rows), self.select_id(saved.id)),
            action=tr("Impossible de charger"),
        )


# =============================================================================
# Complaints
# =============================================================================


class ComplaintsPage(CatalogPage):
    title = Tr("Réclamations")
    description = Tr("Traitement des réclamations. Chaque changement est historisé ; rien n'est supprimé.")
    columns = Tr(["Sujet", "Catégorie", "Priorité", "Auteur", "Créée le", STATUS_COLUMN_TITLE])
    noun = "réclamation"
    search_placeholder = Tr("Rechercher par sujet ou auteur…")
    status_filters = Tr([("Statut : tous", None), *((label, code) for code, label in COMPLAINT_STATUSES.items())])
    has_toggle = False
    narrow_hidden = (2, 4)

    def __init__(self, communication, runner, parent=None, **kwargs):
        self.communication = communication
        self.members = []
        self.choose_files, self.save_path = choose_files, ask_save_path
        super().__init__(runner, parent, **kwargs)
        self.add_button.hide()
        self.edit_button.hide()
        self.detail_button.clicked.connect(self.open_row)
        self.status_button.clicked.connect(lambda: self.complaint_action("status"))
        self.cancel_button.clicked.connect(lambda: self.complaint_action("cancel"))
        self.attach_button.clicked.connect(lambda: self.complaint_action("attach"))

    def stretch_columns(self):
        return {0}

    def leading_actions(self):
        self.detail_button = button(tr("Détail"), tooltip=tr("Détail et historique (Entrée)"))
        return [self.detail_button]

    def extra_actions(self):
        self.cancel_button = button(tr("Annuler…"), "danger")
        self.attach_button = button(tr("Joindre…"))
        self.status_button = button(tr("Changer le statut…"), "primary")
        return [self.cancel_button, self.attach_button, self.status_button]

    def add_filters(self, layout):
        self.category_filter = _combo(tr("Filtrer par catégorie"), tr("Catégorie : toutes"), 150)
        for code, label in COMPLAINT_CATEGORIES.items():
            self.category_filter.addItem(label, code)
        self.category_filter.currentIndexChanged.connect(lambda _: self.reload())
        layout.addWidget(self.category_filter)

    def update_extra_actions(self, row):
        if hasattr(self, "status_button"):
            live = row is not None and row.status not in ("CANCELLED", "CLOSED")
            self.detail_button.setEnabled(row is not None)
            for widget in (self.status_button, self.cancel_button, self.attach_button):
                widget.setEnabled(live)
                widget.setToolTip("" if live else tr("Réclamation finale (annulée ou clôturée) : consultation seule."))

    def is_filtered(self):
        return super().is_filtered() or bool(self.category_filter.currentData())

    def status_cell(self, row):
        colour = {"OPEN": TOKENS.warning, "IN_PROGRESS": TOKENS.primary, "RESOLVED": TOKENS.success}.get(
            row.status, TOKENS.text_secondary
        )
        return coloured(row.status_label, colour)

    @property
    def names(self):
        return {m.id: m.name for m in self.members}

    def fetch(self):
        if not self.members:
            self.members = self.communication.members()
        rows = self.communication.complaints(
            status=self.status.currentData(), category=self.category_filter.currentData()
        )
        search = self.search.text().strip().lower()
        if search:
            rows = [r for r in rows if search in f"{r.subject} {self.names.get(r.author_id, '')}".lower()]
        return rows

    def cells(self, row):
        return [
            row.subject,
            COMPLAINT_CATEGORIES.get(row.category, row.category),
            COMPLAINT_PRIORITIES.get(row.priority, row.priority),
            self.names.get(row.author_id, "—"),
            (_when(row.created_at), _sort_key(row.created_at)),
            "",
        ]

    def describe_row(self, row):
        return row.subject

    def ask(self, kind, **context):
        if kind == "detail":
            dialog = ComplaintDialog(context["complaint"], self.names, self)
            if dialog.exec() != QDialog.Accepted:
                return None
            return {"action": dialog.action, "attachment": dialog.download}
        if kind == "status":
            assignees = [m for m in self.members if {"ADMIN", "SUPER_ADMIN", "TEACHER", "STAFF"} & set(m.roles)]
            dialog = ComplaintStatusDialog(context["complaint"], assignees, self)
            return dialog.values() if dialog.exec() == QDialog.Accepted else None
        if kind == "cancel":
            return ask_reason(self, tr("Annuler la réclamation ?"), tr("Elle reste dans l'historique."), danger=True)
        return None

    def open_row(self):
        row = self.selected()
        if row is None:
            return

        def show(complaint):
            choice = self.ask("detail", complaint=complaint)
            if choice and choice["action"] == "download":
                self.download(choice["attachment"])
            elif choice and choice["action"]:
                self.complaint_action(choice["action"], complaint)

        self.call(lambda: self.communication.complaint(row.id), show, action=tr("Impossible de charger la réclamation"))

    def edit(self):
        self.open_row()

    def complaint_action(self, action, complaint=None):
        row = complaint or self.selected()
        if row is None:
            return
        if action == "status":
            values = self.ask("status", complaint=row)
            if values:
                self.call(
                    lambda: self.communication.change_status(row.id, **values),
                    lambda saved: self._done(
                        saved, tr("Réclamation « {0} » : {1}.", saved.subject, saved.status_label.lower())
                    ),
                    action=tr("Impossible de changer le statut"),
                )
        elif action == "cancel":
            values = self.ask("cancel", complaint=row)
            if values:
                self.call(
                    lambda: self.communication.cancel_complaint(row.id, values["reason"]),
                    lambda saved: self._done(
                        saved, tr("Réclamation « {0} » annulée (historique conservé).", saved.subject)
                    ),
                    action=tr("Impossible d'annuler la réclamation"),
                )
        elif action == "attach":
            paths = self.choose_files(self)
            if paths:
                from ...services.communication import read_attachment

                files = [read_attachment(p) for p in paths]
                self.call(
                    lambda: self.communication.attach_to_complaint(row.id, files),
                    lambda count: self.success(tr("{0} pièce(s) jointe(s) ajoutée(s).", count)),
                    action=tr("Pièce jointe refusée"),
                )

    def download(self, attachment):
        path = self.save_path(self, attachment.name)
        if path:
            self.call(
                lambda: self.communication.download(attachment),
                lambda content: (save_bytes(path, content), self.success(tr("« {0} » enregistré.", attachment.name))),
                action=tr("Impossible de télécharger la pièce jointe"),
            )

    def _done(self, saved, message):
        self.success(message)
        self.call(
            self.fetch,
            lambda rows: (self.show_rows(rows), self.select_id(saved.id)),
            action=tr("Impossible de charger"),
        )


# =============================================================================
# The page
# =============================================================================


class CommunicationPage(Page):
    title = Tr("Communication")

    def __init__(self, communication, references, runner, parent=None, *, realtime=None, **kwargs):
        super().__init__(runner, parent, **kwargs)
        self.realtime = realtime
        self.layout_.setContentsMargins(0, 8, 0, 0)
        self.live = QLabel("", objectName="subtitle")
        self.live.setContentsMargins(28, 0, 28, 0)
        self.layout_.addWidget(self.live)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.notifications = NotificationsPage(communication, runner, **kwargs)
        self.messaging = MessagingPage(communication, runner, realtime=realtime, **kwargs)
        self.forum = ForumPage(communication, references, runner, **kwargs)
        self.complaints = ComplaintsPage(communication, runner, **kwargs)
        for page, label in (
            (self.notifications, tr("Notifications")),
            (self.messaging, tr("Messagerie")),
            (self.forum, tr("Forum")),
            (self.complaints, tr("Réclamations")),
        ):
            self.tabs.addTab(page, label)
            page.session_expired.connect(self.session_expired.emit)
        self.layout_.addWidget(self.tabs)
        self.tabs.currentChanged.connect(lambda _: self.tabs.currentWidget().activate())
        self.set_live(realtime.state if realtime is not None else "disabled")
        if realtime is not None:
            realtime.state_changed.connect(self.set_live)
            realtime.unread_changed.connect(self.set_unread)
            realtime.notification.connect(self.notifications.pushed)
            realtime.notification.connect(lambda _: self.set_unread(self.notifications.unread + 1))

    def set_live(self, state):
        self.live.setText(
            {
                "online": tr("● Temps réel connecté"),
                "connecting": tr("○ Connexion temps réel…"),
                "offline": tr("○ Temps réel hors ligne : nouvelle tentative automatique"),
                "expired": tr("○ Session expirée"),
                "disabled": tr("Temps réel désactivé : utilisez « Actualiser »."),
            }.get(state, "")
        )

    def set_unread(self, count):
        self.notifications.unread = count
        self.tabs.setTabText(0, tr("Notifications ({0})", count) if count else tr("Notifications"))

    def activate(self):
        self.tabs.currentWidget().activate()

    def open_tab(self, name):
        page = getattr(self, name)
        self.tabs.setCurrentWidget(page)
        return page

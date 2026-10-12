"""Gestion académique → Parents (ADR 0026): what the parent app asks, decided
by the school.

    Inscriptions   accounts created from the app (membership pending):
                   Valider (parent role + profile) · Refuser… (motif)
    Rattachements  « this is my child » requests: Vérifier l'identité… (the
                   ORIGINAL document shown at the counter) · Désignation par
                   l'élève… · Valider le rattachement… (rights) · Refuser…

No rule lives here: identity match, pupil's approval, sponsor's rights and
school isolation are checked by the server, whose refusals are explained in
the banner.
"""

from PySide6.QtWidgets import QDialog, QTabWidget

from ...models import LINK_REQUEST_STATUSES, REGISTRATION_STATUSES
from ..dialogs.parent_dialogs import IdentityCheckDialog, LinkApprovalDialog, LinkRequestDialog, StudentApprovalDialog
from ..dialogs.teacher_dialogs import ReasonDialog
from ..theme import TOKENS, TokenColours
from ..widgets import Page, button
from .catalog_base import STATUS_COLUMN_TITLE, PagedCatalogPage
from .finance_page import coloured

COLOURS = TokenColours(PENDING="warning", APPROVED="success", REJECTED="danger")


def _when(moment):
    return (f"{moment:%d/%m/%Y %H:%M}" if moment else "—", moment.isoformat() if moment else "")


class _DecisionPage(PagedCatalogPage):
    has_toggle = False
    feminine = True

    def __init__(self, parents, runner, parent=None, **kwargs):
        self.parents = parents
        super().__init__(runner, parent, **kwargs)
        self.edit_button.hide()
        self.add_button.hide()

    def status_cell(self, row):
        return coloured(row.status_label, COLOURS.get(row.status, TOKENS.text_secondary))

    def is_filtered(self):
        return bool(self.search.text().strip()) or self.status.currentData() != "PENDING"

    def add(self):  # Ctrl+N: nothing to create here (requests come from the app)
        pass

    def _reason(self, title, instruction):
        return self.ask("reason", title=title, instruction=instruction)


class RegistrationsPage(_DecisionPage):
    title = "Inscriptions"
    description = "Comptes parents créés depuis l'application : validez-les après avoir reconnu la personne."
    columns = ["Demandeur", "E-mail", "Téléphone", "Reçue le", STATUS_COLUMN_TITLE]
    noun = "inscription"
    search_placeholder = "Rechercher par nom ou e-mail…"
    status_filters = [
        ("En attente", "PENDING"),
        *((label, code) for code, label in REGISTRATION_STATUSES.items() if code != "PENDING"),
        ("Toutes", None),
    ]
    narrow_hidden = (2,)

    def stretch_columns(self):
        return {0}

    def extra_actions(self):
        self.reject_button = button("Refuser…", "danger")
        self.approve_button = button("Valider", "primary", tooltip="Activer le compte parent")
        self.reject_button.clicked.connect(lambda: self.reject(self.selected()))
        self.approve_button.clicked.connect(lambda: self.approve(self.selected()))
        return [self.reject_button, self.approve_button]

    def update_extra_actions(self, row):
        if hasattr(self, "approve_button"):
            pending = row is not None and row.status == "PENDING"
            why = "" if pending else "Sélectionnez une inscription en attente."
            for widget in (self.approve_button, self.reject_button):
                widget.setEnabled(pending)
                widget.setToolTip(why or widget.text().rstrip("…"))

    def fetch(self):
        return self.parents.registrations(
            page=self.page_number, status=self.status.currentData(), search=self.search.text()
        )

    def cells(self, row):
        return [row.applicant_name, row.email, row.phone or "—", _when(row.submitted_at), ""]

    def describe_row(self, row):
        return f"{row.applicant_name} ({row.email})"

    def open_row(self):
        self.approve(self.selected())

    def edit(self):
        self.open_row()

    def ask(self, kind, **context):
        dialog = ReasonDialog(context["title"], context["instruction"], self, save_text="Refuser", danger=True)
        return dialog.values() if dialog.exec() == QDialog.Accepted else None

    def approve(self, row):
        if row is None or row.status != "PENDING":
            return
        if not self.confirm(
            self,
            "Valider l'inscription ?",
            f"{self.describe_row(row)} pourra se connecter comme parent. Il devra ensuite demander le "
            "rattachement de son enfant (vérification d'identité à l'école).",
            confirm_text="Valider",
        ):
            return
        self.call(
            lambda: self.parents.approve_registration(row.id),
            lambda saved: self._reselect(saved.id, f"Inscription de {saved.applicant_name} validée."),
            action="Impossible de valider l'inscription",
        )

    def reject(self, row):
        if row is None or row.status != "PENDING":
            return
        values = self._reason("Refuser l'inscription ?", f"{self.describe_row(row)} ne pourra plus se connecter.")
        if values:
            self.call(
                lambda: self.parents.reject_registration(row.id, values["reason"]),
                lambda saved: self._reselect(saved.id, f"Inscription de {saved.applicant_name} refusée."),
                action="Impossible de refuser l'inscription",
            )


class LinkRequestsPage(_DecisionPage):
    title = "Rattachements"
    description = (
        "Demandes « c'est mon enfant » : identité vérifiée sur pièce originale, désignation par l'élève, "
        "puis décision de l'école avec les droits du parent."
    )
    columns = ["Élève", "Classe", "Parent", "Lien", "Identité", "Désignation", STATUS_COLUMN_TITLE]
    noun = "demande"
    search_placeholder = "Rechercher par élève ou parent…"
    status_filters = [
        ("En cours", "PENDING"),
        *((label, code) for code, label in LINK_REQUEST_STATUSES.items() if code != "PENDING"),
        ("Toutes", None),
    ]
    narrow_hidden = (1, 3, 5)

    def stretch_columns(self):
        return {0, 2}

    def leading_actions(self):
        self.detail_button = button("Traiter…", tooltip="Fiche de la demande et actions (Entrée)")
        self.detail_button.clicked.connect(self.open_row)
        return [self.detail_button]

    def update_extra_actions(self, row):
        if hasattr(self, "detail_button"):
            self.detail_button.setEnabled(row is not None)

    def fetch(self):
        return self.parents.link_requests(
            page=self.page_number, status=self.status.currentData(), search=self.search.text()
        )

    def cells(self, row):
        return [
            row.student_name,
            row.class_name or "—",
            row.parent_name,
            row.relationship_label,
            row.identity_label,
            row.approval_label,
            "",
        ]

    def describe_row(self, row):
        return f"{row.parent_name} → {row.student_name}"

    def edit(self):
        self.open_row()

    # --- dialogs (overridable in tests) ---
    def ask(self, kind, **context):
        request = context.get("request")
        if kind == "record":
            dialog = LinkRequestDialog(request, self)
            return dialog.action if dialog.exec() == QDialog.Accepted else None
        if kind == "reason":
            dialog = ReasonDialog(context["title"], context["instruction"], self, save_text="Refuser", danger=True)
        else:
            dialog = {
                "identity": IdentityCheckDialog,
                "student_approval": StudentApprovalDialog,
                "approve": LinkApprovalDialog,
            }[kind](request, self)
        return dialog.values() if dialog.exec() == QDialog.Accepted else None

    def open_row(self):
        row = self.selected()
        if row is None:
            return

        def show(request):
            action = self.ask("record", request=request)
            handler = {
                "verify_identity": self.verify_identity,
                "student_approval": self.student_approval,
                "approve": self.approve,
                "reject": self.reject,
            }.get(action)
            if handler is not None:
                handler(request)

        self.call(lambda: self.parents.link_request(row.id), show, action="Impossible de charger la demande")

    def _done(self, message):
        return lambda saved: self._reselect(saved.id, message(saved))

    def verify_identity(self, request):
        values = self.ask("identity", request=request)
        if values:
            self.call(
                lambda: self.parents.verify_identity(request.id, values["document_type"], values["document_number"]),
                self._done(lambda saved: f"Identité de {saved.parent_name} vérifiée."),
                action="Identité non vérifiée",
            )

    def student_approval(self, request):
        values = self.ask("student_approval", request=request)
        if values:
            self.call(
                lambda: self.parents.record_student_approval(request.id, values["decision"], values["note"]),
                self._done(lambda saved: f"Réponse de l'élève enregistrée : {saved.approval_label.lower()}."),
                action="Impossible d'enregistrer la réponse de l'élève",
            )

    def approve(self, request):
        values = self.ask("approve", request=request)
        if values:
            self.call(
                lambda: self.parents.approve(request.id, **values),
                self._done(lambda saved: f"{saved.parent_name} est maintenant parent vérifié de {saved.student_name}."),
                action="Impossible de valider le rattachement",
            )

    def reject(self, request):
        values = self._reason("Refuser le rattachement ?", f"{self.describe_row(request)} : aucun accès ne sera donné.")
        if values:
            self.call(
                lambda: self.parents.reject(request.id, values["reason"]),
                self._done(lambda saved: f"Rattachement {saved.parent_name} → {saved.student_name} refusé."),
                action="Impossible de refuser le rattachement",
            )


class ParentsPage(Page):
    title = "Parents"

    def __init__(self, parents, runner, parent=None, **kwargs):
        super().__init__(runner, parent, **kwargs)
        self.layout_.setContentsMargins(0, 8, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.registrations = RegistrationsPage(parents, runner, **kwargs)
        self.links = LinkRequestsPage(parents, runner, **kwargs)
        for page, label in ((self.links, "Rattachements"), (self.registrations, "Inscriptions")):
            self.tabs.addTab(page, label)
            page.session_expired.connect(self.session_expired.emit)
        self.layout_.addWidget(self.tabs)
        self.tabs.currentChanged.connect(lambda _: self.tabs.currentWidget().activate())

    def activate(self):
        self.tabs.currentWidget().activate()

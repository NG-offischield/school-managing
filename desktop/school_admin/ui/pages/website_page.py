"""Gestion → Site ISBREE (ADR 0032): administration of the public site and of
the Espace ISBREE portal, through the API only.

    Préinscriptions · Pages · FAQ · Actualités · Images · Ressources · Lieux · Applications · Profil et publication

- Préinscriptions (administrators): detail, status changes among those the
  server allows, invitation link shown ONCE (nothing is e-mailed). Accepting
  a request never enrolls the child nor links it to the family.
- Contents (administrators and content managers): create, edit, publish,
  archive — nothing is deleted. A provisional or demonstration content stays
  flagged as such for the readers.
- Applications: only a signed release APK is accepted by the server.
- Profil et publication: the school presentation, and what still prevents an
  opening (readiness report of the server).

Hooks (ask / choose_file / show_invitation) are overridable in tests.
"""

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...i18n import Texts, Tr, tr
from ...services.website import (
    APK_FILTER,
    FAQ_CATEGORIES,
    IMAGE_CATEGORIES,
    IMAGE_FILTER,
    NEWS_CATEGORIES,
    PAGE_KINDS,
    PDF_FILTER,
    PRE_ENROLLMENT_STATUSES,
    PUBLICATION_STATUSES,
    READINESS,
    RESOURCE_KINDS,
)
from ..dialogs.website_dialogs import (
    ContentDialog,
    InvitationDialog,
    PreEnrollmentDialog,
    ReleaseDialog,
    StatusDialog,
)
from ..theme import TOKENS, TokenColours
from ..widgets import Page, button
from .catalog_base import STATUS_COLUMN_TITLE, CatalogPage, PagedCatalogPage
from .finance_page import coloured

REQUEST_COLOURS = TokenColours(
    RECEIVED="warning", UNDER_REVIEW="warning", INFO_REQUESTED="warning", ACCEPTED="success", REJECTED="text_secondary"
)
PUBLICATION_COLOURS = TokenColours(PUBLISHED="success", DRAFT="warning", ARCHIVED="text_secondary")


def choose_file(parent, title, file_filter):
    path, _ = QFileDialog.getOpenFileName(parent, title, "", file_filter)
    return path


def _when(moment, with_time=False):
    if not moment:
        return ("—", "")
    return (f"{moment:%d/%m/%Y %H:%M}" if with_time else f"{moment:%d/%m/%Y}", moment.isoformat())


def _size(size):
    return f"{size / 1024 / 1024:.1f} Mo" if size >= 1024 * 1024 else f"{max(1, size // 1024)} Ko"


# =============================================================================
# Pre-enrollments
# =============================================================================


class PreEnrollmentsPage(PagedCatalogPage):
    title = Tr("Préinscriptions")
    description = Tr(
        "Demandes envoyées par les familles depuis le site. Accepter une demande permet d'inviter la famille dans "
        "son Espace ISBREE ; l'inscription de l'élève reste à faire dans « Élèves »."
    )
    columns = Tr(["Référence", "Responsable", "Enfant", "Niveau demandé", "Reçue le", STATUS_COLUMN_TITLE])
    noun = "demande"
    search_placeholder = Tr("Rechercher par référence, nom ou e-mail…")
    status_filters = Tr([("Statut : tous", None), *((label, code) for code, label in PRE_ENROLLMENT_STATUSES.items())])
    has_toggle = False
    narrow_hidden = (3, 4)

    def __init__(self, service, runner, parent=None, **kwargs):
        self.service = service
        self.show_invitation = lambda result: InvitationDialog(result, self).exec()
        super().__init__(runner, parent, **kwargs)
        self.edit_button.hide()
        self.add_button.hide()

    def stretch_columns(self):
        return {1, 2}

    def leading_actions(self):
        self.detail_button = button(tr("Détail"), tooltip=tr("Toute la demande et son historique (Entrée)"))
        self.detail_button.clicked.connect(self.open_row)
        return [self.detail_button]

    def extra_actions(self):
        self.status_button = button(tr("Changer le statut…"))
        self.invite_button = button(tr("Inviter la famille…"), "primary")
        self.status_button.clicked.connect(self.change_status)
        self.invite_button.clicked.connect(self.invite)
        return [self.status_button, self.invite_button]

    def update_extra_actions(self, row):
        if not hasattr(self, "invite_button"):
            return
        self.detail_button.setEnabled(row is not None)
        final = row is not None and row.status in ("ACCEPTED", "REJECTED")
        self.status_button.setEnabled(row is not None and not final)
        self.status_button.setToolTip(tr("Une décision est définitive.") if final else "")
        accepted = row is not None and row.status == "ACCEPTED"
        self.invite_button.setEnabled(accepted)
        self.invite_button.setToolTip(
            tr("Crée le compte Parent (sans enfant rattaché) et un lien d'activation valable 48 heures.")
            if accepted
            else tr("Seule une demande acceptée peut être invitée.")
        )

    def status_cell(self, row):
        return coloured(row.status_label, REQUEST_COLOURS.get(row.status, TOKENS.text))

    def fetch(self):
        return self.service.pre_enrollments(
            page=self.page_number, status=self.status.currentData(), search=self.search.text()
        )

    def cells(self, row):
        return [row.reference, row.guardian, row.child, row.level, _when(row.submitted_at), ""]

    def describe_row(self, row):
        return row.reference

    def ask(self, kind, request):
        dialog = (PreEnrollmentDialog if kind == "detail" else StatusDialog)(request, self)
        accepted = dialog.exec() == QDialog.Accepted
        return dialog.values() if accepted and kind == "status" else None

    def open_row(self):
        row = self.selected()
        if row is not None:
            self.call(
                lambda: self.service.pre_enrollment(row.id),
                lambda request: self.ask("detail", request),
                action=tr("Impossible de charger la demande"),
            )

    def change_status(self):
        row = self.selected()
        if row is None:
            return

        def decide(request):
            values = self.ask("status", request)
            if values:
                self.call(
                    lambda: self.service.change_status(request.id, **values),
                    lambda saved: self._reselect(
                        saved.id, tr("Demande {0} : {1}.", saved.reference, saved.status_label.lower())
                    ),
                    action=tr("Impossible de changer le statut"),
                )

        self.call(lambda: self.service.pre_enrollment(row.id), decide, action=tr("Impossible de charger la demande"))

    def invite(self):
        row = self.selected()
        if row is None or row.status != "ACCEPTED":
            return
        text = tr(
            "Un compte Parent sera créé pour {0} ({1}), sans aucun enfant rattaché, avec un lien d'activation "
            "valable 48 heures. Une invitation précédente devient inutilisable.\n\nAucun e-mail n'est envoyé : "
            "vous remettrez le lien vous-même.",
            row.guardian,
            row.guardian_email,
        )
        if not self.confirm(self, tr("Inviter la famille ?"), text, confirm_text=tr("Créer le lien")):
            return

        def show(result):
            self.show_invitation(result)
            self._reselect(row.id, tr("Lien d'invitation créé pour {0}.", row.reference))

        self.call(lambda: self.service.invite(row.id), show, action=tr("Impossible d'inviter la famille"))


# =============================================================================
# Editorial contents
# =============================================================================


class ContentPage(CatalogPage):
    """One editorial table. `kind`: pages | faq | news | locations | resources | images."""

    status_filters = Tr([("Statut : tous", None), *((label, code) for code, label in PUBLICATION_STATUSES.items())])
    has_toggle = False
    search_placeholder = Tr("Rechercher…")
    narrow_hidden = (2, 3)

    def __init__(self, kind, service, references, runner, parent=None, **kwargs):
        self.kind = kind
        self.service = service
        self.references = references
        self.choose_file = choose_file
        super().__init__(runner, parent, **kwargs)

    def stretch_columns(self):
        return {0}

    def extra_actions(self):
        self.publish_button = button(tr("Publier"))
        self.archive_button = button(tr("Archiver"), "danger", tooltip=tr("Le contenu n'est plus affiché (conservé)"))
        self.publish_button.clicked.connect(lambda: self.set_status("PUBLISHED"))
        self.archive_button.clicked.connect(lambda: self.set_status("ARCHIVED"))
        actions = [self.publish_button, self.archive_button]
        if self.kind == "resources":
            self.document_button = button(tr("Joindre un PDF…"), tooltip=tr("Document téléchargeable par les lecteurs"))
            self.document_button.clicked.connect(self.attach_document)
            actions.insert(0, self.document_button)
        return actions

    def update_extra_actions(self, row):
        if not hasattr(self, "publish_button"):
            return
        self.publish_button.setEnabled(row is not None and row.status != "PUBLISHED")
        self.archive_button.setEnabled(row is not None and row.status == "PUBLISHED")
        if self.kind == "resources":
            self.document_button.setEnabled(row is not None)

    def status_cell(self, row):
        return coloured(row.status_label, PUBLICATION_COLOURS.get(row.status, TOKENS.text))

    def fetch(self):
        rows = self.service.contents(self.kind, status=self.status.currentData())
        search = self.search.text().strip().lower()
        rows = [r for r in rows if not search or search in r.title.lower()]
        return sorted(rows, key=lambda r: (r.data.get("order") or 0, r.title.lower()))

    def detail(self, row):
        """Second column: what kind of content it is."""
        d = row.data
        if self.kind == "pages":
            return PAGE_KINDS.get(d.get("kind"), d.get("kind"))
        if self.kind == "faq":
            return FAQ_CATEGORIES.get(d.get("category"), d.get("category"))
        if self.kind == "news":
            return NEWS_CATEGORIES.get(d.get("category"), d.get("category"))
        if self.kind == "resources":
            label = RESOURCE_KINDS.get(d.get("kind"), d.get("kind"))
            return f"{label} · PDF" if d.get("document_name") else label
        if self.kind == "images":
            label = IMAGE_CATEGORIES.get(d.get("category"), d.get("category"))
            return f"{label} · {tr('illustration')}" if d.get("is_illustration") else label
        return d.get("address_text") or ""

    def cells(self, row):
        flags = []
        if row.data.get("to_validate"):
            flags.append(tr("provisoire"))
        if row.data.get("is_demo"):
            flags.append(tr("démo"))
        title = f"{row.title}  ({', '.join(flags)})" if flags else row.title
        return [title, self.detail(row), row.audience_label or "—", _when(row.updated_at), ""]

    def describe_row(self, row):
        return row.title

    def _references(self):
        if self.kind != "resources":
            return {}
        return {
            "levels": self.references.levels(),
            "classes": self.references.classes(),
            "years": self.references.years(),
        }

    def ask(self, content=None, references=None, file_name=None):
        dialog = ContentDialog(self.kind, self, content, references, file_name=file_name)
        return dialog.values() if dialog.exec() == QDialog.Accepted else None

    def _saved_content(self, saved, verb):
        self.success(tr("« {0} » {1}.", saved.title, verb))
        self.call(
            self.fetch,
            lambda rows: (self.show_rows(rows), self.select_id(saved.id)),
            action=tr("Impossible de charger les {0}", self.plural),
        )

    def add(self):
        if self.kind == "images":
            path = self.choose_file(self, tr("Importer une image"), tr(IMAGE_FILTER))
            if not path:
                return
            values = self.ask(file_name=path.replace("\\", "/").rsplit("/", 1)[-1])
            if values:
                self.call(
                    lambda: self.service.upload_image(path, values),
                    lambda saved: self._saved_content(saved, tr("importée")),
                    action=tr("Impossible d'importer l'image"),
                )
            return

        def open_form(references):
            values = self.ask(None, references)
            if values:
                self.call(
                    lambda: self.service.save(self.kind, values),
                    lambda saved: self._saved_content(saved, tr("enregistré")),
                    action=tr("Impossible d'enregistrer"),
                )

        self.call(self._references, open_form, action=tr("Impossible de préparer le formulaire"))

    def edit(self):
        row = self.selected()
        if row is None:
            return

        def open_form(references):
            values = self.ask(row, references)
            if values:
                self.call(
                    lambda: self.service.save(self.kind, values, row.id),
                    lambda saved: self._saved_content(saved, tr("enregistré")),
                    action=tr("Impossible d'enregistrer"),
                )

        self.call(self._references, open_form, action=tr("Impossible de préparer le formulaire"))

    def set_status(self, status):
        row = self.selected()
        if row is None:
            return
        if status == "ARCHIVED" and not self.confirm(
            self,
            tr("Archiver ce contenu ?"),
            tr("« {0} » ne sera plus affiché. Il est conservé et pourra être republié.", row.title),
            confirm_text=tr("Archiver"),
            danger=True,
        ):
            return
        verb = tr("publié") if status == "PUBLISHED" else tr("archivé")
        self.call(
            lambda: self.service.set_status(row, status),
            lambda saved: self._saved_content(saved, verb),
            action=tr("Impossible de modifier la publication"),
        )

    def attach_document(self):
        row = self.selected()
        if row is None:
            return
        path = self.choose_file(self, tr("Joindre un PDF"), tr(PDF_FILTER))
        if path:
            self.call(
                lambda: self.service.attach_document(row.id, path),
                lambda saved: self._saved_content(saved, tr("document joint")),
                action=tr("Impossible de joindre le document"),
            )


class PagesContent(ContentPage):
    title = Tr("Pages")
    description = Tr("Textes du site et de l'Espace ISBREE (présentation, admissions, mentions légales…).")
    columns = Tr(["Titre", "Type", "Publics", "Modifié le", STATUS_COLUMN_TITLE])
    noun = "page"


class FaqContent(ContentPage):
    title = Tr("FAQ")
    description = Tr("Questions fréquentes, classées par catégorie et par public.")
    columns = Tr(["Question", "Catégorie", "Publics", "Modifié le", STATUS_COLUMN_TITLE])
    noun = "question"


class NewsContent(ContentPage):
    title = Tr("Actualités")
    description = Tr("Actualités et événements. La date de publication est fixée par le serveur.")
    columns = Tr(["Titre", "Catégorie", "Publics", "Modifié le", STATUS_COLUMN_TITLE])
    noun = "actualité"


class ImagesContent(ContentPage):
    title = Tr("Images")
    description = Tr(
        "Images du site, réencodées par le serveur (métadonnées supprimées). Une image d'illustration est "
        "toujours signalée comme telle aux lecteurs."
    )
    columns = Tr(["Texte alternatif", "Catégorie", "Publics", "Modifié le", STATUS_COLUMN_TITLE])
    noun = "image"


class ResourcesContent(ContentPage):
    title = Tr("Ressources")
    description = Tr(
        "Ressources de l'Espace ISBREE par rôle : fournitures, programmes, consignes, procédures… Une ressource "
        "peut être limitée à un niveau, une classe ou une année."
    )
    columns = Tr(["Titre", "Type", "Publics", "Modifié le", STATUS_COLUMN_TITLE])
    noun = "ressource"


class LocationsContent(ContentPage):
    title = Tr("Lieux")
    description = Tr("Sites de l'établissement affichés sur la page Contact.")
    columns = Tr(["Nom", "Adresse", "Publics", "Modifié le", STATUS_COLUMN_TITLE])
    noun = "lieu"
    plural_noun = "lieux"
    feminine = False


CONTENT_PAGES = {
    "pages": PagesContent,
    "faq": FaqContent,
    "news": NewsContent,
    "images": ImagesContent,
    "resources": ResourcesContent,
    "locations": LocationsContent,
}


# =============================================================================
# Mobile applications
# =============================================================================


class ReleasesPage(CatalogPage):
    title = Tr("Applications")
    description = Tr(
        "Versions Android téléchargeables depuis l'Espace ISBREE, par rôle. Seul un APK de production signé est "
        "accepté ; une version n'est proposée qu'une fois publiée. Aucune version iOS."
    )
    columns = Tr(["Application", "Version", "Fichier", "Publiée le", STATUS_COLUMN_TITLE])
    noun = "version"
    search_placeholder = Tr("Rechercher par application ou version…")
    status_filters = Tr(
        [("Statut : tous", None), ("Publiées", "PUBLISHED"), ("Brouillons", "DRAFT"), ("Retirées", "WITHDRAWN")]
    )
    has_toggle = False
    narrow_hidden = (2,)

    def __init__(self, service, runner, parent=None, **kwargs):
        self.service = service
        self.choose_file = choose_file
        super().__init__(runner, parent, **kwargs)
        self.edit_button.hide()
        self.add_button.setText(tr("Importer un APK…"))

    def stretch_columns(self):
        return {0}

    def extra_actions(self):
        self.publish_button = button(tr("Publier"))
        self.withdraw_button = button(tr("Retirer"), "danger", tooltip=tr("La version n'est plus téléchargeable"))
        self.publish_button.clicked.connect(lambda: self.set_status("PUBLISHED"))
        self.withdraw_button.clicked.connect(lambda: self.set_status("WITHDRAWN"))
        return [self.publish_button, self.withdraw_button]

    def update_extra_actions(self, row):
        if not hasattr(self, "publish_button"):
            return
        self.publish_button.setEnabled(row is not None and row.status != "PUBLISHED")
        self.withdraw_button.setEnabled(row is not None and row.status == "PUBLISHED")

    def status_cell(self, row):
        return coloured(row.status_label, PUBLICATION_COLOURS.get(row.status, TOKENS.text_secondary))

    def fetch(self):
        rows = self.service.releases()
        wanted = self.status.currentData()
        search = self.search.text().strip().lower()
        return [
            r
            for r in rows
            if (not wanted or r.status == wanted)
            and (not search or search in r.app_label.lower() or search in r.version_name.lower())
        ]

    def cells(self, row):
        return [
            row.app_label,
            (f"{row.version_name} ({row.version_code})", row.version_code),
            f"{row.file_name} · {_size(row.size)}",
            _when(row.published_at),
            "",
        ]

    def describe_row(self, row):
        return f"{row.app_label} {row.version_name}"

    def ask(self, file_name):
        dialog = ReleaseDialog(file_name, self)
        return dialog.values() if dialog.exec() == QDialog.Accepted else None

    def add(self):
        path = self.choose_file(self, tr("Importer un APK de production signé"), tr(APK_FILTER))
        if not path:
            return
        values = self.ask(path.replace("\\", "/").rsplit("/", 1)[-1])
        if values:
            self.call(
                lambda: self.service.add_release(path, **values),
                lambda saved: self._done(saved, tr("Version {0} importée (brouillon).", saved.version_name)),
                action=tr("APK refusé"),
            )

    def edit(self):
        pass

    def open_row(self):
        pass

    def set_status(self, status):
        row = self.selected()
        if row is None:
            return
        if status == "WITHDRAWN" and not self.confirm(
            self,
            tr("Retirer cette version ?"),
            tr("{0} ne sera plus téléchargeable depuis l'Espace ISBREE.", self.describe_row(row)),
            confirm_text=tr("Retirer"),
            danger=True,
        ):
            return
        self.call(
            lambda: self.service.set_release_status(row.id, status),
            lambda saved: self._done(saved, tr("{0} : {1}.", self.describe_row(saved), saved.status_label.lower())),
            action=tr("Impossible de modifier la version"),
        )

    def _done(self, saved, message):
        self.success(message)
        self.call(
            self.fetch,
            lambda rows: (self.show_rows(rows), self.select_id(saved.id)),
            action=tr("Impossible de charger les {0}", self.plural),
        )


# =============================================================================
# Profile and publication readiness
# =============================================================================

PROFILE_FIELDS = Texts(
    [
        ("tagline", "Accroche", "line"),
        ("presentation", "Présentation", "text"),
        ("values", "Valeurs (une par ligne)", "text"),
        ("pedagogy", "Approche pédagogique", "text"),
        ("location_details", "Localisation affichée", "line"),
        ("office_hours", "Horaires d'accueil", "line"),
    ]
)


class ProfilePage(Page):
    title = Tr("Profil et publication")

    def __init__(self, service, runner, parent=None, **kwargs):
        super().__init__(runner, parent, **kwargs)
        self.service = service
        head = QVBoxLayout()
        head.addWidget(QLabel(self.title, objectName="pageTitle"))
        subtitle = QLabel(
            tr(
                "Présentation de l'établissement sur le site public, et ce qui empêche encore une ouverture "
                "officielle. L'adresse n'est affichée qu'une fois confirmée."
            ),
            objectName="subtitle",
        )
        subtitle.setWordWrap(True)
        head.addWidget(subtitle)
        self.layout_.addLayout(head)
        self.layout_.addWidget(self.banner)

        columns = QHBoxLayout()
        form_box = QWidget()
        self.form = QFormLayout(form_box)
        self.fields = {}
        for key, label, kind in PROFILE_FIELDS:
            if kind == "line":
                widget = QLineEdit()
            else:
                widget = QPlainTextEdit()
                widget.setTabChangesFocus(True)
                widget.setFixedHeight(90)
            widget.setAccessibleName(label)
            self.fields[key] = widget
            self.form.addRow(label, widget)
        self.address_confirmed = QCheckBox(tr("L'adresse de l'établissement est confirmée (affichée sur le site)"))
        self.to_validate = QCheckBox(tr("Présentation provisoire, à valider par l'établissement"))
        self.form.addRow("", self.address_confirmed)
        self.form.addRow("", self.to_validate)
        self.save_button = button(tr("Enregistrer"), "primary")
        self.save_button.clicked.connect(self.save)
        self.form.addRow("", self.save_button)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(form_box)
        columns.addWidget(scroll, 3)

        side = QVBoxLayout()
        side.addWidget(QLabel(tr("Avant l'ouverture"), objectName="sectionTitle"))
        self.readiness_state = QLabel("")
        self.readiness_state.setWordWrap(True)
        side.addWidget(self.readiness_state)
        self.readiness = QListWidget()
        self.readiness.setAccessibleName(tr("Points à régler avant l'ouverture"))
        self.readiness.setWordWrap(True)
        side.addWidget(self.readiness, 1)
        self.refresh_button = button(tr("Actualiser"))
        self.refresh_button.clicked.connect(self.reload)
        side.addWidget(self.refresh_button)
        columns.addLayout(side, 2)
        self.layout_.addLayout(columns, 1)

    def reload(self):
        self.call(
            lambda: (self.service.profile(), self.service.readiness()),
            self.show_data,
            action=tr("Impossible de charger le profil"),
        )

    def show_data(self, data):
        profile, readiness = data
        for key, widget in self.fields.items():
            value = profile.get(key) or ""
            if isinstance(widget, QLineEdit):
                widget.setText(value)
            else:
                widget.setPlainText(value)
        self.address_confirmed.setChecked(bool(profile.get("address_confirmed")))
        self.to_validate.setChecked(bool(profile.get("to_validate")))
        self.show_readiness(readiness)

    def show_readiness(self, readiness):
        self.readiness.clear()
        items = readiness.get("items", [])
        blocking = [i for i in items if i.get("severity") == "blocking"]
        self.readiness_state.setText(
            tr("Prêt pour une ouverture : aucun point bloquant.")
            if readiness.get("ready")
            else tr("{0} point(s) bloquant(s) avant une ouverture officielle.", len(blocking))
        )
        for item in items:
            prefix = "■ " if item.get("severity") == "blocking" else "□ "
            count = f" ({item['count']})" if item.get("count") else ""
            text = READINESS.get(item.get('code'), item.get('message') or item.get('code'))
            entry = QListWidgetItem(f"{prefix}{text}{count}")
            entry.setToolTip(tr("Bloquant") if item.get("severity") == "blocking" else tr("À surveiller"))
            self.readiness.addItem(entry)

    def values(self):
        values = {
            key: (widget.text() if isinstance(widget, QLineEdit) else widget.toPlainText()).strip()
            for key, widget in self.fields.items()
        }
        values.update(address_confirmed=self.address_confirmed.isChecked(), to_validate=self.to_validate.isChecked())
        return values

    def save(self):
        values = self.values()
        self.call(
            lambda: (self.service.save_profile(values), self.service.readiness()),
            lambda data: (self.show_data(data), self.success(tr("Profil enregistré."))),
            action=tr("Impossible d'enregistrer le profil"),
        )

    def set_busy(self, busy):
        super().set_busy(busy)
        if hasattr(self, "save_button"):
            self.save_button.setEnabled(not busy)
            self.refresh_button.setEnabled(not busy)


# =============================================================================
# Module
# =============================================================================


class WebsitePage(Page):
    title = Tr("Site ISBREE")

    def __init__(self, service, references, runner, parent=None, *, can_review=True, **kwargs):
        super().__init__(runner, parent, **kwargs)
        self.layout_.setContentsMargins(0, 8, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.pages = {}
        if can_review:
            self._add("pre_enrollments", tr("Préinscriptions"), PreEnrollmentsPage(service, runner, **kwargs))
        for kind, label in (
            ("pages", tr("Pages")),
            ("faq", tr("FAQ")),
            ("news", tr("Actualités")),
            ("images", tr("Images")),
            ("resources", tr("Ressources")),
            ("locations", tr("Lieux")),
        ):
            self._add(kind, label, CONTENT_PAGES[kind](kind, service, references, runner, **kwargs))
        self._add("releases", tr("Applications"), ReleasesPage(service, runner, **kwargs))
        self._add("profile", tr("Profil et publication"), ProfilePage(service, runner, **kwargs))
        self.layout_.addWidget(self.tabs)
        self.tabs.currentChanged.connect(lambda _: self.tabs.currentWidget().activate())

    def _add(self, name, label, page):
        self.pages[name] = page
        self.tabs.addTab(page, label)
        page.session_expired.connect(self.session_expired.emit)

    def activate(self):
        self.tabs.currentWidget().activate()

    def open_tab(self, name):
        page = self.pages[name]
        self.tabs.setCurrentWidget(page)
        return page

"""Site ISBREE: the dialogs. Every rule is the server's (transitions, publication,
file checks); the forms only collect values and say what is missing.

    PreEnrollmentDialog  a family's request: identity, request, history, invitation state
    StatusDialog         next status among those the server allows, reason, message to the family
    InvitationDialog     the activation link, shown ONCE, to hand over to the family (no e-mail is sent)
    ContentDialog        page / question / article / location / role resource / image information
    ReleaseDialog        a signed release APK and its version
"""

from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QGuiApplication, QIntValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QWidget,
)

from ...i18n import Labels, tr
from ...services.website import (
    APPS,
    AUDIENCES,
    FAQ_CATEGORIES,
    IMAGE_CATEGORIES,
    INVITATION_STATES,
    NEWS_CATEGORIES,
    PAGE_KINDS,
    PRE_ENROLLMENT_STATUSES,
    PUBLICATION_STATUSES,
    RESOURCE_KINDS,
)
from ..widgets import FormDialog, button, date_field

EVENT_ACTIONS = Labels(
    {"SUBMITTED": "Demande reçue", "STATUS_CHANGED": "Statut modifié", "INVITED": "Invitation émise"}
)
NEEDS_REASON = ("REJECTED", "INFO_REQUESTED")
TELLS_FAMILY = ("ACCEPTED", "REJECTED", "INFO_REQUESTED")


def _when(moment):
    return f"{moment:%d/%m/%Y %H:%M}" if moment else "—"


def _text(placeholder="", height=90):
    widget = QPlainTextEdit(placeholderText=placeholder)
    widget.setFixedHeight(height)
    widget.setTabChangesFocus(True)
    return widget


def _info(text):
    label = QLabel(text or "—")
    label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


# =============================================================================
# Pre-enrollments
# =============================================================================


class PreEnrollmentDialog(FormDialog):
    """Read-only record of a request (the decision is taken with « Changer le statut… »)."""

    def __init__(self, request, parent=None):
        super().__init__(
            tr("Demande {0}", request.reference),
            tr("Reçue le {0} · {1}", _when(request.submitted_at), request.status_label),
            parent,
            save_text=tr("Fermer"),
            width=620,
        )
        self.cancel_button.hide()
        self.add_section(tr("Responsable"))
        self.add_field("guardian", tr("Nom"), _info(f"{request.guardian} ({request.relationship})"))
        self.add_field("phone", tr("Téléphone"), _info(request.guardian_phone), width="medium")
        self.add_field("email", tr("Adresse e-mail"), _info(request.guardian_email), beside=True)
        self.add_section(tr("Enfant et demande"))
        born = f" — {tr('né(e) le {0:%d/%m/%Y}', request.child_birth_date)}" if request.child_birth_date else ""
        self.add_field("child", tr("Enfant"), _info(f"{request.child}{born}"))
        self.add_field("request", tr("Niveau et année"), _info(f"{request.level} · {request.year}"))
        self.add_field("previous", tr("Établissement actuel"), _info(request.previous_school))
        self.add_field("comment", tr("Message de la famille"), _info(request.comment))
        self.add_field(
            "consent",
            tr("Consentement"),
            _info(tr("Accepté le {0} (version {1})", _when(request.consent_at), request.consent_version or "—")),
        )
        self.add_section(tr("Suivi"))
        invitation = request.invitation or {}
        state = INVITATION_STATES.get(invitation.get("state", "NONE"), invitation.get("state", ""))
        self.add_field("invitation", tr("Espace ISBREE"), _info(state))
        if request.message_to_family:
            self.add_field("message", tr("Message à la famille"), _info(request.message_to_family))
        history = []
        for event in request.events:
            when = (event.get("created_at") or "")[:16].replace("T", " ")
            line = f"{when} — {EVENT_ACTIONS.get(event['action'], event['action'])}"
            if event.get("to_status"):
                line += f" : {PRE_ENROLLMENT_STATUSES.get(event['to_status'], event['to_status'])}"
            if event.get("actor"):
                line += f" ({event['actor']})"
            if event.get("note"):
                line += f" — {event['note']}"
            history.append(line)
        self.add_field("history", tr("Historique"), _info("\n".join(history)))
        self.finish(required_note=False)


class StatusDialog(FormDialog):
    def __init__(self, request, parent=None):
        super().__init__(
            tr("Changer le statut — {0}", request.reference),
            tr(
                "Seules les étapes autorisées par le serveur sont proposées. Une décision (acceptée, refusée) est "
                "définitive. Accepter une demande n'inscrit pas l'élève et ne rattache aucun enfant."
            ),
            parent,
            width=560,
        )
        self.target = QComboBox()
        for code in request.allowed:
            self.target.addItem(PRE_ENROLLMENT_STATUSES.get(code, code), code)
        self.add_field("status", tr("Nouveau statut"), self.target, required=True, width="medium")
        self.note = self.add_field(
            "note",
            tr("Motif interne"),
            _text(tr("Visible par l'administration uniquement.")),
            help_text=tr("Obligatoire pour un refus ou une demande d'informations."),
        )
        self.message = self.add_field(
            "message_to_family",
            tr("Message à la famille"),
            _text(tr("Affiché à la famille dans son Espace ISBREE (500 caractères au plus)."), 72),
            help_text=tr("Aucun e-mail n'est envoyé : la famille le lit dans son espace, ou vous le lui transmettez."),
        )
        self.message.setPlainText(request.message_to_family)
        self.target.currentIndexChanged.connect(self.refresh_state)
        self.note.textChanged.connect(self.refresh_state)
        self.finish()

    def missing_fields(self):
        missing = [] if self.target.currentData() else [tr("Nouveau statut")]
        if self.target.currentData() in NEEDS_REASON and not self.note.toPlainText().strip():
            missing.append(tr("Motif interne"))
        return missing

    def values(self):
        status = self.target.currentData()
        return {
            "status": status,
            "note": self.note.toPlainText().strip(),
            "message_to_family": self.message.toPlainText().strip()[:500] if status in TELLS_FAMILY else None,
        }


class InvitationDialog(FormDialog):
    """The link is displayed once: the server keeps only its hash."""

    def __init__(self, result, parent=None):
        super().__init__(
            tr("Lien d'invitation"),
            tr(
                "Remettez ce lien à la famille (en main propre, SMS ou e-mail que vous envoyez vous-même). "
                "Aucun e-mail n'a été envoyé par le logiciel. Le lien ne sera plus affiché."
            ),
            parent,
            save_text=tr("Fermer"),
            width=620,
        )
        self.cancel_button.hide()
        self.link = QLineEdit(result["link"])
        self.link.setReadOnly(True)
        self.link.setCursorPosition(0)
        self.add_field("link", tr("Lien d'activation"), self.link)
        self.copy_button = button(tr("Copier le lien"))
        self.copy_button.clicked.connect(self.copy)
        self.add_field("copy", "", self.copy_button, width="medium")
        self.add_field(
            "expires",
            tr("Valable jusqu'au"),
            _info(_when(result.get("expires_at"))),
            help_text=tr("Utilisable une seule fois. Une nouvelle invitation rend celle-ci inutilisable."),
        )
        self.finish(required_note=False)

    def copy(self):
        QGuiApplication.clipboard().setText(self.link.text())
        self.copy_button.setText(tr("Lien copié"))


# =============================================================================
# Editorial contents
# =============================================================================


class OptionalDate(QWidget):
    """A date that may stay empty: « Définir » enables the calendar."""

    def __init__(self, label, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.enabled = QCheckBox(tr("Définir"))
        self.enabled.setAccessibleName(tr("Définir : {0}", label))
        self.date = date_field()
        self.date.setDate(QDate.currentDate())
        self.date.setEnabled(False)
        self.enabled.toggled.connect(self.date.setEnabled)
        row.addWidget(self.enabled)
        row.addWidget(self.date, 1)

    def set_value(self, value):
        self.enabled.setChecked(bool(value))
        if value:
            day = date.fromisoformat(value) if isinstance(value, str) else value
            self.date.setDate(QDate(day.year, day.month, day.day))

    def value(self):
        if not self.enabled.isChecked():
            return None
        return self.date.date().toPython().isoformat()


def _combo(labels):
    widget = QComboBox()
    for code, label in labels.items():
        widget.addItem(label, code)
    return widget


def _refs(rows, empty):
    widget = QComboBox()
    widget.addItem(empty, None)
    for row in rows:
        widget.addItem(getattr(row, "label", None) or row.name, row.id)
    return widget


# (key, label, widget kind, options, required)
SPECS = Labels(
    {
        "pages": [
            ("kind", "Type de page", "combo", PAGE_KINDS, True),
            ("title", "Titre", "line", 200, True),
            ("summary", "Résumé", "line", 300, False),
            ("body", "Texte", "text", None, False),
            ("audiences", "Publics", "audiences", True, True),
        ],
        "faq": [
            ("category", "Catégorie", "combo", FAQ_CATEGORIES, True),
            ("question", "Question", "line", 300, True),
            ("answer", "Réponse", "text", None, True),
            ("audiences", "Publics", "audiences", True, True),
        ],
        "news": [
            ("category", "Catégorie", "combo", NEWS_CATEGORIES, True),
            ("title", "Titre", "line", 200, True),
            ("summary", "Résumé", "line", 400, True),
            ("body", "Texte", "text", None, False),
            ("event_date", "Date de l'événement", "date", None, False),
            ("audiences", "Publics", "audiences", True, True),
        ],
        "locations": [
            ("name", "Nom du lieu", "line", 150, True),
            ("description", "Description", "text", None, False),
            ("address_text", "Adresse affichée", "line", 300, False),
            ("is_main", "Site principal", "check", None, False),
        ],
        "resources": [
            ("kind", "Type de ressource", "combo", RESOURCE_KINDS, True),
            ("title", "Titre", "line", 200, True),
            ("body", "Texte", "text", None, False),
            ("audiences", "Publics", "audiences", False, True),
            ("level", "Niveau", "ref", "levels", False),
            ("school_class", "Classe", "ref", "classes", False),
            ("academic_year", "Année scolaire", "ref", "years", False),
            ("visible_from", "Visible à partir du", "date", None, False),
            ("visible_until", "Visible jusqu'au", "date", None, False),
        ],
        "images": [
            ("alt_text", "Texte alternatif", "line", 250, True),
            ("caption", "Légende", "line", 250, False),
            ("credit", "Crédit / source", "line", 200, False),
            ("category", "Catégorie", "combo", IMAGE_CATEGORIES, True),
            ("in_gallery", "Afficher dans la galerie", "check", None, False),
            ("is_illustration", "Image d'illustration (ne représente pas l'établissement)", "check", None, False),
            ("audiences", "Publics", "audiences", True, True),
        ],
    }
)
TITLES = Labels(
    {
        "pages": ("Nouvelle page", "Modifier la page"),
        "faq": ("Nouvelle question", "Modifier la question"),
        "news": ("Nouvelle actualité", "Modifier l'actualité"),
        "locations": ("Nouveau lieu", "Modifier le lieu"),
        "resources": ("Nouvelle ressource", "Modifier la ressource"),
        "images": ("Importer une image", "Modifier l'image"),
    }
)
HELP = Labels(
    {
        "body": (
            "Mise en forme simple : « ## » en début de ligne pour un intertitre, « - » pour une liste, "
            "une ligne vide entre deux paragraphes."
        ),
        "alt_text": "Décrit l'image pour les personnes qui ne la voient pas (obligatoire).",
        "audiences": "Qui peut lire ce contenu. « Site public » le rend visible de tous.",
        "level": "Facultatif : limite la ressource aux élèves / enseignants de ce niveau.",
        "school_class": "Facultatif : limite la ressource à cette classe.",
    }
)


class ContentDialog(FormDialog):
    """`references`: {"levels", "classes", "years"} lists for the role resources."""

    def __init__(self, kind, parent=None, content=None, references=None, *, file_name=None):
        self.kind = kind
        new_title, edit_title = TITLES[kind]
        super().__init__(
            tr(edit_title) if content is not None else tr(new_title),
            tr(
                "Un contenu n'est visible qu'une fois publié. Cochez « Contenu provisoire » tant que "
                "l'établissement ne l'a pas validé : il est alors signalé comme tel aux lecteurs."
            ),
            parent,
            width=640,
        )
        references = references or {}
        self.widgets = {}
        self.required = []
        if file_name:
            self.add_field("file", tr("Fichier"), _info(file_name))
        for key, label, widget_kind, option, required in SPECS[kind]:
            label = tr(label)
            if widget_kind == "line":
                widget = QLineEdit(maxLength=option)
            elif widget_kind == "text":
                widget = _text(height=140)
            elif widget_kind == "combo":
                widget = _combo(option)
            elif widget_kind == "check":
                widget = QCheckBox(label)
            elif widget_kind == "date":
                widget = OptionalDate(label)
            elif widget_kind == "ref":
                widget = _refs(references.get(option, []), tr("Tous"))
            else:  # audiences
                widget = QWidget()
                row = QHBoxLayout(widget)
                row.setContentsMargins(0, 0, 0, 0)
                widget.boxes = {}
                for code, name in AUDIENCES.items():
                    if code == "PUBLIC" and not option:
                        continue
                    box = QCheckBox(name)
                    box.toggled.connect(self.refresh_state)
                    widget.boxes[code] = box
                    row.addWidget(box)
                row.addStretch()
            short = widget_kind in ("combo", "ref", "date")
            self.add_field(
                key,
                "" if widget_kind == "check" else label,
                widget,
                required=required,
                width="medium" if short else "long",
                help_text=tr(HELP[key]) if key in HELP else "",
            )
            self.widgets[key] = (widget_kind, widget)
            if required:
                self.required.append((key, label))
                if widget_kind == "line":
                    widget.textChanged.connect(self.refresh_state)
                elif widget_kind == "text":
                    widget.textChanged.connect(self.refresh_state)

        self.add_section(tr("Publication"))
        self.publication = self.add_field("status", tr("Statut"), _combo(PUBLICATION_STATUSES), width="medium")
        order = QLineEdit(placeholderText="0", maxLength=4)
        order.setValidator(QIntValidator(0, 9999, order))
        self.order = self.add_field("order", tr("Ordre d'affichage"), order, width="short", beside=True)
        self.to_validate = self.add_field(
            "to_validate", "", QCheckBox(tr("Contenu provisoire, à valider par l'établissement"))
        )
        self.is_demo = self.add_field("is_demo", "", QCheckBox(tr("Donnée de démonstration (fictive)")))
        if content is None:
            self.to_validate.setChecked(True)
            if "audiences" in self.widgets:
                boxes = self.widgets["audiences"][1].boxes
                (boxes.get("PUBLIC") or next(iter(boxes.values()))).setChecked(True)
        else:
            self._load(content.data)
        self.finish()

    def _load(self, data):
        for key, (widget_kind, widget) in self.widgets.items():
            value = data.get(key)
            if widget_kind == "line":
                widget.setText(value or "")
            elif widget_kind == "text":
                widget.setPlainText(value or "")
            elif widget_kind in ("combo", "ref"):
                widget.setCurrentIndex(max(0, widget.findData(value)))
            elif widget_kind == "check":
                widget.setChecked(bool(value))
            elif widget_kind == "date":
                widget.set_value(value)
            else:
                for code, box in widget.boxes.items():
                    box.setChecked(code in (value or []))
        self.publication.setCurrentIndex(max(0, self.publication.findData(data.get("status"))))
        self.order.setText(str(data.get("order") or ""))
        self.to_validate.setChecked(bool(data.get("to_validate")))
        self.is_demo.setChecked(bool(data.get("is_demo")))

    def _value(self, key):
        widget_kind, widget = self.widgets[key]
        if widget_kind == "line":
            return widget.text().strip()
        if widget_kind == "text":
            return widget.toPlainText().strip()
        if widget_kind in ("combo", "ref"):
            return widget.currentData()
        if widget_kind == "check":
            return widget.isChecked()
        if widget_kind == "date":
            return widget.value()
        return [code for code, box in widget.boxes.items() if box.isChecked()]

    def missing_fields(self):
        return [label for key, label in self.required if not self._value(key)]

    def values(self):
        values = {key: self._value(key) for key in self.widgets}
        values.update(
            status=self.publication.currentData(),
            order=int(self.order.text()) if self.order.text().strip() else 0,
            to_validate=self.to_validate.isChecked(),
            is_demo=self.is_demo.isChecked(),
        )
        return values


# =============================================================================
# Mobile applications
# =============================================================================


class ReleaseDialog(FormDialog):
    def __init__(self, file_name, parent=None):
        super().__init__(
            tr("Nouvelle version d'application"),
            tr(
                "Seul un APK de production signé avec la clé de l'établissement est accepté : le serveur refuse un "
                "APK non signé ou signé en mode debug. La version reste en brouillon jusqu'à sa publication."
            ),
            parent,
            width=600,
        )
        self.add_field("file", tr("Fichier"), _info(file_name))
        self.app = self.add_field("app", tr("Application"), _combo(APPS), required=True, width="medium")
        self.version_name = self.add_field(
            "version_name",
            tr("Version"),
            QLineEdit(placeholderText=tr("Ex. 1.0.0"), maxLength=40),
            required=True,
            width="short",
        )
        code = QLineEdit(placeholderText="1", maxLength=9)
        code.setValidator(QIntValidator(1, 999999999, code))
        self.version_code = self.add_field(
            "version_code",
            tr("Code de version"),
            code,
            required=True,
            width="short",
            beside=True,
            help_text=tr("Le versionCode de l'APK : unique et croissant."),
        )
        self.min_android = self.add_field(
            "min_android", tr("Android minimum"), QLineEdit(placeholderText=tr("Ex. 8.0"), maxLength=60), width="short"
        )
        self.notes = self.add_field(
            "release_notes", tr("Nouveautés"), _text(tr("Ce qui change pour les utilisateurs."))
        )
        self.version_name.textChanged.connect(self.refresh_state)
        self.version_code.textChanged.connect(self.refresh_state)
        self.finish()

    def missing_fields(self):
        missing = []
        if not self.version_name.text().strip():
            missing.append(tr("Version"))
        if not self.version_code.text().strip():
            missing.append(tr("Code de version"))
        return missing

    def values(self):
        return {
            "app": self.app.currentData(),
            "version_name": self.version_name.text().strip(),
            "version_code": self.version_code.text().strip(),
            "min_android": self.min_android.text().strip(),
            "release_notes": self.notes.toPlainText().strip(),
        }

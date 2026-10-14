"""Vie scolaire → Présences: the day's attendance (computed by the server
from the QR scans and the policies; an administrator corrects a record with
a reason, audited), the gate passages (read only), the pupils' annual QR
codes (issue, reissue, revoke), the convocations of parents (verified links
only) and the gate guardians (creation, activation code, suspension — the
existing account services). Tabs: « Présences du jour », « Passages au
portail », « Codes QR », « Convocations », « Gardiens ».
Every call off the UI thread; every rule is the server's.
"""

from PySide6.QtCore import QDate, Qt, QTime
from PySide6.QtWidgets import QComboBox, QDialog, QLabel, QLineEdit, QPlainTextEdit, QTabWidget

from ...i18n import Lazy, Texts, Tr, tr
from ...services.attendance import (
    CONVOCATION_OUTCOMES,
    CONVOCATION_STATUSES,
    CORRECTIONS,
    DAILY_STATUSES,
    SCAN_RESULTS,
)
from ..dialogs.finance_dialogs import StudentPicker
from ..dialogs.teacher_dialogs import ActivationCodeDialog, ask_reason
from ..theme import TOKENS, TokenColours
from ..widgets import FormDialog, Page, button, date_field, time_field
from .catalog_base import STATUS_COLUMN_TITLE, CatalogPage
from .finance_page import coloured

DAILY_COLOURS = TokenColours(PRESENT="success", LATE="warning", ABSENT="danger", EXCUSED="text_secondary")
ALL = Texts([("Tous", None)])


def _date_filter(page, layout):
    page.day = date_field()
    page.day.setDate(QDate.currentDate())
    page.day.setAccessibleName(tr("Date"))
    page.day.setToolTip(tr("Jour affiché"))
    page.day.dateChanged.connect(lambda _: page.reload())
    layout.addWidget(page.day)


class _ReadOnly(CatalogPage):
    """List without add / edit: what the server computed."""

    has_toggle = False

    def __init__(self, service, runner, parent=None, **kwargs):
        self.service = service
        super().__init__(runner, parent, **kwargs)
        self.add_button.hide()
        self.edit_button.hide()

    def open_row(self):
        pass


def _values(dialog):
    return dialog.values() if dialog.exec() == QDialog.Accepted else None


class CorrectionDialog(FormDialog):
    """Correct one pupil's day: the reason is kept in the history (audit);
    present or late is decided by the server from the arrival time."""

    def __init__(self, record, parent=None):
        super().__init__(
            tr("Corriger la présence — {0}", record.student_name),
            tr("Statut actuel : {0}. Le motif est conservé dans l'historique.", record.status_label),
            parent,
            save_text=tr("Enregistrer la correction"),
            width=540,
        )
        self.target = QComboBox()
        for code, label in CORRECTIONS.items():
            self.target.addItem(label, code)
        current = "PRESENT" if record.status in ("PRESENT", "LATE") else record.status
        self.target.setCurrentIndex(max(0, self.target.findData(current)))
        self.add_field("status", tr("Nouveau statut"), self.target, required=True)
        arrival = QTime(record.arrival.hour, record.arrival.minute) if record.arrival else QTime(7, 30)
        self.arrival = self.add_field("arrival_time", tr("Heure d'arrivée"), time_field(arrival), width="short")
        reason = QPlainTextEdit(placeholderText=tr("Ex. certificat médical présenté, oubli de carte…"))
        reason.setFixedHeight(72)
        reason.setTabChangesFocus(True)
        self.reason = self.add_field("reason", tr("Motif"), reason, required=True)
        self.target.currentIndexChanged.connect(self._status_changed)
        self.reason.textChanged.connect(self.refresh_state)
        self.arrival.setEnabled(self.target.currentData() == "PRESENT")
        self.finish()

    def _status_changed(self, _index=None):
        self.arrival.setEnabled(self.target.currentData() == "PRESENT")
        self.refresh_state()

    def missing_fields(self):
        return [] if self.reason.toPlainText().strip() else [tr("Motif")]

    def values(self):
        present = self.target.currentData() == "PRESENT"
        return {
            "status": self.target.currentData(),
            "reason": self.reason.toPlainText().strip(),
            "arrival": self.arrival.time().toPython() if present else None,
        }


class DailyAttendancePage(_ReadOnly):
    title = Tr("Présences du jour")
    description = Tr(
        "Calculées par le serveur à partir des passages au portail (QR) et de l'horaire du jour. "
        "Une correction exige un motif et reste dans l'historique."
    )
    columns = Tr(["Élève", "Matricule", "Classe", "Arrivée", "Retard", STATUS_COLUMN_TITLE])
    noun = "élève"
    feminine = False
    search_placeholder = Tr("Rechercher un élève…")
    status_filters = Lazy(lambda: list(ALL) + [(label, code) for code, label in DAILY_STATUSES.items()])
    narrow_hidden = (1,)

    def __init__(self, service, references, runner, parent=None, **kwargs):
        self.references = references
        self.open_correction = lambda record: _values(CorrectionDialog(record, self))  # overridable in tests
        super().__init__(service, runner, parent, **kwargs)

    def stretch_columns(self):
        return {0}

    def extra_actions(self):
        self.correct_button = button(
            tr("Corriger…"), tooltip=tr("Corriger la présence sélectionnée (motif obligatoire)")
        )
        self.correct_button.clicked.connect(self.correct)
        return [self.correct_button]

    def update_extra_actions(self, row):
        if hasattr(self, "correct_button"):
            self.correct_button.setEnabled(row is not None)

    def open_row(self):
        self.correct()

    def correct(self):
        row = self.selected()
        if row is None:
            return
        values = self.open_correction(row)
        if not values:
            return
        self.call(
            lambda: self.service.correct(
                row.id, status=values["status"], reason=values["reason"], day=row.day, arrival=values["arrival"]
            ),
            lambda _saved: (self.success(tr("Correction de {0} enregistrée.", row.student_name)), self.reload()),
            action=tr("Impossible d'enregistrer la correction"),
        )

    def add_filters(self, layout):
        _date_filter(self, layout)
        self.class_filter = QComboBox()
        self.class_filter.setAccessibleName(tr("Filtrer par classe"))
        self.class_filter.addItem(tr("Toutes les classes"), None)
        self.class_filter.setMinimumWidth(160)
        self.class_filter.currentIndexChanged.connect(lambda _: self.reload())
        layout.addWidget(self.class_filter)

    def fetch(self):
        if self.class_filter.count() == 1:
            classes = self.references.classes()
            self.class_filter.blockSignals(True)
            for klass in classes:
                self.class_filter.addItem(klass.name, klass.id)
            self.class_filter.blockSignals(False)
        rows = self.service.daily(self.day.date().toPython(), self.class_filter.currentData())
        status, search = self.status.currentData(), self.search.text().strip().lower()
        return [
            r
            for r in rows
            if (not status or r.status == status)
            and (not search or search in f"{r.student_name} {r.student_number}".lower())
        ]

    def describe_row(self, row):
        return row.student_name

    def status_cell(self, row):
        return coloured(row.status_label, DAILY_COLOURS.get(row.status, TOKENS.text_secondary))

    def cells(self, row):
        arrival = f"{row.arrival:%H:%M}" if row.arrival else "—"
        late = (f"{row.late_minutes} min", row.late_minutes) if row.late_minutes else ("—", 0)
        return [row.student_name, row.student_number, row.school_class, arrival, late, ""]


class ScansPage(_ReadOnly):
    title = Tr("Passages au portail")
    description = Tr("Chaque QR présenté au portail, accepté ou refusé, avec le gardien qui l'a scanné.")
    columns = Tr(["Heure", "Élève", "Gardien", STATUS_COLUMN_TITLE])
    noun = "passage"
    feminine = False
    search_placeholder = Tr("Rechercher un élève ou un gardien…")
    status_filters = Lazy(lambda: list(ALL) + [(label, code) for code, label in SCAN_RESULTS.items()])
    default_sort = (0, Qt.DescendingOrder)  # most recent first

    def stretch_columns(self):
        return {1, 2}

    def add_filters(self, layout):
        _date_filter(self, layout)
        self.guardian_filter = QComboBox()
        self.guardian_filter.setAccessibleName(tr("Filtrer par gardien"))
        self.guardian_filter.addItem(tr("Tous les gardiens"), None)
        self.guardian_filter.setMinimumWidth(170)
        self.guardian_filter.currentIndexChanged.connect(lambda _: self.reload())
        layout.addWidget(self.guardian_filter)

    def set_guardians(self, guardians):
        current = self.guardian_filter.currentData()
        self.guardian_filter.blockSignals(True)
        self.guardian_filter.clear()
        self.guardian_filter.addItem(tr("Tous les gardiens"), None)
        for guardian in guardians:
            self.guardian_filter.addItem(f"{guardian.name} ({guardian.number})", guardian.id)
        self.guardian_filter.setCurrentIndex(max(0, self.guardian_filter.findData(current)))
        self.guardian_filter.blockSignals(False)

    def show_guardian(self, guardian_id):
        index = self.guardian_filter.findData(guardian_id)
        if index >= 0:
            self.guardian_filter.setCurrentIndex(index)  # reloads

    def fetch(self):
        rows = self.service.scans(
            self.day.date().toPython(), guardian=self.guardian_filter.currentData(), result=self.status.currentData()
        )
        search = self.search.text().strip().lower()
        return [r for r in rows if not search or search in f"{r.student_name} {r.scanned_by}".lower()]

    def describe_row(self, row):
        return row.student_name

    def status_cell(self, row):
        return coloured(row.result_label, TOKENS.success if row.accepted else TOKENS.danger)

    def cells(self, row):
        when = (f"{row.scanned_at:%H:%M:%S}", row.scanned_at.timestamp()) if row.scanned_at else ("—", 0)
        return [when, row.student_name, row.scanned_by, ""]


QR_COLOURS = TokenColours(ACTIVE="success", REVOKED="danger")


class CodesPage(_ReadOnly):
    """The annual QR code of each pupil of a class (the one the student card
    prints). Issuing is idempotent server side; a reissue revokes the active
    code and creates version n+1 (lost or stolen card)."""

    title = Tr("Codes QR")
    description = Tr(
        "Code QR annuel de chaque élève (imprimé sur la carte d'élève, module Documents). "
        "Réémettre révoque l'ancien code : l'ancienne carte ne passe plus au portail."
    )
    columns = Tr(["Élève", "Matricule", "Version", "Émis le", STATUS_COLUMN_TITLE])
    noun = "élève"
    feminine = False
    search_placeholder = Tr("Rechercher un élève…")
    status_filters = Lazy(
        lambda: list(ALL) + [(tr("Actif"), "ACTIVE"), (tr("Révoqué"), "REVOKED"), (tr("Aucun code"), "NONE")]
    )
    narrow_hidden = (1, 3)

    def __init__(self, service, references, runner, parent=None, **kwargs):
        self.references = references
        self.ask = ask_reason  # overridable in tests
        super().__init__(service, runner, parent, **kwargs)

    def stretch_columns(self):
        return {0}

    def add_filters(self, layout):
        self.class_filter = QComboBox()
        self.class_filter.setAccessibleName(tr("Filtrer par classe"))
        self.class_filter.addItem(tr("Choisir une classe…"), None)
        self.class_filter.setMinimumWidth(170)
        self.class_filter.currentIndexChanged.connect(lambda _: self.reload())
        layout.addWidget(self.class_filter)

    def extra_actions(self):
        self.class_button = button(
            tr("Toute la classe"),
            tooltip=tr("Un code pour chaque élève actif de la classe qui n'en a pas"),
        )
        self.issue_button = button(tr("Émettre"), tooltip=tr("Émettre le code de l'élève sélectionné"))
        self.reissue_button = button(
            tr("Réémettre…"), tooltip=tr("Carte perdue ou volée : nouveau code, l'ancien est révoqué")
        )
        self.revoke_button = button(tr("Révoquer…"), "danger")
        self.class_button.clicked.connect(self.issue_class)
        self.issue_button.clicked.connect(self.issue)
        self.reissue_button.clicked.connect(self.reissue)
        self.revoke_button.clicked.connect(self.revoke)
        return [self.class_button, self.issue_button, self.reissue_button, self.revoke_button]

    def update_extra_actions(self, row):
        if not hasattr(self, "class_button"):
            return
        self.class_button.setEnabled(self.class_filter.currentData() is not None)
        self.issue_button.setEnabled(row is not None and not row.active)
        self.reissue_button.setEnabled(row is not None and row.active)
        self.revoke_button.setEnabled(row is not None and row.active)

    def fetch(self):
        if self.class_filter.count() == 1:
            classes = self.references.classes()
            self.class_filter.blockSignals(True)
            for klass in classes:
                self.class_filter.addItem(klass.name, klass.id)
            self.class_filter.blockSignals(False)
        class_id = self.class_filter.currentData()
        if class_id is None:
            return []
        rows = self.service.class_codes(class_id)
        wanted, search = self.status.currentData(), self.search.text().strip().lower()
        return [
            r
            for r in rows
            if (not wanted or (r.qr_status or "NONE") == wanted)
            and (not search or search in f"{r.student_name} {r.student_number}".lower())
        ]

    def describe_row(self, row):
        return row.student_name

    def status_cell(self, row):
        return coloured(row.status_label, QR_COLOURS.get(row.qr_status, TOKENS.text_secondary))

    def cells(self, row):
        version = (f"V{row.version}", row.version) if row.version else ("—", 0)
        issued = (f"{row.issued_at:%d/%m/%Y}", row.issued_at.timestamp()) if row.issued_at else ("—", 0)
        return [row.student_name, row.student_number, version, issued, ""]

    def _done(self, message):
        self.success(message)
        self.reload()

    def issue_class(self):
        class_id, name = self.class_filter.currentData(), self.class_filter.currentText()
        if class_id is not None:
            self.call(
                lambda: self.service.issue_class_codes(class_id),
                lambda codes: self._done(tr("{0} code(s) actif(s) pour la classe {1}.", len(codes), name)),
                action=tr("Impossible d'émettre les codes de la classe"),
            )

    def open_row(self):
        """Double-click / Entrée on a pupil without an active code: issue it."""
        row = self.selected()
        if row is not None and not row.active:
            self.issue()

    def issue(self):
        row = self.selected()
        if row is not None and not row.active:
            self.call(
                lambda: self.service.issue_code(row.student_id),
                lambda _qr: self._done(tr("Code QR émis pour {0}.", row.student_name)),
                action=tr("Impossible d'émettre le code QR"),
            )

    def reissue(self):
        row = self.selected()
        if row is None:
            return
        answer = self.ask(
            self,
            tr("Réémettre le code de {0} ?", row.student_name),
            tr(
                "L'ancien code (V{0}) est révoqué : l'ancienne carte ne passe plus au portail. "
                "Imprimez ensuite la nouvelle carte (module Documents).",
                row.version,
            ),
            save_text=tr("Réémettre"),
        )
        if answer:
            self.call(
                lambda: self.service.reissue_code(row.student_id, answer["reason"]),
                lambda qr: self._done(tr("Nouveau code (V{0}) pour {1}.", qr.get("version"), row.student_name)),
                action=tr("Impossible de réémettre le code QR"),
            )

    def revoke(self):
        row = self.selected()
        if row is None:
            return
        answer = self.ask(
            self,
            tr("Révoquer le code de {0} ?", row.student_name),
            tr(
                "Le code ne passera plus au portail. Il reste dans l'historique ; "
                "un nouveau code peut être émis ensuite."
            ),
            save_text=tr("Révoquer"),
            danger=True,
        )
        if answer:
            self.call(
                lambda: self.service.revoke_code(row.qr_id, answer["reason"]),
                lambda _qr: self._done(tr("Code de {0} révoqué.", row.student_name)),
                action=tr("Impossible de révoquer le code QR"),
            )


class ConvocationDialog(FormDialog):
    """Convene a parent about a pupil: the pupil is searched on the server,
    the recipients are the server's list (active, verified links only)."""

    def __init__(self, search, load_recipients, parent=None):
        super().__init__(
            tr("Nouvelle convocation"),
            tr(
                "Le parent choisi est convoqué et prévenu dans son application. "
                "Seuls les responsables au lien vérifié peuvent être convoqués."
            ),
            parent,
            save_text=tr("Convoquer"),
            width=640,
        )
        self.load_recipients = load_recipients
        self.picker = self.add_field("student", tr("Élève"), StudentPicker(search), required=True)
        self.recipient = QComboBox()
        self.recipient.setEnabled(False)
        self.recipient.addItem(tr("— choisissez d'abord l'élève —"), None)
        self.add_field("parent", tr("Responsable convoqué"), self.recipient, required=True)
        self.recipient_help = QLabel("", objectName="help", wordWrap=True)
        self.body.addWidget(self.recipient_help)
        self.day = self.add_field("day", tr("Date"), date_field(), required=True, width="short")
        self.day.setDate(QDate.currentDate().addDays(1))
        self.start = self.add_field(
            "start", tr("Début"), time_field(QTime(15, 0)), required=True, width="short", beside=True
        )
        self.end = self.add_field("end", tr("Fin"), time_field(QTime(16, 0)), required=True, width="short", beside=True)
        reason = QPlainTextEdit(placeholderText=tr("Ex. absences répétées non justifiées"))
        reason.setFixedHeight(72)
        reason.setTabChangesFocus(True)
        self.reason = self.add_field("reason", tr("Motif"), reason, required=True)
        self.recipients = []
        self.picker.results.currentIndexChanged.connect(lambda _: self._student_changed())
        self.recipient.currentIndexChanged.connect(lambda _: self._recipient_changed())
        for field in (self.start, self.end):
            field.timeChanged.connect(lambda _: self.refresh_state())
        self.reason.textChanged.connect(self.refresh_state)
        self.finish()

    def _student_changed(self):
        self.recipients = []
        self.recipient.clear()
        self.recipient.setEnabled(False)
        self.recipient_help.setText("")
        if self.picker.student_id:
            self.recipient.addItem(tr("Chargement…"), None)
            self.load_recipients(self.picker.student_id, self.show_recipients)
        else:
            self.recipient.addItem(tr("— choisissez d'abord l'élève —"), None)
        self.refresh_state()

    def show_recipients(self, recipients):
        self.recipients = list(recipients)
        self.recipient.clear()
        if not self.recipients:
            self.recipient.addItem(tr("Aucun responsable vérifié"), None)
            self.recipient_help.setText(
                tr(
                    "Aucun parent n'a de lien vérifié avec cet élève : "
                    "validez d'abord un rattachement (module Parents)."
                )
            )
        for recipient in self.recipients:
            self.recipient.addItem(recipient.label, recipient.parent_id)
        self.recipient.setEnabled(bool(self.recipients))
        self._recipient_changed()

    def _recipient_changed(self):
        chosen = next((r for r in self.recipients if r.parent_id == self.recipient.currentData()), None)
        if chosen is not None:
            self.recipient_help.setText(
                ""
                if chosen.notified
                else tr(
                    "Ce parent ne recevra pas la notification (compte inactif ou notifications refusées) : "
                    "prévenez-le aussi autrement."
                )
            )
        self.refresh_state()

    def missing_fields(self):
        missing = []
        if not self.picker.student_id:
            missing.append(tr("Élève"))
        if not self.recipient.currentData():
            missing.append(tr("Responsable convoqué"))
        if self.end.time() <= self.start.time():
            missing.append(tr("une heure de fin après le début"))
        if not self.reason.toPlainText().strip():
            missing.append(tr("Motif"))
        return missing

    def values(self):
        return {
            "student_id": self.picker.student_id,
            "parent_id": self.recipient.currentData(),
            "day": self.day.date().toPython(),
            "start": self.start.time().toPython(),
            "end": self.end.time().toPython(),
            "reason": self.reason.toPlainText().strip(),
        }


class OutcomeDialog(FormDialog):
    """Close a scheduled convocation (held, parent absent, cancelled), with an optional note."""

    def __init__(self, convocation, parent=None):
        super().__init__(
            tr("Clore la convocation — {0}", convocation.student_name),
            tr("Une convocation close ne change plus ; le parent est prévenu du nouveau statut."),
            parent,
            save_text=tr("Enregistrer"),
            width=520,
        )
        self.outcome = QComboBox()
        for code, label in CONVOCATION_OUTCOMES.items():
            self.outcome.addItem(label, code)
        self.add_field("status", tr("Résultat"), self.outcome, required=True)
        notes = QPlainTextEdit(placeholderText=tr("Compte rendu (facultatif)"))
        notes.setFixedHeight(72)
        notes.setTabChangesFocus(True)
        self.notes = self.add_field("notes", tr("Notes"), notes)
        self.finish()

    def values(self):
        return {"status": self.outcome.currentData(), "notes": self.notes.toPlainText().strip()}


CONVOCATION_COLOURS = TokenColours(SCHEDULED="warning", HELD="success", MISSED="danger", CANCELLED="text_secondary")


class ConvocationsPage(CatalogPage):
    """Convocations of the school (administration list: names, never contact details)."""

    title = Tr("Convocations")
    description = Tr(
        "Rendez-vous avec un parent au sujet d'un élève. Seuls les parents au lien vérifié peuvent être convoqués ; "
        "chaque convocation et son issue restent dans l'historique."
    )
    columns = Tr(["Date", "Élève", "Responsable", "Motif", STATUS_COLUMN_TITLE])
    noun = "convocation"
    feminine = True
    search_placeholder = Tr("Rechercher un élève ou un parent…")
    status_filters = Lazy(lambda: list(ALL) + [(label, code) for code, label in CONVOCATION_STATUSES.items()])
    has_toggle = False
    default_sort = (0, Qt.DescendingOrder)
    narrow_hidden = (3,)

    def __init__(self, service, runner, parent=None, *, find_students=None, **kwargs):
        self.service = service
        self.find_students = find_students  # text -> [(id, label)]: the server's search (students/?search=)
        self.open_dialog = self._open_dialog  # overridable in tests
        self.open_outcome = lambda convocation: _values(OutcomeDialog(convocation, self))
        super().__init__(runner, parent, **kwargs)
        self.edit_button.hide()

    def stretch_columns(self):
        return {1, 3}

    def extra_actions(self):
        self.close_button = button(tr("Clore…"), tooltip=tr("Tenue, parent absent ou annulée"))
        self.close_button.clicked.connect(self.close_convocation)
        return [self.close_button]

    def update_extra_actions(self, row):
        if hasattr(self, "close_button"):
            self.close_button.setEnabled(row is not None and row.active)
            self.close_button.setToolTip(
                tr("Tenue, parent absent ou annulée")
                if row is None or row.active
                else tr("Convocation déjà close : elle ne change plus.")
            )

    def open_row(self):
        row = self.selected()
        if row is not None and row.active:
            self.close_convocation()

    def fetch(self):
        rows = self.service.convocations(self.status.currentData())
        search = self.search.text().strip().lower()
        return [
            r for r in rows if not search or search in f"{r.student_name} {r.student_number} {r.parent_name}".lower()
        ]

    def describe_row(self, row):
        return row.student_name

    def status_cell(self, row):
        return coloured(row.status_label, CONVOCATION_COLOURS.get(row.status, TOKENS.text_secondary))

    def cells(self, row):
        when = (f"{row.start:%d/%m/%Y %H:%M}", row.start.timestamp()) if row.start else ("—", 0)
        return [when, row.student_name, row.parent_name, row.reason, ""]

    def load_recipients(self, student_id, done):
        self.call(
            lambda: self.service.recipients(student_id),
            done,
            action=tr("Impossible de charger les responsables de l'élève"),
        )

    def search_students(self, text, done):
        self.call(lambda: self.find_students(text), done, action=tr("Impossible de rechercher les élèves"))

    def _open_dialog(self):
        return _values(ConvocationDialog(self.search_students, self.load_recipients, self))

    def add(self):
        values = self.open_dialog()
        if values:
            self.call(
                lambda: self.service.create_convocation(**values),
                lambda saved: self._done(
                    tr("Convocation de {0} enregistrée : le parent est prévenu.", saved.parent_name)
                ),
                action=tr("Impossible de créer la convocation"),
            )

    def close_convocation(self):
        row = self.selected()
        if row is None or not row.active:
            return
        values = self.open_outcome(row)
        if values:
            self.call(
                lambda: self.service.close_convocation(row.id, values["status"], values["notes"]),
                lambda saved: self._done(tr("Convocation de {0} : {1}.", saved.student_name, saved.status_label)),
                action=tr("Impossible de clore la convocation"),
            )

    def _done(self, message):
        self.success(message)
        self.reload()


class GuardianDialog(FormDialog):
    def __init__(self, parent=None):
        super().__init__(
            tr("Nouveau gardien"),
            tr("Le compte est créé sans mot de passe : remettez ensuite un code d'activation à la personne."),
            parent,
            width=560,
        )
        self.first_name = self.add_field("first_name", tr("Prénom"), QLineEdit(), required=True, width="medium")
        self.last_name = self.add_field("last_name", tr("Nom"), QLineEdit(), required=True, width="medium", beside=True)
        self.email = self.add_field("email", tr("E-mail (identifiant)"), QLineEdit(), required=True)
        self.number = self.add_field("guardian_number", tr("N° de gardien"), QLineEdit(), required=True, width="short")
        self.phone = self.add_field("phone", tr("Téléphone"), QLineEdit(), width="medium", beside=True)
        for field in (self.first_name, self.last_name, self.email, self.number):
            field.textChanged.connect(lambda _: self.refresh_state())
        self.finish()

    def missing_fields(self):
        labels = {"Prénom": self.first_name, "Nom": self.last_name, "E-mail": self.email, "N° de gardien": self.number}
        return [label for label, field in labels.items() if not field.text().strip()]

    def values(self):
        return {
            "first_name": self.first_name.text(),
            "last_name": self.last_name.text(),
            "email": self.email.text(),
            "guardian_number": self.number.text(),
            "phone": self.phone.text(),
        }


class GuardiansPage(CatalogPage):
    title = Tr("Gardiens")
    description = Tr("Comptes des gardiens du portail : création, code d'activation, suspension.")
    columns = Tr(["Nom", "N°", "E-mail", "Passages aujourd'hui", "Dernier passage", STATUS_COLUMN_TITLE])
    noun = "gardien"
    feminine = False
    search_placeholder = Tr("Rechercher par nom, n° ou e-mail…")
    status_filters = Tr([("Tous", None), ("Actifs", "ACTIVE"), ("Suspendus", "SUSPENDED")])
    has_toggle = False
    narrow_hidden = (2, 4)

    def __init__(self, service, accounts, runner, parent=None, *, show_scans=None, **kwargs):
        self.service, self.accounts = service, accounts
        self.show_scans = show_scans  # opens the passages of a guardian (tab « Passages »)
        self.open_dialog = self._open_dialog
        self.ask_suspend = ask_reason
        self.show_code = lambda guardian, issued: ActivationCodeDialog(guardian.name, issued, self).exec()
        super().__init__(runner, parent, **kwargs)
        self.edit_button.hide()

    def stretch_columns(self):
        return {0, 2}

    def extra_actions(self):
        self.code_button = button(
            tr("Code d'activation…"), tooltip=tr("Générer le code que la personne saisira dans l'application")
        )
        self.suspend_button = button(tr("Suspendre"), "danger", tooltip=tr("Connexion impossible, sessions fermées"))
        self.enable_button = button(tr("Réactiver"))
        self.scans_button = button(tr("Passages…"), tooltip=tr("Les passages enregistrés par ce gardien"))
        self.code_button.clicked.connect(self.issue_code)
        self.suspend_button.clicked.connect(self.suspend)
        self.enable_button.clicked.connect(self.enable)
        self.scans_button.clicked.connect(self.open_scans)
        return [self.scans_button, self.code_button, self.suspend_button, self.enable_button]

    def update_extra_actions(self, row):
        if not hasattr(self, "code_button"):
            return
        active = row is not None and row.account_status == "ACTIVE"
        self.code_button.setEnabled(active and not row.activated)
        self.suspend_button.setEnabled(active)
        self.enable_button.setEnabled(row is not None and row.account_status == "SUSPENDED")
        self.scans_button.setEnabled(row is not None)

    def fetch(self):
        return self.service.guardians(search=self.search.text().strip(), status=self.status.currentData())

    def describe_row(self, row):
        return row.name

    def status_cell(self, row):
        colour = {"ACTIVE": TOKENS.success, "SUSPENDED": TOKENS.danger}.get(row.account_status, TOKENS.text_secondary)
        if row.account_status == "ACTIVE" and not row.activated:
            colour = TOKENS.warning
        return coloured(row.account_label, colour)

    def cells(self, row):
        last = (f"{row.last_scan_at:%d/%m %H:%M}", row.last_scan_at.timestamp()) if row.last_scan_at else ("—", 0)
        return [row.name, row.number, row.email, (str(row.scans_today), row.scans_today), last, ""]

    def show_rows(self, rows):
        super().show_rows(rows)
        if self.show_scans is not None:
            self.show_scans(rows, None)

    def _open_dialog(self):
        dialog = GuardianDialog(self)
        return dialog.values() if dialog.exec() == QDialog.Accepted else None

    def add(self):
        values = self.open_dialog()
        if values:
            self.call(
                lambda: self.service.create_guardian(**values),
                lambda saved: self._saved(saved, tr("créé")),
                action=tr("Impossible de créer le gardien"),
            )

    def _done(self, message):
        self.reload()
        self.banner.show_message("success", message, autohide=True)

    def issue_code(self):
        row = self.selected()
        if row is None:
            return

        def shown(issued):
            self.show_code(row, issued)
            expires = f"{issued.expires_at:%d/%m/%Y %H:%M}" if issued.expires_at else "—"
            self._done(
                tr("Code d'activation remis pour {0} (valable jusqu'au {1}).", row.name, expires)
            )  # never the code

        self.call(
            lambda: self.accounts.issue_code(row.membership_id), shown, action=tr("Impossible de générer le code")
        )

    def suspend(self):
        row = self.selected()
        if row is None:
            return
        answer = self.ask_suspend(
            self,
            tr("Suspendre le gardien"),
            tr("{0} ne pourra plus se connecter ni scanner ; ses sessions sont fermées.", row.name),
            save_text=tr("Suspendre"),
            danger=True,
        )
        if answer:
            self.call(
                lambda: self.accounts.disable(row.membership_id, answer["reason"]),
                lambda _: self._done(tr("Compte de {0} suspendu.", row.name)),
                action=tr("Impossible de suspendre le compte"),
            )

    def enable(self):
        row = self.selected()
        if row is not None:
            self.call(
                lambda: self.accounts.enable(row.membership_id),
                lambda _: self._done(tr("Compte de {0} réactivé.", row.name)),
                action=tr("Impossible de réactiver le compte"),
            )

    def open_scans(self):
        row = self.selected()
        if row is not None and self.show_scans is not None:
            self.show_scans(None, row.id)


class AttendancePage(Page):
    title = Tr("Présences")

    def __init__(self, service, references, accounts, runner, parent=None, *, find_students=None, **kwargs):
        super().__init__(runner, parent, **kwargs)
        self.layout_.setContentsMargins(0, 8, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.daily = DailyAttendancePage(service, references, runner, **kwargs)
        self.scans = ScansPage(service, runner, **kwargs)
        self.codes = CodesPage(service, references, runner, **kwargs)
        self.convocations = ConvocationsPage(service, runner, find_students=find_students, **kwargs)
        self.guardians = GuardiansPage(service, accounts, runner, show_scans=self._scans_of, **kwargs)
        self.pages = {
            "daily": self.daily,
            "scans": self.scans,
            "codes": self.codes,
            "convocations": self.convocations,
            "guardians": self.guardians,
        }
        for page, label in (
            (self.daily, tr("Présences du jour")),
            (self.scans, tr("Passages au portail")),
            (self.codes, tr("Codes QR")),
            (self.convocations, tr("Convocations")),
            (self.guardians, tr("Gardiens")),
        ):
            self.tabs.addTab(page, label)
            page.session_expired.connect(self.session_expired.emit)
        self.layout_.addWidget(self.tabs)
        self.tabs.currentChanged.connect(lambda _: self.tabs.currentWidget().activate())

    def _scans_of(self, guardians, guardian_id):
        if guardians is not None:
            self.scans.set_guardians(guardians)  # the guardian filter follows the list
        if guardian_id is not None:
            self.tabs.setCurrentWidget(self.scans)
            self.scans.show_guardian(guardian_id)

    def activate(self):
        self.tabs.currentWidget().activate()

    def reload(self):
        for page in self.pages.values():
            if page.rows or page.isVisible():
                page.reload()

    def open_tab(self, name):
        page = self.pages[name]
        self.tabs.setCurrentWidget(page)
        return page

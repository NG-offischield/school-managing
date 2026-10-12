"""Vie scolaire → Présences: the day's attendance and the gate passages (read
only: the server computes them from the QR scans and the policies), and the
gate guardians (creation, activation code, suspension — the existing account
services). Tabs: « Présences du jour », « Passages au portail », « Gardiens ».
Every call off the UI thread; every rule is the server's.
"""

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QComboBox, QDialog, QLineEdit, QTabWidget

from ...services.attendance import DAILY_STATUSES, SCAN_RESULTS
from ..dialogs.teacher_dialogs import ActivationCodeDialog, ask_reason
from ..theme import TOKENS, TokenColours
from ..widgets import FormDialog, Page, button, date_field
from .catalog_base import STATUS_COLUMN_TITLE, CatalogPage
from .finance_page import coloured

DAILY_COLOURS = TokenColours(PRESENT="success", LATE="warning", ABSENT="danger", EXCUSED="text_secondary")
ALL = [("Tous", None)]


def _date_filter(page, layout):
    page.day = date_field()
    page.day.setDate(QDate.currentDate())
    page.day.setAccessibleName("Date")
    page.day.setToolTip("Jour affiché")
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


class DailyAttendancePage(_ReadOnly):
    title = "Présences du jour"
    description = "Calculées par le serveur à partir des passages au portail (QR) et de l'horaire du jour."
    columns = ["Élève", "Matricule", "Classe", "Arrivée", "Retard", STATUS_COLUMN_TITLE]
    noun = "élève"
    feminine = False
    search_placeholder = "Rechercher un élève…"
    status_filters = ALL + [(label, code) for code, label in DAILY_STATUSES.items()]
    narrow_hidden = (1,)

    def __init__(self, service, references, runner, parent=None, **kwargs):
        self.references = references
        super().__init__(service, runner, parent, **kwargs)

    def stretch_columns(self):
        return {0}

    def add_filters(self, layout):
        _date_filter(self, layout)
        self.class_filter = QComboBox()
        self.class_filter.setAccessibleName("Filtrer par classe")
        self.class_filter.addItem("Toutes les classes", None)
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
    title = "Passages au portail"
    description = "Chaque QR présenté au portail, accepté ou refusé, avec le gardien qui l'a scanné."
    columns = ["Heure", "Élève", "Gardien", STATUS_COLUMN_TITLE]
    noun = "passage"
    feminine = False
    search_placeholder = "Rechercher un élève ou un gardien…"
    status_filters = ALL + [(label, code) for code, label in SCAN_RESULTS.items()]
    default_sort = (0, Qt.DescendingOrder)  # most recent first

    def stretch_columns(self):
        return {1, 2}

    def add_filters(self, layout):
        _date_filter(self, layout)
        self.guardian_filter = QComboBox()
        self.guardian_filter.setAccessibleName("Filtrer par gardien")
        self.guardian_filter.addItem("Tous les gardiens", None)
        self.guardian_filter.setMinimumWidth(170)
        self.guardian_filter.currentIndexChanged.connect(lambda _: self.reload())
        layout.addWidget(self.guardian_filter)

    def set_guardians(self, guardians):
        current = self.guardian_filter.currentData()
        self.guardian_filter.blockSignals(True)
        self.guardian_filter.clear()
        self.guardian_filter.addItem("Tous les gardiens", None)
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


class GuardianDialog(FormDialog):
    def __init__(self, parent=None):
        super().__init__(
            "Nouveau gardien",
            "Le compte est créé sans mot de passe : remettez ensuite un code d'activation à la personne.",
            parent,
            width=560,
        )
        self.first_name = self.add_field("first_name", "Prénom", QLineEdit(), required=True, width="medium")
        self.last_name = self.add_field("last_name", "Nom", QLineEdit(), required=True, width="medium", beside=True)
        self.email = self.add_field("email", "E-mail (identifiant)", QLineEdit(), required=True)
        self.number = self.add_field("guardian_number", "N° de gardien", QLineEdit(), required=True, width="short")
        self.phone = self.add_field("phone", "Téléphone", QLineEdit(), width="medium", beside=True)
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
    title = "Gardiens"
    description = "Comptes des gardiens du portail : création, code d'activation, suspension."
    columns = ["Nom", "N°", "E-mail", "Passages aujourd'hui", "Dernier passage", STATUS_COLUMN_TITLE]
    noun = "gardien"
    feminine = False
    search_placeholder = "Rechercher par nom, n° ou e-mail…"
    status_filters = [("Tous", None), ("Actifs", "ACTIVE"), ("Suspendus", "SUSPENDED")]
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
            "Code d'activation…", tooltip="Générer le code que la personne saisira dans l'application"
        )
        self.suspend_button = button("Suspendre", "danger", tooltip="Connexion impossible, sessions fermées")
        self.enable_button = button("Réactiver")
        self.scans_button = button("Passages…", tooltip="Les passages enregistrés par ce gardien")
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
                lambda saved: self._saved(saved, "créé"),
                action="Impossible de créer le gardien",
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
            self._done(f"Code d'activation remis pour {row.name} (valable jusqu'au {expires}).")  # never the code

        self.call(lambda: self.accounts.issue_code(row.membership_id), shown, action="Impossible de générer le code")

    def suspend(self):
        row = self.selected()
        if row is None:
            return
        answer = self.ask_suspend(
            self,
            "Suspendre le gardien",
            f"{row.name} ne pourra plus se connecter ni scanner ; ses sessions sont fermées.",
            save_text="Suspendre",
            danger=True,
        )
        if answer:
            self.call(
                lambda: self.accounts.disable(row.membership_id, answer["reason"]),
                lambda _: self._done(f"Compte de {row.name} suspendu."),
                action="Impossible de suspendre le compte",
            )

    def enable(self):
        row = self.selected()
        if row is not None:
            self.call(
                lambda: self.accounts.enable(row.membership_id),
                lambda _: self._done(f"Compte de {row.name} réactivé."),
                action="Impossible de réactiver le compte",
            )

    def open_scans(self):
        row = self.selected()
        if row is not None and self.show_scans is not None:
            self.show_scans(None, row.id)


class AttendancePage(Page):
    title = "Présences"

    def __init__(self, service, references, accounts, runner, parent=None, **kwargs):
        super().__init__(runner, parent, **kwargs)
        self.layout_.setContentsMargins(0, 8, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.daily = DailyAttendancePage(service, references, runner, **kwargs)
        self.scans = ScansPage(service, runner, **kwargs)
        self.guardians = GuardiansPage(service, accounts, runner, show_scans=self._scans_of, **kwargs)
        self.pages = {"daily": self.daily, "scans": self.scans, "guardians": self.guardians}
        for page, label in (
            (self.daily, "Présences du jour"),
            (self.scans, "Passages au portail"),
            (self.guardians, "Gardiens"),
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

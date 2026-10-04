"""Gestion académique → Élèves (ADR 0018).

    Élèves                    Actualiser  Fiche  Modifier  Archiver  [Ajouter]
    [Rechercher…] [Actifs ▼]                                      N élèves
    [Année ▼] [Niveau ▼] [Classe ▼] [Inscription ▼]
    ┌ table (one page of the API) ───────────────────────────────────────┐
    └─────────────────────────────────────────────────────────────────────┘
                                   ‹ Précédente   Page 1 / 3   Suivante ›

The list is paginated by the server (50 rows a page) and filtered by the
API; the class filter follows the chosen year and level. Double-click /
Entrée opens the record, from which the schooling actions start (inscrire,
changer de classe, retirer). Every call runs off the UI thread; the
server decides every rule and the page explains its refusals.
"""

from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout, QLabel, QTableWidgetItem

from ...models import SEXES
from ..dialogs.student_dialogs import ChangeClassDialog, EnrollDialog, StudentDialog, StudentRecordDialog
from ..theme import TOKENS
from ..widgets import button, set_variant
from .catalog_base import STATUS_COLUMN_TITLE, CatalogPage

ALL_YEARS = "Toutes les années"
ALL_LEVELS = "Tous les niveaux"
ALL_CLASSES = "Toutes les classes"
STUDENT_FILTERS = [("Actifs", "ACTIVE"), ("Archivés", "ARCHIVED"), ("Tous", None)]
ENROLLMENT_FILTERS = [
    ("Toutes les situations", None),
    ("Inscrits (en cours)", "ACTIVE"),
    ("Retirés", "WITHDRAWN"),
    ("Non inscrits", "NONE"),
]


class StudentsPage(CatalogPage):
    title = "Élèves"
    description = "Fiches administratives et inscriptions des élèves : une classe par année scolaire."
    columns = ["Matricule", "Nom", "Prénom(s)", "Sexe", "Classe", "Niveau", "Année scolaire", STATUS_COLUMN_TITLE]
    noun = "élève"
    feminine = False
    search_placeholder = "Rechercher par nom, prénom ou matricule…"
    status_filters = STUDENT_FILTERS
    has_toggle = False
    sortable = False  # one page of a server-sorted list: no partial local sort

    def __init__(self, service, references, runner, parent=None, **kwargs):
        self.service = service
        self.references = references
        self.page_number = 1
        self.total = 0
        self.classes = []
        self._filters_ready = False
        super().__init__(runner, parent, **kwargs)
        self.record_button.clicked.connect(self.open_record)
        self.archive_button.clicked.connect(self.toggle_archive)

        filters = QHBoxLayout()
        filters.setSpacing(8)
        self.year_filter = self._combo("Filtrer par année scolaire", ALL_YEARS, 200)
        self.level_filter = self._combo("Filtrer par niveau", ALL_LEVELS, 170)
        self.class_filter = self._combo("Filtrer par classe", ALL_CLASSES, 150)
        self.enrollment_filter = self._combo("Filtrer par situation d'inscription", None, 180)
        for label, value in ENROLLMENT_FILTERS:
            self.enrollment_filter.addItem(label, value)
        for combo in (self.year_filter, self.level_filter, self.class_filter, self.enrollment_filter):
            filters.addWidget(combo)
        filters.addStretch()
        self.layout_.insertLayout(2, filters)
        self.year_filter.currentIndexChanged.connect(lambda _: self._filters_ready and self._year_or_level_changed())
        self.level_filter.currentIndexChanged.connect(lambda _: self._filters_ready and self._year_or_level_changed())
        self.class_filter.currentIndexChanged.connect(lambda _: self._filters_ready and self.reload_first_page())
        self.enrollment_filter.currentIndexChanged.connect(lambda _: self._filters_ready and self.reload_first_page())
        # Search and status restart from the first page.
        self._debounce.timeout.disconnect()
        self._debounce.timeout.connect(self.reload_first_page)
        self.status.currentIndexChanged.disconnect()
        self.status.currentIndexChanged.connect(lambda _: self.reload_first_page())

        pager = QHBoxLayout()
        pager.addStretch()
        self.previous_button = button("‹ Précédente", tooltip="Page précédente")
        self.page_label = QLabel("", objectName="countLabel")
        self.next_button = button("Suivante ›", tooltip="Page suivante")
        for widget in (self.previous_button, self.page_label, self.next_button):
            pager.addWidget(widget)
        self.layout_.addLayout(pager)
        self.previous_button.clicked.connect(lambda: self.go_to(self.page_number - 1))
        self.next_button.clicked.connect(lambda: self.go_to(self.page_number + 1))
        self._update_pager()

    @staticmethod
    def _combo(name, first, width):
        combo = QComboBox()
        combo.setAccessibleName(name)
        combo.setToolTip(name)
        combo.setMinimumWidth(width)
        if first:
            combo.addItem(first, None)
        return combo

    def stretch_columns(self):
        return {1, 2}

    def leading_actions(self):
        self.record_button = button("Fiche", tooltip="Consulter la fiche de l'élève (Entrée)")
        return [self.record_button]

    def extra_actions(self):
        self.archive_button = button("Archiver", "danger")
        return [self.archive_button]

    def update_extra_actions(self, row):
        if not hasattr(self, "archive_button"):
            return
        why = "Sélectionnez d'abord un élève dans la liste."
        self.record_button.setEnabled(row is not None)
        self.record_button.setToolTip(why if row is None else "Consulter la fiche de l'élève (Entrée)")
        archived = row is not None and row.status == "ARCHIVED"
        self.archive_button.setText("Réactiver" if archived else "Archiver")
        set_variant(self.archive_button, "secondary" if archived else "danger")
        self.archive_button.setEnabled(row is not None)
        self.archive_button.setToolTip(
            why
            if row is None
            else ("Réactiver l'élève" if archived else "Archiver : quitte les listes actives, historique conservé")
        )
        self.edit_button.setEnabled(row is not None and not archived)
        if archived:
            self.edit_button.setToolTip("Élève archivé : réactivez-le pour modifier sa fiche.")

    def describe_row(self, row):
        return f"{row.name} ({row.student_number})"

    def status_cell(self, row):
        item = QTableWidgetItem(("●  " if row.active else "○  ") + row.status_label)
        item.setForeground(QBrush(QColor(TOKENS.success if row.active else TOKENS.text_secondary)))
        font = QFont()
        font.setWeight(QFont.DemiBold if row.active else QFont.Normal)
        item.setFont(font)
        return item

    def is_filtered(self):
        return (
            super().is_filtered()
            or bool(self.level_filter.currentData())
            or bool(self.class_filter.currentData())
            or bool(self.enrollment_filter.currentData())
        )

    # --- filters ----------------------------------------------------------------------
    def activate(self):
        """Refresh the filter lists (years, levels, classes), then the list."""
        self.call(
            lambda: (
                self.references.years(),
                self.references.levels(active_only=False),
                self.references.classes(),
            ),
            self._fill_filters,
            action="Impossible de charger les années, niveaux et classes",
        )

    def _fill_filters(self, references):
        years, levels, self.classes = references
        first_time = not self._filters_ready
        self._filters_ready = False
        year, level = self.year_filter.currentData(), self.level_filter.currentData()
        self.year_filter.clear()
        self.year_filter.addItem(ALL_YEARS, None)
        for item in years:
            self.year_filter.addItem(item.label, item.id)
        if first_time:  # default: the current year
            year = next((y.id for y in years if y.is_current), None)
        self.year_filter.setCurrentIndex(max(0, self.year_filter.findData(year)))
        self.level_filter.clear()
        self.level_filter.addItem(ALL_LEVELS, None)
        for item in levels:
            self.level_filter.addItem(item.label if item.active else f"{item.label} (inactif)", item.id)
        self.level_filter.setCurrentIndex(max(0, self.level_filter.findData(level)))
        self._fill_classes()
        self._filters_ready = True
        self.reload_first_page()

    def _fill_classes(self):
        """Classes of the chosen year and level only."""
        chosen = self.class_filter.currentData()
        year, level = self.year_filter.currentData(), self.level_filter.currentData()
        self.class_filter.blockSignals(True)
        self.class_filter.clear()
        self.class_filter.addItem(ALL_CLASSES, None)
        for item in self.classes:
            if (not year or item.year_id == year) and (not level or item.level_id == level):
                self.class_filter.addItem(item.name, item.id)
        self.class_filter.setCurrentIndex(max(0, self.class_filter.findData(chosen)))
        self.class_filter.blockSignals(False)

    def _year_or_level_changed(self):
        self._fill_classes()
        self.reload_first_page()

    # --- list (server pages) -----------------------------------------------------------
    def fetch(self):
        return self.service.page(
            page=self.page_number,
            search=self.search.text(),
            status=self.status.currentData(),
            academic_year_id=self.year_filter.currentData() if hasattr(self, "year_filter") else None,
            level_id=self.level_filter.currentData() if hasattr(self, "level_filter") else None,
            class_id=self.class_filter.currentData() if hasattr(self, "class_filter") else None,
            enrollment_status=self.enrollment_filter.currentData() if hasattr(self, "enrollment_filter") else None,
        )

    def reload_first_page(self):
        self.page_number = 1
        self.reload()

    def go_to(self, number):
        self.page_number = max(1, min(number, self.pages))
        self.reload()

    @property
    def pages(self):
        return max(1, -(-self.total // self.service.PAGE_SIZE))

    def show_rows(self, result):
        rows, self.total = result
        super().show_rows(rows)
        self.count_label.setText(f"{self.total} {self.noun if self.total < 2 else self.plural}")
        self._update_pager()

    def _update_pager(self):
        if not hasattr(self, "page_label"):
            return
        self.page_label.setText(f"Page {self.page_number} / {self.pages}")
        self.previous_button.setEnabled(self.page_number > 1)
        self.next_button.setEnabled(self.page_number < self.pages)

    def cells(self, row):
        enrollment = row.enrollment
        return [
            row.student_number,
            row.last_name,
            row.first_name,
            SEXES.get(row.sex, row.sex),
            enrollment.class_name if enrollment else "Non inscrit",
            enrollment.level_code if enrollment else "—",
            enrollment.year_name if enrollment else "—",
            "",
        ]

    # --- dialogs (overridable in tests) ------------------------------------------------
    def ask(self, kind, **context):
        """Open the dialog `kind` and return its values (None if cancelled).
        For "record", returns the action chosen in the record (or None)."""
        factories = {
            "student": lambda: StudentDialog(
                context.get("references"), self, context.get("student"), photo=context.get("photo")
            ),
            "enroll": lambda: EnrollDialog(context["references"], self, context["student"]),
            "change_class": lambda: ChangeClassDialog(context["references"], self, context["enrollment"]),
            "record": lambda: StudentRecordDialog(
                context["student"], context["enrollments"], context["history"], context.get("photo"), self
            ),
        }
        dialog = factories[kind]()
        if dialog.exec() != QDialog.Accepted:
            return None
        if kind == "record":
            return dialog.action
        values = dialog.values()
        if kind == "student":
            values["photo_change"] = dialog.photo_change
        return values

    def _school_references(self):
        return (self.references.years(open_only=True), self.references.levels(), self.references.classes())

    # --- actions ------------------------------------------------------------------------
    def add(self):
        def open_form(references):
            values = self.ask("student", references=references)
            if values:
                photo = values.pop("photo_change")
                self.call(
                    lambda: self._save_photo(self.service.create(**values), photo),
                    lambda saved: self._saved(saved, "créé"),
                    action="Impossible de créer l'élève",
                )

        self.call(self._school_references, open_form, action="Impossible de charger les années, niveaux et classes")

    def edit(self, student=None):
        row = student or self.selected()
        if row is None or row.status == "ARCHIVED":
            return

        def open_form(loaded):
            current, photo = loaded
            values = self.ask("student", student=current, photo=photo)
            if values:
                change = values.pop("photo_change")
                values.pop("class_id", None)
                self.call(
                    lambda: self._save_photo(self.service.update(current.id, **values), change),
                    lambda saved: self._saved(saved, "modifié"),
                    action="Impossible de modifier l'élève",
                )

        self.call(
            lambda: (self.service.get(row.id), self.service.photo(row.id) if row.has_photo else None),
            open_form,
            action="Impossible de charger la fiche de l'élève",
        )

    def _save_photo(self, student, change):
        """Second call after the record is saved (multipart). If the photo is
        refused, the record stays saved and the error says why."""
        if change and change[0] == "set":
            return self.service.set_photo(student.id, change[1], change[2])
        if change and change[0] == "remove" and student.has_photo:
            return self.service.remove_photo(student.id)
        return student

    def open_row(self):
        self.open_record()

    def open_record(self):
        row = self.selected()
        if row is None:
            return

        def show(loaded):
            student, enrollments, history, photo = loaded
            action = self.ask("record", student=student, enrollments=enrollments, history=history, photo=photo)
            if action == "edit":
                self.edit(student)
            elif action == "enroll":
                self.enroll(student)
            elif action == "change_class":
                self.change_class(student, next(e for e in enrollments if e.active))
            elif action == "withdraw":
                self.withdraw(student, next(e for e in enrollments if e.active))

        self.call(
            lambda: (
                self.service.get(row.id),
                self.service.enrollments(row.id),
                self.service.history(row.id),
                self.service.photo(row.id) if row.has_photo else None,
            ),
            show,
            action="Impossible de charger la fiche de l'élève",
        )

    def enroll(self, student):
        def open_form(references):
            values = self.ask("enroll", references=references, student=student)
            if values:
                self.call(
                    lambda: self.service.enroll(student.id, values["class_id"], values.get("enrollment_date")),
                    lambda enrollment: self._done(
                        student, f"{student.name} est inscrit(e) en {enrollment.class_name} ({enrollment.year_name})."
                    ),
                    action="Impossible d'inscrire l'élève",
                )

        self.call(self._school_references, open_form, action="Impossible de charger les années, niveaux et classes")

    def change_class(self, student, enrollment):
        def open_form(references):
            values = self.ask("change_class", references=references, enrollment=enrollment)
            if values:
                self.call(
                    lambda: self.service.change_class(enrollment.id, values["class_id"]),
                    lambda moved: self._done(
                        student, f"{student.name} passe de {enrollment.class_name} à {moved.class_name}."
                    ),
                    action="Impossible de changer l'élève de classe",
                )

        self.call(
            lambda: (
                [],
                self.references.levels(),
                self.references.classes(academic_year_id=enrollment.year_id),
            ),
            open_form,
            action="Impossible de charger les classes",
        )

    def withdraw(self, student, enrollment):
        text = (
            f"{student.name} quittera la classe {enrollment.class_name} ({enrollment.year_name}) à partir "
            f"d'aujourd'hui : l'inscription passe « Retirée ».\n\nNotes, présences, QR, factures et documents "
            f"déjà enregistrés sont conservés dans l'historique."
        )
        if not self.confirm(self, "Retirer l'élève de sa classe ?", text, confirm_text="Retirer", danger=True):
            return
        self.call(
            lambda: self.service.withdraw(enrollment.id),
            lambda _: self._done(student, f"{student.name} a été retiré(e) de {enrollment.class_name}."),
            action="Impossible de retirer l'élève de sa classe",
        )

    def toggle_archive(self):
        row = self.selected()
        if row is None:
            return
        if row.status == "ARCHIVED":
            self.call(
                lambda: self.service.reactivate(row.id),
                lambda saved: self._saved(saved, "réactivé"),
                action="Impossible de réactiver l'élève",
            )
            return
        text = (
            f"« {self.describe_row(row)} » quittera les listes actives. Rien n'est supprimé : inscriptions, "
            f"notes, bulletins, présences, QR, paiements et documents restent dans l'historique, et vous "
            f"pourrez le réactiver.\n\nLe serveur refusera l'archivage tant que l'élève est inscrit dans une classe."
        )
        if not self.confirm(self, "Archiver l'élève ?", text, confirm_text="Archiver", danger=True):
            return
        self.call(
            lambda: self.service.archive(row.id),
            lambda saved: self._saved(saved, "archivé"),
            action="Impossible d'archiver l'élève",
        )

    def _done(self, student, message):
        self.success(message)
        self.call(
            self.fetch,
            lambda result: (self.show_rows(result), self.select_id(student.id)),
            action="Impossible de charger les élèves",
        )

    def _saved(self, saved, verb):
        self.success(f"Élève « {saved.name} » ({saved.student_number}) {verb} avec succès.")
        self.call(
            self.fetch,
            lambda result: (self.show_rows(result), self.select_id(saved.id)),
            action="Impossible de charger les élèves",
        )

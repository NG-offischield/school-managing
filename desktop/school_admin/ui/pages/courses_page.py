"""Gestion académique → Cours (ADR 0020).

    Cours                         Actualiser  Fiche  Modifier  Désactiver  [Ajouter]
    [Rechercher…] [Actifs ▼]                                               N cours
    [Année ▼] [Classe ▼] [Matière ▼]
    ┌ table (one page of the API) ─────────────────────────────────────────┐
    └───────────────────────────────────────────────────────────────────────┘
                                      ‹ Précédente   Page 1 / 2   Suivante ›

A course = subject + teacher + class + year. The teacher list of the form
comes from the server (eligible teachers); deactivation is refused by the
server while the planning still uses the course.
"""

from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout

from ..dialogs.course_dialogs import CourseDialog, CourseRecordDialog
from ..widgets import button
from .catalog_base import STATUS_COLUMN_TITLE, PagedCatalogPage

COURSE_FILTERS = [("Actifs", "active"), ("Inactifs", "inactive"), ("Tous", None)]
ALL_YEARS = "Toutes les années"
ALL_CLASSES = "Toutes les classes"
ALL_SUBJECTS = "Toutes les matières"


class CoursesPage(PagedCatalogPage):
    title = "Cours"
    description = "Qui enseigne quelle matière dans quelle classe, pour l'année de la classe."
    columns = ["Matière", "Enseignant", "Classe", "Niveau", "Année scolaire", "Coefficient", STATUS_COLUMN_TITLE]
    noun = "cours"
    plural_noun = "cours"
    feminine = False
    search_placeholder = "Rechercher par matière, classe ou enseignant…"
    status_filters = COURSE_FILTERS

    def __init__(self, service, subjects, references, runner, parent=None, **kwargs):
        self.service = service
        self.subjects = subjects
        self.references = references
        self.page_size = service.PAGE_SIZE
        self.classes = []
        self._filters_ready = False
        super().__init__(runner, parent, **kwargs)
        self.build_filters()
        self.record_button.clicked.connect(self.open_record)

    def stretch_columns(self):
        return {0, 1}

    def leading_actions(self):
        self.record_button = button("Fiche", tooltip="Consulter la fiche du cours (Entrée)")
        return [self.record_button]

    def build_filters(self):
        layout = QHBoxLayout()
        layout.setSpacing(8)
        self.year_filter = self._combo("Filtrer par année scolaire", ALL_YEARS, 200)
        self.class_filter = self._combo("Filtrer par classe", ALL_CLASSES, 150)
        self.subject_filter = self._combo("Filtrer par matière", ALL_SUBJECTS, 180)
        for combo in (self.year_filter, self.class_filter, self.subject_filter):
            layout.addWidget(combo)
        layout.addStretch()
        self.layout_.insertLayout(2, layout)
        self.year_filter.currentIndexChanged.connect(lambda _: self._filters_ready and self._year_changed())
        for combo in (self.class_filter, self.subject_filter):
            combo.currentIndexChanged.connect(lambda _: self._filters_ready and self.reload_first_page())

    @staticmethod
    def _combo(name, first, width):
        combo = QComboBox()
        combo.setAccessibleName(name)
        combo.setToolTip(name)
        combo.setMinimumWidth(width)
        combo.addItem(first, None)
        return combo

    def update_extra_actions(self, row):
        if hasattr(self, "record_button"):
            self.record_button.setEnabled(row is not None)
            self.record_button.setToolTip(
                "Sélectionnez d'abord un cours dans la liste."
                if row is None
                else "Consulter la fiche du cours (Entrée)"
            )

    def describe_row(self, row):
        return f"{row.subject_code} — {row.class_name} ({row.teacher_name})"

    def is_filtered(self):
        return super().is_filtered() or any(
            combo.currentData() for combo in (self.class_filter, self.subject_filter) if hasattr(self, "class_filter")
        )

    # --- filters ----------------------------------------------------------------------
    def activate(self):
        self.call(
            lambda: (self.references.years(), self.references.classes(), self.subjects.list(active=None)),
            self._fill_filters,
            action="Impossible de charger les années, classes et matières",
        )

    def _fill_filters(self, loaded):
        years, self.classes, subjects = loaded
        first_time = not self._filters_ready
        self._filters_ready = False
        year = self.year_filter.currentData()
        self.year_filter.clear()
        self.year_filter.addItem(ALL_YEARS, None)
        for item in years:
            self.year_filter.addItem(item.label, item.id)
        if first_time:
            year = next((y.id for y in years if y.is_current), None)
        self.year_filter.setCurrentIndex(max(0, self.year_filter.findData(year)))
        chosen = self.subject_filter.currentData()
        self.subject_filter.clear()
        self.subject_filter.addItem(ALL_SUBJECTS, None)
        for item in subjects:
            self.subject_filter.addItem(f"{item.code} — {item.name}", item.id)
        self.subject_filter.setCurrentIndex(max(0, self.subject_filter.findData(chosen)))
        self._fill_classes()
        self._filters_ready = True
        self.reload_first_page()

    def _fill_classes(self):
        year, chosen = self.year_filter.currentData(), self.class_filter.currentData()
        self.class_filter.blockSignals(True)
        self.class_filter.clear()
        self.class_filter.addItem(ALL_CLASSES, None)
        for item in self.classes:
            if not year or item.year_id == year:
                self.class_filter.addItem(item.name, item.id)
        self.class_filter.setCurrentIndex(max(0, self.class_filter.findData(chosen)))
        self.class_filter.blockSignals(False)

    def _year_changed(self):
        self._fill_classes()
        self.reload_first_page()

    def fetch(self):
        return self.service.page(
            page=self.page_number,
            search=self.search.text(),
            status=self.status.currentData(),
            academic_year_id=self.year_filter.currentData() if hasattr(self, "year_filter") else None,
            class_id=self.class_filter.currentData() if hasattr(self, "class_filter") else None,
            subject_id=self.subject_filter.currentData() if hasattr(self, "subject_filter") else None,
        )

    def cells(self, row):
        return [
            row.subject_label,
            f"{row.teacher_name} ({row.teacher_number})" if row.teacher_number else row.teacher_name,
            row.class_name,
            row.level_code or "—",
            row.year_name,
            (row.coefficient, float(row.coefficient or 0)),
            "",
        ]

    # --- dialogs (overridable in tests) ------------------------------------------------
    def find_teachers(self, class_id, subject_id, done):
        """Ask the SERVER which teachers may teach (off the UI thread)."""
        self.call(
            lambda: self.service.eligible_teachers(class_id, subject_id),
            done,
            action="Impossible de charger les enseignants autorisés",
        )

    def ask(self, kind, **context):
        if kind == "course":
            dialog = CourseDialog(context["references"], self.find_teachers, self, context.get("course"))
            return dialog.values() if dialog.exec() == QDialog.Accepted else None
        dialog = CourseRecordDialog(context["course"], self)
        return dialog.action if dialog.exec() == QDialog.Accepted else None

    def _form_references(self):
        return (
            self.references.years(open_only=True),
            self.references.classes(),
            self.subjects.list(active=True),
            self.service.scales(),
        )

    # --- actions ------------------------------------------------------------------------
    def add(self):
        def open_form(references):
            values = self.ask("course", references=references)
            if values:
                self.call(
                    lambda: self.service.create(**values),
                    lambda saved: self._reselect(
                        saved.id, f"Cours « {saved.code} » ({saved.teacher_name}) créé avec succès."
                    ),
                    action="Impossible de créer le cours",
                )

        self.call(self._form_references, open_form, action="Impossible de charger les listes du formulaire")

    def edit(self, course=None):
        row = course or self.selected()
        if row is None:
            return

        def open_form(loaded):
            current, references = loaded
            values = self.ask("course", references=references, course=current)
            if values:
                self.call(
                    lambda: self.service.update(current.id, **values),
                    lambda saved: self._reselect(
                        saved.id, f"Cours « {saved.code} » ({saved.teacher_name}) modifié avec succès."
                    ),
                    action="Impossible de modifier le cours",
                )

        self.call(
            lambda: (self.service.get(row.id), self._form_references()),
            open_form,
            action="Impossible de charger le cours",
        )

    def open_row(self):
        self.open_record()

    def open_record(self):
        row = self.selected()
        if row is None:
            return

        def show(course):
            if self.ask("record", course=course) == "edit":
                self.edit(course)

        self.call(lambda: self.service.get(row.id), show, action="Impossible de charger le cours")

    def deactivate(self, row_id):
        return self.service.deactivate(row_id)

    def reactivate(self, row_id):
        return self.service.reactivate(row_id)

    def _saved(self, saved, verb):
        self._reselect(saved.id, f"Cours « {saved.code} » ({saved.teacher_name}) {verb} avec succès.")

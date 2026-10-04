"""Gestion académique → Enseignants (ADR 0019).

    Enseignants      Actualiser  Fiche  Modifier  Désactiver  Qualifications  [Ajouter]
    [Rechercher…] [Actifs ▼]                                               N enseignants
    [Catégorie ▼] [Matière ▼]
    ┌ table (one page of the API) ──────────────────────────────────────────┐
    └────────────────────────────────────────────────────────────────────────┘
                                        ‹ Précédente   Page 1 / 2   Suivante ›

Server-side pagination and filters. Double-click / Entrée opens the record.
Désactiver = stop teaching (refused by the server while courses or future
sessions need the teacher); nothing is deleted. Compatibility verdicts come
from the server only (QualificationsDialog).
"""

from PySide6.QtWidgets import QComboBox, QDialog, QHBoxLayout

from ..dialogs.teacher_dialogs import QualificationsDialog, TeacherDialog, TeacherRecordDialog, ask_reason
from ..widgets import button
from .catalog_base import STATUS_COLUMN_TITLE, PagedCatalogPage

TEACHER_FILTERS = [("Actifs", "active"), ("Inactifs", "inactive"), ("Tous", None)]
ALL_CATEGORIES = "Toutes les catégories"
ALL_SUBJECTS = "Toutes les matières"


class TeachersPage(PagedCatalogPage):
    title = "Enseignants"
    description = "Fiches des enseignants, leurs matières qualifiées et leur statut. Les cours se créent ensuite."
    columns = ["Matricule", "Nom", "Prénom(s)", "Catégorie", "Matière principale", "Matières", STATUS_COLUMN_TITLE]
    noun = "enseignant"
    feminine = False
    search_placeholder = "Rechercher par nom, prénom, e-mail ou matricule…"
    status_filters = TEACHER_FILTERS

    def __init__(self, service, categories, subjects, references, runner, parent=None, *, payroll=None, **kwargs):
        self.service = service
        self.payroll = payroll  # read-only remuneration (record)
        self.categories = categories
        self.subjects = subjects
        self.references = references
        self.page_size = service.PAGE_SIZE
        self._filters_ready = False
        super().__init__(runner, parent, **kwargs)
        self.build_filters()
        self.record_button.clicked.connect(self.open_record)
        self.qualifications_button.clicked.connect(lambda: self.manage_qualifications())

    def stretch_columns(self):
        return {1, 2, 5}

    def leading_actions(self):
        self.record_button = button("Fiche", tooltip="Consulter la fiche de l'enseignant (Entrée)")
        return [self.record_button]

    def extra_actions(self):
        self.qualifications_button = button("Qualifications")
        return [self.qualifications_button]

    def build_filters(self):
        """Second row (under the search): the toolbar stays readable at 1024 px."""
        layout = QHBoxLayout()
        layout.setSpacing(8)
        self.category_filter = QComboBox()
        self.category_filter.setAccessibleName("Filtrer par catégorie pédagogique")
        self.category_filter.setToolTip("Filtrer par catégorie pédagogique")
        self.category_filter.setMinimumWidth(170)
        self.category_filter.addItem(ALL_CATEGORIES, None)
        self.subject_filter = QComboBox()
        self.subject_filter.setAccessibleName("Filtrer par matière qualifiée")
        self.subject_filter.setToolTip("Filtrer par matière qualifiée")
        self.subject_filter.setMinimumWidth(170)
        self.subject_filter.addItem(ALL_SUBJECTS, None)
        for combo in (self.category_filter, self.subject_filter):
            combo.currentIndexChanged.connect(lambda _: self._filters_ready and self.reload_first_page())
            layout.addWidget(combo)
        layout.addStretch()
        self.layout_.insertLayout(2, layout)

    def update_extra_actions(self, row):
        if not hasattr(self, "qualifications_button"):
            return
        why = "Sélectionnez d'abord un enseignant dans la liste."
        for widget, tip in (
            (self.record_button, "Consulter la fiche de l'enseignant (Entrée)"),
            (self.qualifications_button, "Matières, compatibilité et dérogations"),
        ):
            widget.setEnabled(row is not None)
            widget.setToolTip(why if row is None else tip)

    def describe_row(self, row):
        return f"{row.name} ({row.number})"

    def is_filtered(self):
        return (
            super().is_filtered() or bool(self.category_filter.currentData()) or bool(self.subject_filter.currentData())
        )

    # --- filters ----------------------------------------------------------------------
    def activate(self):
        self.call(
            lambda: (self.categories.list(active=None), self.subjects.list(active=None)),
            self._fill_filters,
            action="Impossible de charger les catégories et les matières",
        )

    def _fill_filters(self, loaded):
        categories, subjects = loaded
        self._filters_ready = False
        for combo, first, items in (
            (self.category_filter, ALL_CATEGORIES, categories),
            (self.subject_filter, ALL_SUBJECTS, subjects),
        ):
            chosen = combo.currentData()
            combo.clear()
            combo.addItem(first, None)
            for item in items:
                combo.addItem(f"{item.code} — {item.name}" + ("" if item.active else " (inactive)"), item.id)
            combo.setCurrentIndex(max(0, combo.findData(chosen)))
        self._filters_ready = True
        self.reload_first_page()

    def fetch(self):
        return self.service.page(
            page=self.page_number,
            search=self.search.text(),
            status=self.status.currentData(),
            category_id=self.category_filter.currentData(),
            subject_id=self.subject_filter.currentData(),
        )

    def cells(self, row):
        subjects = ", ".join(row.subjects) or "—"
        return [
            row.number,
            row.last_name,
            row.first_name,
            row.category_label.split(" — ")[0] if row.category_label else "—",
            row.primary_subject_label or "—",
            subjects,
            "",
        ]

    def status_cell(self, row):
        from .catalog_base import status_item

        item = status_item(row.active, feminine=False)
        if not row.active:
            item.setText(f"○  {row.status_label}")
        return item

    # --- dialogs (overridable in tests) ------------------------------------------------
    def ask(self, kind, **context):
        """Open dialog `kind`; return its values / chosen action (None if cancelled)."""
        if kind == "teacher":
            dialog = TeacherDialog(context["categories"], context["subjects"], self, context.get("teacher"))
            return dialog.values() if dialog.exec() == QDialog.Accepted else None
        if kind == "remuneration":
            from ..dialogs.payroll_dialogs import TeacherPayDialog

            TeacherPayDialog(
                context["teacher"],
                context["summary"],
                context["payrolls"],
                context["validated"],
                context["date_from"],
                context["date_to"],
                self,
            ).exec()
            return None
        if kind == "record":
            dialog = TeacherRecordDialog(
                context["teacher"],
                context["qualifications"],
                context["rates"],
                self,
                with_remuneration=self.payroll is not None and bool(context["teacher"].employee_id),
            )
            return dialog.action if dialog.exec() == QDialog.Accepted else None
        dialog = QualificationsDialog(
            context["teacher"], self.service, self.runner, context["subjects"], context["levels"], self, ask=ask_reason
        )
        dialog.exec()
        if dialog.expired:
            self.session_expired.emit()
        return dialog.changed

    def _form_lists(self):
        return self.categories.list(active=True), self.subjects.list(active=True)

    # --- actions ------------------------------------------------------------------------
    def add(self):
        def open_form(lists):
            categories, subjects = lists
            values = self.ask("teacher", categories=categories, subjects=subjects)
            if values:
                self.call(
                    lambda: self.service.create(**values),
                    lambda saved: self._reselect(
                        saved.id, f"Enseignant « {saved.name} » ({saved.number}) créé avec succès."
                    ),
                    action="Impossible de créer l'enseignant",
                )

        self.call(self._form_lists, open_form, action="Impossible de charger les catégories et les matières")

    def edit(self, teacher=None):
        row = teacher or self.selected()
        if row is None:
            return

        def open_form(loaded):
            current, (categories, subjects) = loaded
            values = self.ask("teacher", categories=categories, subjects=subjects, teacher=current)
            if values:
                self.call(
                    lambda: self.service.update(current.id, **values),
                    lambda saved: self._reselect(
                        saved.id, f"Enseignant « {saved.name} » ({saved.number}) modifié avec succès."
                    ),
                    action="Impossible de modifier l'enseignant",
                )

        self.call(
            lambda: (self.service.get(row.id), self._form_lists()),
            open_form,
            action="Impossible de charger la fiche de l'enseignant",
        )

    def open_row(self):
        self.open_record()

    def open_record(self):
        row = self.selected()
        if row is None:
            return

        def show(loaded):
            teacher, qualifications, rates = loaded
            action = self.ask("record", teacher=teacher, qualifications=qualifications, rates=rates)
            if action == "edit":
                self.edit(teacher)
            elif action == "qualifications":
                self.manage_qualifications(teacher)
            elif action == "remuneration":
                self.show_remuneration(teacher)

        self.call(
            lambda: (self.service.get(row.id), self.service.qualifications(row.id), self._rates(row.id)),
            show,
            action="Impossible de charger la fiche de l'enseignant",
        )

    def show_remuneration(self, teacher):
        """Read-only: the server's remuneration of the teacher for the current
        school year, their payrolls and validated sessions. The payroll API's
        own permissions apply (a refusal is shown, never bypassed)."""
        from datetime import date, timedelta

        from ...api.errors import Forbidden, NotFound

        def load():
            years = self.references.years()
            current = next((y for y in years if y.is_current), None)
            date_from, date_to = (
                (current.start_date, current.end_date)
                if current
                else (date.today() - timedelta(days=365), date.today())
            )
            try:
                summary = self.payroll.remuneration(teacher.employee_id, date_from, date_to)
            except (Forbidden, NotFound):
                summary = None
            payrolls = self.payroll.payrolls(employee_id=teacher.employee_id)
            return summary, payrolls, self.payroll.validated_sessions(teacher.id), date_from, date_to

        def show(loaded):
            summary, payrolls, validated, date_from, date_to = loaded
            self.ask(
                "remuneration",
                teacher=teacher,
                summary=summary,
                payrolls=payrolls,
                validated=validated,
                date_from=date_from,
                date_to=date_to,
            )

        self.call(load, show, action="Impossible de charger la rémunération")

    def _rates(self, teacher_id):
        """Payroll rates are optional here: a refusal of the payroll module never
        prevents opening the record."""
        from ...api.errors import Forbidden, NotFound

        try:
            return self.service.rates(teacher_id)
        except (Forbidden, NotFound):
            return []

    def manage_qualifications(self, teacher=None):
        row = teacher or self.selected()
        if row is None:
            return

        def open_dialog(lists):
            subjects, levels = lists
            changed = self.ask("qualifications", teacher=row, subjects=subjects, levels=levels)
            if changed:
                self._reselect(row.id, f"Qualifications de « {row.name} » mises à jour.")

        self.call(
            lambda: (self.subjects.list(active=True), self.references.levels()),
            open_dialog,
            action="Impossible de charger les matières",
        )

    def deactivate(self, row_id):
        return self.service.deactivate(row_id)

    def reactivate(self, row_id):
        return self.service.reactivate(row_id)

    def _saved(self, saved, verb):
        self._reselect(saved.id, f"Enseignant « {saved.name} » ({saved.number}) {verb} avec succès.")

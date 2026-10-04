"""Gestion académique → Catégories pédagogiques / Matières."""

from PySide6.QtWidgets import QComboBox, QDialog

from ...models import SUBJECT_TYPES
from ..dialogs.category_dialog import CategoryDialog
from ..dialogs.subject_dialog import SubjectDialog
from .catalog_base import STATUS_COLUMN_TITLE, CatalogPage


class CategoriesPage(CatalogPage):
    title = "Catégories pédagogiques"
    description = "Familles de matières de l'école. Une matière appartient toujours à une catégorie."
    columns = ["Code", "Nom", "Matières actives", STATUS_COLUMN_TITLE]
    noun = "catégorie"

    def __init__(self, service, runner, parent=None, *, dialog=CategoryDialog, **kwargs):
        self.service = service
        self.dialog = dialog
        super().__init__(runner, parent, **kwargs)

    def fetch(self):
        return self.service.list(search=self.search.text(), active=self.status.currentData())

    def cells(self, row):
        count = "" if row.active_subject_count is None else str(row.active_subject_count)
        return [row.code, row.name, count, ""]

    def open_dialog(self, category=None):
        """Returns the dialog values, or None if cancelled (overridable in tests)."""
        dialog = self.dialog(self, category)
        return dialog.values() if dialog.exec() == QDialog.Accepted else None

    def add(self):
        values = self.open_dialog()
        if values:
            self.call(
                lambda: self.service.create(**values),
                lambda saved: self._saved(saved, "créée"),
                action="Impossible de créer la catégorie",
            )

    def edit(self):
        row = self.selected()
        if row is None:
            return
        values = self.open_dialog(row)
        if values:
            self.call(
                lambda: self.service.update(row.id, name=values["name"], description=values["description"]),
                lambda saved: self._saved(saved, "modifiée"),
                action="Impossible de modifier la catégorie",
            )

    def deactivate(self, row_id):
        return self.service.deactivate(row_id)

    def reactivate(self, row_id):
        return self.service.reactivate(row_id)


class SubjectsPage(CatalogPage):
    title = "Matières"
    description = "Matières enseignées, chacune rattachée à une catégorie pédagogique."
    columns = ["Code", "Nom", "Catégorie", "Type", STATUS_COLUMN_TITLE]
    noun = "matière"

    def __init__(self, service, category_service, runner, parent=None, *, dialog=SubjectDialog, **kwargs):
        self.service = service
        self.category_service = category_service
        self.dialog = dialog
        super().__init__(runner, parent, **kwargs)

    def stretch_columns(self):
        return {1, 2}  # name and category

    def add_filters(self, layout):
        self.category_filter = QComboBox()
        self.category_filter.setAccessibleName("Filtrer par catégorie")
        self.category_filter.setToolTip("Filtrer par catégorie")
        self.category_filter.setMinimumWidth(200)
        self.category_filter.addItem("Toutes les catégories", None)
        self.category_filter.currentIndexChanged.connect(lambda _: self.reload())
        layout.addWidget(self.category_filter)

    def activate(self):
        # Refresh the category filter (categories may have changed), then the list.
        self.call(
            lambda: self.category_service.list(active=None),
            self._fill_filter,
            action="Impossible de charger les catégories",
        )

    def _fill_filter(self, categories):
        current = self.category_filter.currentData()
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        self.category_filter.addItem("Toutes les catégories", None)
        for category in categories:
            suffix = "" if category.active else " (inactive)"
            self.category_filter.addItem(f"{category.code} — {category.name}{suffix}", category.id)
        self.category_filter.setCurrentIndex(max(0, self.category_filter.findData(current)))
        self.category_filter.blockSignals(False)
        self.reload()

    def fetch(self):
        return self.service.list(
            search=self.search.text(), active=self.status.currentData(), category_id=self.category_filter.currentData()
        )

    def cells(self, row):
        return [row.code, row.name, row.category_label, SUBJECT_TYPES.get(row.subject_type, row.subject_type), ""]

    def open_dialog(self, categories, subject=None):
        dialog = self.dialog(categories, self, subject)
        return dialog.values() if dialog.exec() == QDialog.Accepted else None

    def _with_categories(self, then):
        """The category list offered by the form = active categories, fresh from the API."""
        self.call(lambda: self.category_service.list(active=True), then, action="Impossible de charger les catégories")

    def add(self):
        def open_form(categories):
            values = self.open_dialog(categories)
            if values:
                self.call(
                    lambda: self.service.create(**values),
                    lambda saved: self._saved(saved, "créée"),
                    action="Impossible de créer la matière",
                )

        self._with_categories(open_form)

    def edit(self):
        row = self.selected()
        if row is None:
            return

        def open_form(categories):
            values = self.open_dialog(categories, row)
            if values:
                self.call(
                    lambda: self.service.update(
                        row.id,
                        name=values["name"],
                        category_id=values["category_id"],
                        subject_type=values["subject_type"],
                        public_visible=values["public_visible"],
                    ),
                    lambda saved: self._saved(saved, "modifiée"),
                    action="Impossible de modifier la matière",
                )

        self._with_categories(open_form)

    def deactivate(self, row_id):
        return self.service.deactivate(row_id)

    def reactivate(self, row_id):
        return self.service.reactivate(row_id)

"""Documents → Plans: the school's 2D plans (imported, never drawn here).

List of the plans (filter: status, building), « Ajouter » (a draft),
« Modifier » (information — never notifies), « Versions… » (history, import,
preview, publication), « Diffusion… » (AUTO / MANUAL, audience, who has
access), « Retirer » (with a reason). Every call goes through the API, off the
UI thread (a 20 MB upload never freezes the window); every rule is the
server's. Hooks (open_* / choose_file / save_path) are overridable in tests.
"""

from pathlib import Path

from PySide6.QtWidgets import QComboBox, QDialog, QFileDialog

from ...i18n import Tr, tr
from ...models import PLAN_STATUSES
from ...services.plans import FILE_FILTER
from ..dialogs.plan_dialogs import DiffusionDialog, PlanDialog, PreviewDialog, VersionsDialog
from ..dialogs.teacher_dialogs import ask_reason
from ..feedback import describe
from ..theme import TOKENS, TokenColours
from ..widgets import button
from .catalog_base import STATUS_COLUMN_TITLE, CatalogPage
from .finance_page import coloured

ALL_BUILDINGS = "Tous les bâtiments"
STATUS_COLOURS = TokenColours(PUBLISHED="success", WITHDRAWN="text_secondary", DRAFT="warning")


def choose_plan_file(parent):
    path, _ = QFileDialog.getOpenFileName(parent, tr("Importer un plan (PDF, PNG ou JPEG)"), "", tr(FILE_FILTER))
    return path


def ask_save_path(parent, name):
    path, _ = QFileDialog.getSaveFileName(parent, tr("Enregistrer le plan"), name)
    return path


class PlansPage(CatalogPage):
    title = Tr("Plans")
    description = Tr(
        "Plans 2D des locaux, dessinés dans un logiciel d'architecture puis importés ici (PDF, PNG ou JPEG). "
        "Exportez un DWG / DXF en PDF avant de l'importer."
    )
    columns = Tr(["Titre", "Bâtiment · niveau", "Version publiée", "Diffusion", "Publié le", STATUS_COLUMN_TITLE])
    noun = "plan"
    feminine = False
    search_placeholder = Tr("Rechercher par titre…")
    status_filters = Tr([("Statut : tous", None), *((label, code) for code, label in PLAN_STATUSES.items())])
    has_toggle = False
    narrow_hidden = (3, 4)

    def __init__(self, service, references, runner, parent=None, **kwargs):
        self.service = service
        self.references = references
        self.choose_file = choose_plan_file
        self.save_path = ask_save_path
        self.ask_withdraw = ask_reason
        super().__init__(runner, parent, **kwargs)

    # --- list ------------------------------------------------------------------------
    def stretch_columns(self):
        return {0, 1}

    def extra_actions(self):
        self.versions_button = button(tr("Versions…"), tooltip=tr("Historique, import, aperçu et publication"))
        self.diffusion_button = button(tr("Diffusion…"), tooltip=tr("Qui peut consulter ce plan"))
        self.withdraw_button = button(tr("Retirer"), "danger", tooltip=tr("Le plan disparaît pour tous les lecteurs"))
        self.versions_button.clicked.connect(self.versions)
        self.diffusion_button.clicked.connect(self.diffusion)
        self.withdraw_button.clicked.connect(self.withdraw)
        return [self.versions_button, self.diffusion_button, self.withdraw_button]

    def update_extra_actions(self, row):
        if not hasattr(self, "versions_button"):
            return
        self.versions_button.setEnabled(row is not None)
        self.diffusion_button.setEnabled(row is not None)
        self.withdraw_button.setEnabled(row is not None and row.status == "PUBLISHED")

    def add_filters(self, layout):
        self.building_filter = QComboBox()
        self.building_filter.setAccessibleName(tr("Filtrer par bâtiment"))
        self.building_filter.setToolTip(tr("Filtrer par bâtiment"))
        self.building_filter.setMinimumWidth(180)
        self.building_filter.addItem(tr(ALL_BUILDINGS), None)
        self.building_filter.currentIndexChanged.connect(lambda _: self._apply_building())
        layout.addWidget(self.building_filter)

    def is_filtered(self):
        return super().is_filtered() or bool(self.building_filter.currentData())

    def describe_row(self, row):
        return row.title

    def status_cell(self, row):
        return coloured(row.status_label, STATUS_COLOURS.get(row.status, TOKENS.text))

    def fetch(self):
        rows = self.service.list(status=self.status.currentData())
        search = self.search.text().strip().lower()
        return [r for r in rows if not search or search in r.title.lower()]

    def show_rows(self, rows):
        self._all_rows = list(rows)
        current = self.building_filter.currentData()
        self.building_filter.blockSignals(True)
        self.building_filter.clear()
        self.building_filter.addItem(tr(ALL_BUILDINGS), None)
        for building in sorted({r.building for r in rows if r.building}):
            self.building_filter.addItem(building, building)
        self.building_filter.setCurrentIndex(max(0, self.building_filter.findData(current)))
        self.building_filter.blockSignals(False)
        chosen = self.building_filter.currentData()
        super().show_rows([r for r in rows if not chosen or r.building == chosen])

    def _apply_building(self):
        if hasattr(self, "_all_rows"):
            self.show_rows(self._all_rows)

    def cells(self, row):
        current = row.current_version
        published = f"v{current.number} · {current.details}" if current and row.status == "PUBLISHED" else "—"
        when = f"{row.published_at:%d/%m/%Y}" if row.published_at and row.status == "PUBLISHED" else "—"
        return [row.title, row.location, published, row.distribution_label, when, ""]

    # --- create / edit -------------------------------------------------------------------
    def open_plan_dialog(self, plan=None):
        dialog = PlanDialog(self, plan)
        return dialog.values() if dialog.exec() == QDialog.Accepted else None

    def add(self):
        values = self.open_plan_dialog()
        if values:
            self.call(
                lambda: self.service.create(**values),
                lambda saved: self._saved(saved, tr("créé")),
                action=tr("Impossible de créer le plan"),
            )

    def edit(self):
        row = self.selected()
        if row is None:
            return
        values = self.open_plan_dialog(row)
        if values:
            self.call(
                lambda: self.service.update(row.id, **values),
                lambda saved: self._saved(saved, tr("modifié")),
                action=tr("Impossible de modifier le plan"),
            )

    # --- versions ------------------------------------------------------------------------
    def in_dialog(self, dialog, fn, on_success, action):
        """API call whose errors are shown IN the open dialog (it is modal)."""
        self.set_busy(True)

        def ok(result):
            self.set_busy(False)
            on_success(result)

        def failed(exc):
            self.set_busy(False)
            feedback = describe(exc, action)
            if feedback.session_expired:
                dialog.reject()
                self.session_expired.emit()
                return
            dialog.show_message(feedback.kind, feedback.text, title=feedback.title)

        self.runner.run(fn, ok, failed)

    def open_versions(self, plan, versions):
        dialog = VersionsDialog(
            plan,
            versions,
            self,
            on_import=self.import_version,
            on_preview=self.preview,
            on_publish=self.publish,
            on_save=self.save_version,
        )
        dialog.exec()

    def versions(self):
        row = self.selected()
        if row is not None:
            self.call(
                lambda: self.service.versions(row.id),
                lambda versions: self.open_versions(row, versions),
                action=tr("Impossible de charger les versions"),
            )

    def _refresh_versions(self, dialog, message):
        plan_id = dialog.plan.id
        self.in_dialog(
            dialog,
            lambda: (self.service.get(plan_id), self.service.versions(plan_id)),
            lambda result: (
                dialog.set_versions(result[1], result[0]),
                dialog.show_message("success", message),
                self.reload(),
            ),
            tr("Impossible d'actualiser les versions"),
        )

    def import_version(self, dialog):
        path = self.choose_file(dialog)
        if not path:
            return
        dialog.show_message("info", tr("Envoi de « {0} »… le serveur vérifie le fichier.", Path(path).name))
        self.in_dialog(
            dialog,
            lambda: self.service.upload(dialog.plan.id, path),
            lambda version: self._refresh_versions(
                dialog,
                tr("Version {0} importée ({1}). Elle n'est pas encore publiée.", version.number, version.details),
            ),
            tr("Import refusé"),
        )

    def open_preview(self, title, content, mime_type, parent):
        PreviewDialog(title, content, mime_type, parent).exec()

    def preview(self, dialog, version):
        self.in_dialog(
            dialog,
            lambda: self.service.version_file(dialog.plan.id, version.id),
            lambda content: self.open_preview(
                f"{dialog.plan.title} v{version.number}", content, version.mime_type, dialog
            ),
            tr("Aperçu impossible"),
        )

    def publish(self, dialog, version):
        readers = tr("les lecteurs autorisés (selon la diffusion) seront notifiés")
        if not self.confirm(
            dialog,
            tr("Publier cette version"),
            tr(
                "Publier la version {0} de « {1} » ? Elle remplace la version actuelle ; {2}.",
                version.number,
                dialog.plan.title,
                readers,
            ),
            confirm_text=tr("Publier"),
        ):
            return
        self.in_dialog(
            dialog,
            lambda: self.service.publish(dialog.plan.id, version.id),
            lambda plan: self._refresh_versions(dialog, tr("Version {0} publiée.", version.number)),
            tr("Publication impossible"),
        )

    def save_version(self, dialog, version):
        suffix = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}.get(version.mime_type, "")
        target = self.save_path(dialog, f"{dialog.plan.title}-v{version.number}{suffix}")
        if not target:
            return
        self.in_dialog(
            dialog,
            lambda: Path(target).write_bytes(self.service.version_file(dialog.plan.id, version.id)),
            lambda _: dialog.show_message("success", tr("Enregistré : {0}", Path(target).name)),
            tr("Enregistrement impossible"),
        )

    # --- distribution ----------------------------------------------------------------------
    def open_diffusion(self, plan, classes, access):
        dialog = DiffusionDialog(plan, classes, access, self)
        return dialog.values() if dialog.exec() == QDialog.Accepted else None

    def diffusion(self):
        row = self.selected()
        if row is None:
            return

        def apply(values):
            plan_id, mode, entries = row.id, values["distribution"], values["entries"]

            def steps():
                # MANUAL: audience first (a published MANUAL plan always has readers);
                # AUTO: mode first (an emptied audience is then harmless).
                if mode == "MANUAL":
                    self.service.set_audience(plan_id, entries)
                    return self.service.set_distribution(plan_id, mode)
                plan = self.service.set_distribution(plan_id, mode)
                self.service.set_audience(plan_id, entries)
                return plan

            self.call(
                steps,
                lambda saved: self._saved(saved, tr("mis à jour (diffusion)")),
                action=tr("Impossible de modifier la diffusion"),
            )

        def open_form(loaded):
            plan, classes, access = loaded
            values = self.open_diffusion(plan, classes, access)
            if values:
                apply(values)

        self.call(
            lambda: (self.service.get(row.id), self.references.classes(), self.service.access(row.id)),
            open_form,
            action=tr("Impossible de charger la diffusion"),
        )

    # --- withdraw -----------------------------------------------------------------------------
    def withdraw(self):
        row = self.selected()
        if row is None or row.status != "PUBLISHED":
            return
        answer = self.ask_withdraw(
            self,
            tr("Retirer le plan"),
            tr(
                "« {0} » disparaîtra aussitôt des applications Parent et Enseignant ; les versions restent "
                "conservées et le plan pourra être republié. Personne n'est notifié.",
                row.title,
            ),
            save_text=tr("Retirer"),
            danger=True,
        )
        if answer:
            self.call(
                lambda: self.service.withdraw(row.id, answer["reason"]),
                lambda saved: self._saved(saved, tr("retiré")),
                action=tr("Impossible de retirer le plan"),
            )

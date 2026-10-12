"""Documents → Plans: the dialogs. No drawing here — School Managing never
edits a plan; it imports the PDF / image an architect produced, shows it,
publishes a version and chooses who may see it. Every rule (file content,
publication, audience, access) is the server's.

    PlanDialog       title, description, building, floor, order (+ distribution when creating)
    VersionsDialog   history, « Importer… », « Aperçu », « Publier cette version », « Enregistrer sous… »
    PreviewDialog    PDF (QtPdf) or image (zoom, scroll) — from bytes, nothing written to disk
    DiffusionDialog  AUTO / MANUAL, audience (school roles, classes), « Qui a accès ? »
"""

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QIntValidator, QPixmap
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QRadioButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...models import PLAN_AUDIENCE_TARGETS, PLAN_DISTRIBUTIONS
from ..widgets import Banner, FormDialog, button

NO_AUDIENCE = "Destinataires (au moins un public en diffusion manuelle)"


def _when(moment):
    return f"{moment:%d/%m/%Y %H:%M}" if moment else "—"


def _text(placeholder, height=80):
    widget = QPlainTextEdit(placeholderText=placeholder)
    widget.setFixedHeight(height)
    widget.setTabChangesFocus(True)
    return widget


# =============================================================================
# Plan information
# =============================================================================


class PlanDialog(FormDialog):
    def __init__(self, parent=None, plan=None):
        editing = plan is not None
        super().__init__(
            "Modifier le plan" if editing else "Nouveau plan",
            "Les informations aident les familles et les enseignants à trouver le bon plan. "
            "Changer ces informations ne notifie personne.",
            parent,
        )
        self.title = self.add_field(
            "title", "Titre", QLineEdit(placeholderText="Ex. Plan général, Bâtiment A", maxLength=200), required=True
        )
        self.building = self.add_field(
            "building",
            "Bâtiment",
            QLineEdit(placeholderText="Ex. Bâtiment A", maxLength=100),
            width="medium",
            help_text="Facultatif.",
        )
        self.floor = self.add_field(
            "floor",
            "Niveau / étage",
            QLineEdit(placeholderText="Ex. Rez-de-chaussée", maxLength=60),
            width="medium",
            beside=True,
            help_text="Facultatif.",
        )
        order = QLineEdit(placeholderText="0", maxLength=4)
        order.setValidator(QIntValidator(0, 9999, order))
        self.order = self.add_field(
            "display_order", "Ordre d'affichage", order, width="short", help_text="Petit = en haut."
        )
        self.description = self.add_field(
            "description", "Description", _text("Ce que montre le plan, repères utiles (accueil, salles, blocs)…")
        )
        self.distribution = None
        if not editing:
            self.distribution = QComboBox()
            for code, label in PLAN_DISTRIBUTIONS.items():
                self.distribution.addItem(label, code)
            self.add_field(
                "distribution",
                "Diffusion",
                self.distribution,
                width="medium",
                help_text="Automatique : parents vérifiés et enseignants de l'école. "
                "Modifiable ensuite (« Diffusion… »).",
            )
        if editing:
            self.title.setText(plan.title)
            self.building.setText(plan.building)
            self.floor.setText(plan.floor)
            self.order.setText(str(plan.display_order or ""))
            self.description.setPlainText(plan.description)
        self.title.textChanged.connect(self.refresh_state)
        self.finish()
        self.title.setFocus()

    def missing_fields(self):
        return [] if self.title.text().strip() else ["Titre"]

    def values(self):
        values = {
            "title": self.title.text().strip(),
            "description": self.description.toPlainText().strip(),
            "building": self.building.text().strip(),
            "floor": self.floor.text().strip(),
            "display_order": int(self.order.text()) if self.order.text().strip() else 0,
        }
        if self.distribution is not None:
            values["distribution"] = self.distribution.currentData()
        return values


# =============================================================================
# Versions: history, import, preview, publication
# =============================================================================


class VersionsDialog(FormDialog):
    """Actions call back the page (API calls off the UI thread); the page then
    refreshes this dialog with `set_versions` / `show_message`."""

    COLUMNS = ["Version", "Fichier", "Format", "Importée le", "Par", "Statut"]

    def __init__(self, plan, versions, parent=None, *, on_import, on_preview, on_publish, on_save):
        super().__init__(
            f"Versions — {plan.title}",
            "Importer n'est pas publier : les lecteurs voient la version publiée tant que vous n'en publiez pas "
            "une autre. Les anciennes versions sont conservées (consultables ici seulement).",
            parent,
            save_text="Fermer",
            width=820,
        )
        self.plan = plan
        self.cancel_button.hide()
        self.banner = Banner()
        self.body.addWidget(self.banner)
        actions = QHBoxLayout()
        self.import_button = button("Importer une version…", "primary", tooltip="PDF, PNG ou JPEG (20 Mo au plus)")
        self.preview_button = button("Aperçu", tooltip="Voir la version sélectionnée")
        self.publish_button = button("Publier cette version", tooltip="Les lecteurs autorisés seront notifiés")
        self.save_as_button = button("Enregistrer sous…")
        for widget in (self.import_button, self.preview_button, self.publish_button, self.save_as_button):
            actions.addWidget(widget)
        actions.addStretch()
        self.body.addLayout(actions)
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setMinimumHeight(200)
        self.body.addWidget(self.table)
        self.import_button.clicked.connect(lambda: on_import(self))
        self.preview_button.clicked.connect(lambda: self.selected() and on_preview(self, self.selected()))
        self.publish_button.clicked.connect(lambda: self.selected() and on_publish(self, self.selected()))
        self.save_as_button.clicked.connect(lambda: self.selected() and on_save(self, self.selected()))
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.itemDoubleClicked.connect(lambda _: self.selected() and on_preview(self, self.selected()))
        self.set_versions(versions)
        self.finish(required_note=False)

    def set_versions(self, versions, plan=None):
        self.plan = plan or self.plan
        self.versions = list(versions)
        self.table.setRowCount(len(self.versions))
        for row, version in enumerate(self.versions):
            cells = [
                f"v{version.number}",
                version.original_name,
                version.details,
                _when(version.uploaded_at),
                version.uploaded_by,
                version.status_label,
            ]
            for column, text in enumerate(cells):
                self.table.setItem(row, column, QTableWidgetItem(text))
        if self.versions:
            self.table.selectRow(0)
        self._update_buttons()

    def selected(self):
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        return self.versions[rows[0].row()] if rows else None

    def _update_buttons(self):
        version = self.selected()
        for widget in (self.preview_button, self.save_as_button):
            widget.setEnabled(version is not None)
        live = version is not None and version.is_current and self.plan.status == "PUBLISHED"
        self.publish_button.setEnabled(version is not None and not live)
        self.publish_button.setToolTip(
            "Déjà la version que voient les lecteurs." if live else "Les lecteurs autorisés seront notifiés"
        )

    def show_message(self, kind, text, title=""):
        self.banner.show_message(kind, text, title=title, autohide=kind == "success")


class PreviewDialog(QDialog):
    """A plan shown from its bytes (nothing written to disk): PDF with QtPdf,
    image with zoom and scrolling. Sized to the screen."""

    def __init__(self, title, content, mime_type, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Aperçu — {title}")
        layout = QVBoxLayout(self)
        self.zoom = 1.0
        if mime_type == "application/pdf":
            self.buffer = QBuffer(self)
            self.buffer.setData(QByteArray(content))
            self.buffer.open(QIODevice.ReadOnly)
            self.document = QPdfDocument(self)
            self.document.load(self.buffer)
            self.view = QPdfView(self)
            self.view.setDocument(self.document)
            self.view.setPageMode(QPdfView.PageMode.MultiPage)
            self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            layout.addWidget(self.view)
            self.pages = self.document.pageCount()
        else:
            self.pixmap = QPixmap()
            self.pixmap.loadFromData(content)
            tools = QHBoxLayout()
            self.zoom_out = button("−", tooltip="Réduire")
            self.zoom_in = button("+", tooltip="Agrandir")
            self.fit = button("Ajuster", tooltip="Voir le plan entier")
            for widget in (self.zoom_out, self.zoom_in, self.fit):
                tools.addWidget(widget)
            tools.addStretch()
            layout.addLayout(tools)
            self.image = QLabel(alignment=Qt.AlignCenter)
            self.area = QScrollArea()
            self.area.setWidget(self.image)
            self.area.setAlignment(Qt.AlignCenter)
            layout.addWidget(self.area)
            self.zoom_in.clicked.connect(lambda: self.set_zoom(self.zoom * 1.25))
            self.zoom_out.clicked.connect(lambda: self.set_zoom(self.zoom / 1.25))
            self.fit.clicked.connect(self.fit_to_window)
            self.pages = 1
        close = button("Fermer", "primary")
        close.clicked.connect(self.accept)
        footer = QHBoxLayout()
        footer.addStretch()
        footer.addWidget(close)
        layout.addLayout(footer)
        screen = (parent.screen() if parent is not None else None) or QGuiApplication.primaryScreen()
        available = screen.availableGeometry()
        self.resize(int(available.width() * 0.8), int(available.height() * 0.8))
        if mime_type != "application/pdf":
            self.fit_to_window()

    @property
    def is_valid(self):
        return self.pages > 0 if hasattr(self, "document") else not self.pixmap.isNull()

    def set_zoom(self, zoom):
        self.zoom = max(0.05, min(zoom, 8.0))
        size = self.pixmap.size() * self.zoom
        self.image.setPixmap(self.pixmap.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.image.resize(self.image.pixmap().size())

    def fit_to_window(self):
        if self.pixmap.isNull():
            return
        target = self.area.viewport().size()
        ratio = min(target.width() / self.pixmap.width(), target.height() / self.pixmap.height())
        self.set_zoom(ratio if ratio > 0 else 1.0)


# =============================================================================
# Distribution: AUTO / MANUAL, audience, who has access
# =============================================================================


class DiffusionDialog(FormDialog):
    """`classes`: the school's classes (ids from the API); `access`: the
    server's answer to « who can see it now » (count + readers)."""

    def __init__(self, plan, classes, access, parent=None):
        super().__init__(
            f"Diffusion — {plan.title}",
            "Qui peut consulter ce plan dans les applications Parent et Enseignant. Le serveur revérifie les droits "
            "à chaque ouverture : un parent qui n'est plus vérifié ou un retrait du plan ferment l'accès aussitôt. "
            "Gardiens et personnel n'y ont pas accès.",
            parent,
            width=720,
        )
        self.mode_group = QButtonGroup(self)
        modes = QWidget()
        column = QVBoxLayout(modes)
        column.setContentsMargins(0, 0, 0, 0)
        self.auto = QRadioButton("Automatique : tous les parents vérifiés et tous les enseignants en activité")
        self.manual = QRadioButton("Manuelle : seulement les publics cochés ci-dessous")
        for radio in (self.auto, self.manual):
            self.mode_group.addButton(radio)
            column.addWidget(radio)
        self.add_field("distribution", "Mode", modes)
        audience = {(row["target"], row.get("school_class")) for row in plan.audience}
        self.school_parents = QCheckBox(PLAN_AUDIENCE_TARGETS["SCHOOL_PARENTS"])
        self.school_teachers = QCheckBox(PLAN_AUDIENCE_TARGETS["SCHOOL_TEACHERS"])
        self.school_parents.setChecked(("SCHOOL_PARENTS", None) in audience)
        self.school_teachers.setChecked(("SCHOOL_TEACHERS", None) in audience)
        school = QWidget()
        rows = QVBoxLayout(school)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.addWidget(self.school_parents)
        rows.addWidget(self.school_teachers)
        self.add_field("school_audience", "Toute l'école", school)
        self.classes = list(classes)
        self.table = QTableWidget(len(self.classes), 3)
        self.table.setHorizontalHeaderLabels(["Classe", "Parents", "Enseignants"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for row, klass in enumerate(self.classes):
            self.table.setItem(row, 0, QTableWidgetItem(f"{klass.name} — {klass.year_name}"))
            for column, target in ((1, "CLASS_PARENTS"), (2, "CLASS_TEACHERS")):
                item = QTableWidgetItem()
                item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                item.setCheckState(Qt.Checked if (target, klass.id) in audience else Qt.Unchecked)
                self.table.setItem(row, column, item)
        self.table.setMinimumHeight(min(260, 40 + 32 * max(1, len(self.classes))))
        self.add_field("class_audience", "Par classe", self.table)
        names = ", ".join(reader["name"] for reader in access.get("readers", [])[:30])
        more = access.get("count", 0) - min(30, len(access.get("readers", [])))
        summary = QLabel(
            f"{access.get('count', 0)} personne(s) peuvent le consulter actuellement"
            + (f" : {names}" + (f" et {more} autre(s)" if more > 0 else "") if names else ".")
            + ("" if access.get("published") else " (une fois le plan publié)."),
            objectName="help",
        )
        summary.setWordWrap(True)
        self.add_field("access", "Qui a accès ?", summary)
        (self.manual if plan.distribution == "MANUAL" else self.auto).setChecked(True)
        for signal in (self.auto.toggled, self.school_parents.toggled, self.school_teachers.toggled):
            signal.connect(lambda *_: self._sync())
        self.table.itemChanged.connect(lambda *_: self.refresh_state())
        self._sync()
        self.finish(required_note=False)

    def _sync(self):
        manual = self.manual.isChecked()
        for widget in (self.school_parents, self.school_teachers, self.table):
            widget.setEnabled(manual)
        self.refresh_state()

    def entries(self):
        entries = []
        if self.school_parents.isChecked():
            entries.append(("SCHOOL_PARENTS", None))
        if self.school_teachers.isChecked():
            entries.append(("SCHOOL_TEACHERS", None))
        for row, klass in enumerate(self.classes):
            for column, target in ((1, "CLASS_PARENTS"), (2, "CLASS_TEACHERS")):
                item = self.table.item(row, column)
                if item is not None and item.checkState() == Qt.Checked:
                    entries.append((target, klass.id))
        return entries

    def missing_fields(self):
        if getattr(self, "manual", None) is not None and self.manual.isChecked() and not self.entries():
            return [NO_AUDIENCE]
        return []

    def values(self):
        return {"distribution": "MANUAL" if self.manual.isChecked() else "AUTO", "entries": self.entries()}

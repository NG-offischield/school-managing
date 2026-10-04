"""Gestion → Documents (ADR 0023): the admin face of the EXISTING `Document`
registry (ADR 0016). One tab per family:

    Bulletins · Cartes élèves · Emplois du temps · Reçus · Bulletins de paie · Relevés de présence

Each tab: server-paginated list (search on title / verification code, status
filter), detail, generation (the source is chosen, the SERVER builds the PDF
with the school's branding — SchoolBranding, never the software's), download
(permission checked and traced by the server), regeneration of a provisional
document, authenticity check by code. No PDF logic in the desktop.
"""

from PySide6.QtWidgets import QDialog, QFileDialog, QTabWidget

from ...models import DOCUMENT_KINDS, DOCUMENT_STATUSES
from ..dialogs.document_dialogs import (
    ComputeReportCardsDialog,
    DocumentDetailDialog,
    GenerateDocumentDialog,
    VerifyDialog,
)
from ..theme import TOKENS
from ..widgets import Page, button
from .catalog_base import STATUS_COLUMN_TITLE, PagedCatalogPage
from .finance_page import coloured
from .planning_page import _combo

TABS = (
    ("report_cards", "Bulletins", ("REPORT_CARD",)),
    ("cards", "Cartes élèves", ("STUDENT_CARD",)),
    ("timetables", "Emplois du temps", ("TIMETABLE",)),
    ("receipts", "Reçus", ("PAYMENT_RECEIPT",)),
    ("payslips", "Bulletins de paie", ("PAYSLIP",)),
    ("attendance", "Relevés de présence", ("STUDENT_ATTENDANCE", "CLASS_ATTENDANCE")),
)
STATUS_COLOURS = {"OFFICIAL": TOKENS.success, "PROVISIONAL": TOKENS.warning}


def ask_save_path(parent, name):
    path, _ = QFileDialog.getSaveFileName(parent, "Enregistrer le PDF", name, "PDF (*.pdf)")
    return path


class DocumentKindPage(PagedCatalogPage):
    columns = ["Titre", "Type", "Version", "Généré le", "Code de vérification", STATUS_COLUMN_TITLE]
    noun = "document"
    feminine = False
    search_placeholder = "Rechercher par titre ou code de vérification…"
    status_filters = [("Statut : tous", None), *((label, code) for code, label in DOCUMENT_STATUSES.items())]
    has_toggle = False
    narrow_hidden = (1, 2)

    def __init__(self, title, kinds, sources, runner, parent=None, **kwargs):
        self.title, self.kinds, self.sources = title, kinds, sources
        self.documents = sources["documents"]
        self.description = "Documents officiels de l'école, produits par le serveur aux couleurs de l'établissement."
        self.save_path = ask_save_path
        super().__init__(runner, parent, **kwargs)
        self.edit_button.hide()
        self.add_button.setText("Générer…")
        self.add_button.setToolTip("Générer (ou retrouver) le document à jour")
        self.detail_button.clicked.connect(self.open_row)
        self.download_button.clicked.connect(lambda: self.download(self.selected()))
        self.regenerate_button.clicked.connect(lambda: self.regenerate(self.selected()))
        self.verify_button.clicked.connect(self.verify)
        if self.compute_button is not None:
            self.compute_button.clicked.connect(self.compute_report_cards)

    def stretch_columns(self):
        return {0}

    def leading_actions(self):
        self.detail_button = button("Détail", tooltip="Métadonnées du document (Entrée)")
        return [self.detail_button]

    def extra_actions(self):
        self.verify_button = button("Vérifier…", tooltip="Authenticité d'un document imprimé")
        self.regenerate_button = button("Regénérer")
        self.download_button = button("Télécharger…")
        self.compute_button = button("Calculer les bulletins…") if self.kinds == ("REPORT_CARD",) else None
        extras = [self.verify_button, self.regenerate_button, self.download_button]
        return [self.compute_button, *extras] if self.compute_button else extras

    def add_filters(self, layout):
        self.kind_filter = None
        if len(self.kinds) > 1:
            self.kind_filter = _combo("Type de document", DOCUMENT_KINDS[self.kinds[0]], 190)
            self.kind_filter.setItemData(0, self.kinds[0])
            for kind in self.kinds[1:]:
                self.kind_filter.addItem(DOCUMENT_KINDS[kind], kind)
            self.kind_filter.currentIndexChanged.connect(lambda _: self.reload_first_page())
            layout.addWidget(self.kind_filter)

    @property
    def kind(self):
        return self.kind_filter.currentData() if self.kind_filter is not None else self.kinds[0]

    def update_extra_actions(self, row):
        if hasattr(self, "download_button"):
            self.detail_button.setEnabled(row is not None)
            self.download_button.setEnabled(row is not None)
            provisional = row is not None and row.status == "PROVISIONAL"
            self.regenerate_button.setEnabled(provisional)
            self.regenerate_button.setToolTip("" if provisional else "Seul un document provisoire se regénère.")

    def status_cell(self, row):
        return coloured(row.status_label, STATUS_COLOURS.get(row.status, TOKENS.text_secondary))

    def fetch(self):
        return self.documents.documents(
            page=self.page_number, kind=self.kind, status=self.status.currentData(), search=self.search.text()
        )

    def cells(self, row):
        when = row.generated_at
        return [
            row.title,
            row.kind_label,
            str(row.version),
            (f"{when:%d/%m/%Y %H:%M}" if when else "—", when.isoformat() if when else ""),
            row.verification_code or "—",
            "",
        ]

    def describe_row(self, row):
        return row.title

    # --- dialogs (overridable in tests) ---
    def ask(self, kind, **context):
        if kind == "generate":
            dialog = GenerateDocumentDialog(context["document_kind"], context["sources"], self)
            return dialog.values() if dialog.exec() == QDialog.Accepted else None
        if kind == "detail":
            dialog = DocumentDetailDialog(context["document"], self)
            return dialog.action if dialog.exec() == QDialog.Accepted else None
        if kind == "compute":
            dialog = ComputeReportCardsDialog(context["classes"], context["periods"], self)
            return dialog.values() if dialog.exec() == QDialog.Accepted else None
        dialog = VerifyDialog(self)
        return dialog.values() if dialog.exec() == QDialog.Accepted else None

    def _generation_sources(self):
        """What the generation form offers for this kind (loaded off the UI thread)."""
        s, kind = self.sources, self.kind
        context = {}
        if kind in ("TIMETABLE", "CLASS_ATTENDANCE"):
            context["classes"] = s["references"].classes()
        if kind == "TIMETABLE":
            context["teachers"] = s["teachers"].all()
        if kind == "PAYSLIP":
            context["payrolls"] = [p for p in s["payroll"].payrolls() if p.status in ("APPROVED", "PAID")]
        return context

    def add(self):
        kind = self.kind

        def open_form(context):
            context.update(
                search_students=lambda text, done: self.call(
                    lambda: self.sources["finance"].find_students(text), done, action="Recherche impossible"
                ),
                load_cards=lambda student, done: self.call(
                    lambda: self.documents.report_cards(student), done, action="Impossible de charger les bulletins"
                ),
                find_payments=lambda text, done: self.call(
                    lambda: [
                        p
                        for p in self.sources["finance"].payments(search=text)[0]
                        if p.status in ("SUCCEEDED", "PARTIALLY_REFUNDED", "REFUNDED")
                    ],
                    done,
                    action="Recherche impossible",
                ),
            )
            values = self.ask("generate", document_kind=kind, sources=context)
            if values:
                self.call(
                    lambda: self.documents.generate(kind, **values),
                    lambda document: self._reselect(
                        document.id,
                        f"{document.kind_label} prêt : « {document.title} » ({document.status_label.lower()}).",
                    ),
                    action="Impossible de générer le document",
                )

        self.call(self._generation_sources, open_form, action="Impossible de préparer la génération")

    def open_row(self):
        row = self.selected()
        if row is None:
            return

        def show(document):
            action = self.ask("detail", document=document)
            if action == "download":
                self.download(document)
            elif action == "regenerate":
                self.regenerate(document)

        self.call(lambda: self.documents.document(row.id), show, action="Impossible de charger le document")

    def edit(self):
        self.open_row()

    def download(self, document):
        if document is None:
            return
        path = self.save_path(self, document.file_name or "document.pdf")
        if not path:
            return

        def save(content):
            with open(path, "wb") as handle:
                handle.write(content)
            self.success(f"PDF enregistré : {document.file_name}.")

        self.call(lambda: self.documents.download(document.id), save, action="Impossible de télécharger le document")

    def regenerate(self, document):
        if document is None:
            return
        self.call(
            lambda: self.documents.regenerate(document.id),
            lambda saved: self._reselect(
                saved.id, f"Document regénéré (version {saved.version}) ; l'ancien est conservé."
            ),
            action="Impossible de regénérer le document",
        )

    def verify(self):
        values = self.ask("verify")
        if not values:
            return

        def show(result):
            title = result.get("title") or "(document non lisible avec vos droits)"
            state = "à jour" if result.get("current") else "remplacé par une version plus récente"
            self.banner.show_message(
                "success" if result.get("current") else "warning",
                f"{DOCUMENT_KINDS.get(result.get('kind'), result.get('kind'))} · "
                f"{DOCUMENT_STATUSES.get(result.get('status'), result.get('status'))} · {state} — {title}",
                title="Document authentique",
            )

        self.call(lambda: self.documents.verify(values["code"]), show, action="Code inconnu pour cette école")

    def compute_report_cards(self):
        def open_form(lists):
            classes, periods = lists
            values = self.ask("compute", classes=classes, periods=periods)
            if values:
                self.call(
                    lambda: self.documents.compute_report_cards(values["class_id"], values["period_id"]),
                    lambda cards: self.success(f"{len(cards)} bulletin(s) calculé(s) : générez maintenant leur PDF."),
                    action="Impossible de calculer les bulletins",
                )

        self.call(
            lambda: (self.sources["references"].classes(), self.documents.periods()),
            open_form,
            action="Impossible de charger les classes et les périodes",
        )


class DocumentsPage(Page):
    title = "Documents"

    def __init__(self, documents, finance, payroll, references, teachers, runner, parent=None, **kwargs):
        super().__init__(runner, parent, **kwargs)
        self.layout_.setContentsMargins(0, 8, 0, 0)
        sources = {
            "documents": documents,
            "finance": finance,
            "payroll": payroll,
            "references": references,
            "teachers": teachers,
        }
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.pages = {}
        for name, label, kinds in TABS:
            page = DocumentKindPage(label, kinds, sources, runner, **kwargs)
            self.pages[name] = page
            setattr(self, name, page)
            self.tabs.addTab(page, label)
            page.session_expired.connect(self.session_expired.emit)
        self.layout_.addWidget(self.tabs)
        self.tabs.currentChanged.connect(lambda _: self.tabs.currentWidget().activate())

    def activate(self):
        self.tabs.currentWidget().activate()

    def open_tab(self, name):
        page = self.pages[name]
        self.tabs.setCurrentWidget(page)
        return page

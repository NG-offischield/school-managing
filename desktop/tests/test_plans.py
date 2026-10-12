"""Documents → Plans (desktop): list, create / edit, import (bytes only, off the
UI thread), real preview (QtPdf / image), publish, withdraw, distribution and
access — against the fake of documents/plans_api.py. Widget tests, not E2E."""

import pytest
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PySide6.QtGui import QImage, QPageSize, QPainter, QPdfWriter
from PySide6.QtTest import QTest

from school_admin.models import SchoolClass, SchoolPlan
from school_admin.ui.dialogs.plan_dialogs import NO_AUDIENCE, DiffusionDialog, PlanDialog, PreviewDialog, VersionsDialog

from .test_communication_documents import _fits, column, controller, open_module  # noqa: F401 (fixture)


def real_pdf():
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    writer = QPdfWriter(buffer)
    writer.setPageSize(QPageSize(QPageSize.A4))
    painter = QPainter(writer)
    painter.drawText(100, 100, "Plan du bâtiment A")
    painter.end()
    buffer.close()
    return bytes(data)


def real_png():
    image = QImage(400, 300, QImage.Format_RGB32)
    image.fill(Qt.white)
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def open_plans(ctrl):
    shell, documents = open_module(ctrl, "documents")
    return shell, documents.open_tab("plans")


def select(page, title):
    page.table.selectRow(column(page.table, 0).index(title))


def versions_dialog(page):
    """The page's « Versions… » without the modal loop: the dialog is returned."""
    captured = {}

    def open_versions(plan, versions):
        captured["dialog"] = VersionsDialog(
            plan,
            versions,
            page,
            on_import=page.import_version,
            on_preview=page.preview,
            on_publish=page.publish,
            on_save=page.save_version,
        )

    page.open_versions = open_versions
    page.versions()
    return captured["dialog"]


def test_plans_tab_lists_plans(controller, backend):  # noqa: F811
    pid = backend.add_plan("Plan général", building="Bâtiment A", floor="RDC")
    backend.add_plan_version(pid)
    backend.add_plan("Annexe")
    shell, page = open_plans(controller)
    assert shell.pages["documents"].tabs.tabText(shell.pages["documents"].tabs.count() - 1) == "Plans"
    assert sorted(column(page.table, 0)) == ["Annexe", "Plan général"]
    row = column(page.table, 0).index("Plan général")
    assert page.table.item(row, 1).text() == "Bâtiment A · RDC" and page.table.item(row, 5).text() == "Brouillon"
    assert [page.building_filter.itemText(i) for i in range(page.building_filter.count())] == [
        "Tous les bâtiments",
        "Bâtiment A",
    ]
    page.building_filter.setCurrentIndex(1)
    assert column(page.table, 0) == ["Plan général"]


def test_create_and_edit_a_plan(controller, backend):  # noqa: F811
    _, page = open_plans(controller)
    page.open_plan_dialog = lambda plan=None: {
        "title": "Bâtiment B",
        "description": "Salles 20 à 29",
        "building": "B",
        "floor": "1er",
        "display_order": 2,
        "distribution": "MANUAL",
    }
    page.add()
    assert page.banner.plain_text() == "Plan « Bâtiment B » créé avec succès."
    created = next(p for p in backend.plans.values() if p["title"] == "Bâtiment B")
    assert (created["distribution"], created["status"]) == ("MANUAL", "DRAFT")
    select(page, "Bâtiment B")
    page.open_plan_dialog = lambda plan=None: {
        "title": "Bâtiment B (rénové)",
        "description": "",
        "building": "B",
        "floor": "1er",
        "display_order": 2,
    }
    page.edit()
    assert page.banner.plain_text() == "Plan « Bâtiment B (rénové) » modifié avec succès."


def test_plan_dialog_requires_a_title(qapp):
    dialog = PlanDialog()
    assert not dialog.save_enabled and "Titre" in dialog.status.text()
    QTest.keyClicks(dialog.title, "Plan du site")  # ASCII: keyClicks with accents crashes offscreen Qt
    assert dialog.save_enabled and dialog.values()["distribution"] == "AUTO"
    dialog.close()


def test_import_preview_publish(controller, backend, tmp_path):  # noqa: F811
    pid = backend.add_plan("Plan général")
    _, page = open_plans(controller)
    select(page, "Plan général")
    dialog = versions_dialog(page)
    assert dialog.table.rowCount() == 0 and not dialog.preview_button.isEnabled()
    local = tmp_path / "secret-folder" / "plan-site.pdf"
    local.parent.mkdir()
    local.write_bytes(real_pdf())
    page.choose_file = lambda parent: str(local)
    page.import_version(dialog)
    assert dialog.table.rowCount() == 1 and dialog.table.item(0, 5).text() == "Importée"
    assert "importée" in dialog.banner.plain_text() and "pas encore publiée" in dialog.banner.plain_text()
    assert b"secret-folder" not in backend.plan_uploads[-1]  # bare name + bytes, never the local path
    shown = {}
    page.open_preview = lambda title, content, mime, parent: shown.update(content=content, mime=mime)
    page.preview(dialog, dialog.selected())
    assert shown["mime"] == "application/pdf" and shown["content"].startswith(b"%PDF")
    page.confirm = lambda *a, **k: True
    page.publish(dialog, dialog.selected())
    assert backend.plans[pid]["status"] == "PUBLISHED"
    assert dialog.table.item(0, 5).text() == "Publiée (courante)" and not dialog.publish_button.isEnabled()
    assert column(page.table, 5) == ["Publié"]
    target = tmp_path / "copie.pdf"
    page.save_path = lambda parent, name: str(target)
    page.save_version(dialog, dialog.selected())
    assert target.read_bytes() == local.read_bytes()
    dialog.close()


def test_a_refused_file_is_explained_in_the_dialog(controller, backend, tmp_path):  # noqa: F811
    backend.add_plan("Plan général")
    _, page = open_plans(controller)
    select(page, "Plan général")
    dialog = versions_dialog(page)
    fake = tmp_path / "plan.pdf"
    fake.write_bytes(b"MZ\x90\x00 an executable renamed")
    page.choose_file = lambda parent: str(fake)
    page.import_version(dialog)
    assert "Format refusé" in dialog.banner.plain_text() and "DWG" in dialog.banner.plain_text()
    assert dialog.table.rowCount() == 0
    dialog.close()


def test_publishing_manual_without_audience_is_explained(controller, backend):  # noqa: F811
    pid = backend.add_plan("Aile 3e", distribution="MANUAL")
    backend.add_plan_version(pid)
    _, page = open_plans(controller)
    select(page, "Aile 3e")
    dialog = versions_dialog(page)
    page.confirm = lambda *a, **k: True
    page.publish(dialog, dialog.selected())
    assert "choisissez au moins un public" in dialog.banner.plain_text()
    assert backend.plans[pid]["status"] == "DRAFT"
    dialog.close()


def test_preview_renders_pdf_and_image(qapp):
    pdf = PreviewDialog("Plan", real_pdf(), "application/pdf")
    assert pdf.is_valid and pdf.pages == 1
    image = PreviewDialog("Plan", real_png(), "image/png")
    assert image.is_valid
    image.set_zoom(2.0)
    assert image.image.pixmap().width() == 800  # zoomed x2
    pdf.close()
    image.close()


def test_withdraw_with_a_reason(controller, backend):  # noqa: F811
    pid = backend.add_plan("Plan général")
    vid = backend.add_plan_version(pid)
    backend.plans[pid].update(status="PUBLISHED", current=vid, published_at="2026-03-04T10:00:00+01:00")
    _, page = open_plans(controller)
    select(page, "Plan général")
    assert page.withdraw_button.isEnabled()
    page.ask_withdraw = lambda *a, **k: {"reason": "Travaux"}
    page.withdraw()
    assert backend.plans[pid]["status"] == "WITHDRAWN" and backend.plans[pid]["withdraw_reason"] == "Travaux"
    assert page.banner.plain_text() == "Plan « Plan général » retiré avec succès."
    select(page, "Plan général")
    assert not page.withdraw_button.isEnabled()


def test_diffusion_manual_audience(controller, backend):  # noqa: F811
    pid = backend.add_plan("Aile 3e")
    _, page = open_plans(controller)
    select(page, "Aile 3e")
    seen = {}

    def open_diffusion(plan, classes, access):
        seen.update(classes=[c.name for c in classes], access=access)
        return {"distribution": "MANUAL", "entries": [("CLASS_PARENTS", classes[0].id), ("SCHOOL_TEACHERS", None)]}

    page.open_diffusion = open_diffusion
    page.diffusion()
    assert seen["classes"] and seen["access"]["count"] == 0
    assert backend.plans[pid]["distribution"] == "MANUAL"
    assert [e["target"] for e in backend.plans[pid]["audience"]] == ["CLASS_PARENTS", "SCHOOL_TEACHERS"]
    assert page.banner.plain_text() == "Plan « Aile 3e » mis à jour (diffusion) avec succès."


def test_diffusion_dialog(qapp):
    plan = SchoolPlan.from_api(
        {
            "id": "p1",
            "title": "Aile 3e",
            "status": "DRAFT",
            "distribution": "AUTO",
            "audience": [{"target": "CLASS_TEACHERS", "school_class": "c1"}],
        }
    )
    classes = [SchoolClass("c1", "3e A", "l3", "Troisième", "y1", "2025-2026", None, None, "", False, True)]
    access = {"published": False, "count": 0, "readers": []}
    dialog = DiffusionDialog(plan, classes, access)
    assert dialog.auto.isChecked() and not dialog.table.isEnabled() and dialog.save_enabled
    dialog.manual.setChecked(True)
    assert dialog.entries() == [("CLASS_TEACHERS", "c1")]  # the plan's audience, pre-checked
    dialog.table.item(0, 2).setCheckState(Qt.Unchecked)
    assert not dialog.save_enabled and NO_AUDIENCE in dialog.status.text()
    dialog.school_parents.setChecked(True)
    assert dialog.values() == {"distribution": "MANUAL", "entries": [("SCHOOL_PARENTS", None)]}
    dialog.close()


@pytest.mark.parametrize("size", [QSize(1366, 768), QSize(1280, 720), QSize(1024, 768)])
def test_plans_tab_fits(controller, backend, size):  # noqa: F811
    backend.add_plan("Plan général", building="Bâtiment A")
    shell, page = open_plans(controller)
    shell.resize(size)
    shell.show()
    QTest.qWaitForWindowExposed(shell)
    _fits(page, "plans")
    shell.close()

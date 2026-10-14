"""Gestion → Site ISBREE (ADR 0032): pre-enrollment review and invitation,
editorial contents, images, role resources, Android releases, profile and
readiness — against the fake of apps/website and apps/admissions admin APIs.
Widget tests, not E2E: the real APIs are covered by the backend suite."""

from school_admin.services.website import WebsiteService
from school_admin.ui.dialogs.website_dialogs import ContentDialog, InvitationDialog, StatusDialog

from .test_communication_documents import column, controller, open_module  # noqa: F401 (fixture)


def open_tab(ctrl, name):
    shell, page = open_module(ctrl, "website")
    return shell, page.open_tab(name)


def select(page, text, index=0):
    page.table.selectRow(column(page.table, index).index(text))


def confirm_always(captured):
    def confirm(_parent, title, text, **_options):
        captured.append((title, text))
        return True

    return confirm


# --- module ------------------------------------------------------------------------------


def test_module_and_tabs(controller):  # noqa: F811
    shell, page = open_module(controller, "website")
    labels = [shell.nav.item(i).text() for i in range(shell.nav.count())]
    assert "Site ISBREE" in labels
    assert [page.tabs.tabText(i) for i in range(page.tabs.count())] == [
        "Préinscriptions",
        "Pages",
        "FAQ",
        "Actualités",
        "Images",
        "Ressources",
        "Lieux",
        "Applications",
        "Profil et publication",
    ]


# --- pre-enrollments -----------------------------------------------------------------------


def test_requests_list_and_filters(controller, backend):  # noqa: F811
    _, page = open_tab(controller, "pre_enrollments")
    assert column(page.table, 0) == ["PRE-2026-0001", "PRE-2026-0002", "PRE-2026-0003"]
    assert column(page.table, 5) == ["Reçue", "En examen", "Acceptée"]
    page.search.setText("mbarga")
    page.reload_first_page()
    assert column(page.table, 0) == ["PRE-2026-0002"]


def test_status_change_offers_only_allowed_steps_and_needs_a_reason(controller, backend):  # noqa: F811
    _, page = open_tab(controller, "pre_enrollments")
    select(page, "PRE-2026-0001")
    assert page.status_button.isEnabled() and not page.invite_button.isEnabled()
    request = WebsiteService(controller.api).pre_enrollment(page.selected().id)
    dialog = StatusDialog(request)
    assert [dialog.target.itemData(i) for i in range(dialog.target.count())] == [
        "INFO_REQUESTED",
        "REJECTED",
        "UNDER_REVIEW",
    ]
    dialog.target.setCurrentIndex(dialog.target.findData("REJECTED"))
    assert dialog.missing_fields() == ["Motif interne"]  # a refusal needs a reason
    dialog.close()

    page.ask = lambda kind, req: {"status": "UNDER_REVIEW", "note": "", "message_to_family": None}
    page.change_status()
    assert column(page.table, 5)[0] == "En examen"


def test_invitation_only_for_accepted_requests_and_shown_once(controller, backend):  # noqa: F811
    _, page = open_tab(controller, "pre_enrollments")
    captured, shown = [], []
    page.confirm = confirm_always(captured)
    page.show_invitation = shown.append
    select(page, "PRE-2026-0002")
    assert not page.invite_button.isEnabled()
    assert "acceptée" in page.invite_button.toolTip()
    select(page, "PRE-2026-0003")
    assert page.invite_button.isEnabled()
    page.invite()
    title, text = captured[0]
    assert title == "Inviter la famille ?" and "sans aucun enfant rattaché" in text and "Aucun e-mail" in text
    assert shown[0]["link"].startswith("http://localhost:3001/activation#code=")
    dialog = InvitationDialog(shown[0])
    assert dialog.link.isReadOnly() and dialog.link.text() == shown[0]["link"]
    dialog.close()


def test_server_refusal_is_explained(controller, backend):  # noqa: F811
    _, page = open_tab(controller, "pre_enrollments")
    select(page, "PRE-2026-0003")
    page.ask = lambda kind, req: {"status": "REJECTED", "note": "x", "message_to_family": None}
    page.status_button.setEnabled(True)  # even if forced, the server refuses (a decision is final)
    page.change_status()
    assert page.banner.isVisible()
    assert backend.requests[page.selected().id]["status"] == "ACCEPTED"


# --- editorial contents ------------------------------------------------------------------------


def test_create_publish_and_archive_a_page(controller, backend):  # noqa: F811
    _, page = open_tab(controller, "pages")
    captured = []
    page.confirm = confirm_always(captured)
    page.ask = lambda content=None, references=None, file_name=None: {
        "kind": "ADMISSIONS",
        "title": "Comment nous rejoindre",
        "summary": "",
        "body": "## Étapes\n- une",
        "audiences": ["PUBLIC", "PARENT"],
        "status": "DRAFT",
        "order": 2,
        "to_validate": True,
        "is_demo": False,
    }
    page.add()
    assert "Comment nous rejoindre  (provisoire)" in column(page.table, 0)
    select(page, "Comment nous rejoindre  (provisoire)")
    assert page.publish_button.isEnabled() and not page.archive_button.isEnabled()
    page.set_status("PUBLISHED")
    row = next(r for r in backend.contents["pages"].values() if r["title"] == "Comment nous rejoindre")
    assert row["status"] == "PUBLISHED" and row["audiences"] == ["PUBLIC", "PARENT"]
    page.set_status("ARCHIVED")
    assert captured and row["status"] == "ARCHIVED"
    assert ("DELETE", f"admin/website/pages/{row['id']}/") not in backend.calls  # never deleted


def test_content_dialog_collects_values_and_requires_fields(qapp):
    dialog = ContentDialog("faq")
    assert set(dialog.missing_fields()) == {"Question", "Réponse"}
    dialog.widgets["question"][1].setText("Où est l'école ?")
    dialog.widgets["answer"][1].setPlainText("À Etoug-Ebe.")
    values = dialog.values()
    assert values["audiences"] == ["PUBLIC"] and values["to_validate"] is True and values["status"] == "DRAFT"
    assert dialog.missing_fields() == []
    dialog.close()
    resource = ContentDialog("resources", references={"levels": [], "classes": [], "years": []})
    assert "PUBLIC" not in resource.widgets["audiences"][1].boxes  # role resources are never public
    resource.close()


def test_image_upload_sends_bytes_and_metadata_only(controller, backend, tmp_path):  # noqa: F811
    _, page = open_tab(controller, "images")
    picture = tmp_path / "secret-folder" / "classe.jpg"
    picture.parent.mkdir()
    picture.write_bytes(b"\xff\xd8\xff\xe0 fake jpeg")
    page.choose_file = lambda *_: str(picture)
    page.ask = lambda content=None, references=None, file_name=None: {
        "alt_text": "Élèves en classe",
        "caption": "",
        "credit": "Image fournie",
        "category": "CLASSROOMS",
        "in_gallery": True,
        "is_illustration": True,
        "audiences": ["PUBLIC"],
        "status": "DRAFT",
        "order": 0,
        "to_validate": False,
        "is_demo": False,
    }
    page.add()
    upload = backend.website_uploads[-1]
    assert b'filename="classe.jpg"' in upload and b"secret-folder" not in upload  # never a local path
    assert b"is_illustration" in upload and b"true" in upload
    assert any("Élèves en classe" in t for t in column(page.table, 0))


def test_resource_document_must_be_a_pdf(controller, backend, tmp_path):  # noqa: F811
    _, page = open_tab(controller, "resources")
    select(page, "Fournitures 6e")
    fake = tmp_path / "liste.pdf"
    fake.write_bytes(b"MZ not a pdf")
    page.choose_file = lambda *_: str(fake)
    page.attach_document()
    assert page.banner.isVisible()
    good = tmp_path / "liste2.pdf"
    good.write_bytes(b"%PDF-1.7 ok")
    page.choose_file = lambda *_: str(good)
    select(page, "Fournitures 6e")
    page.attach_document()
    row = next(iter(backend.contents["resources"].values()))
    assert row["document_name"] == "liste2.pdf"


# --- applications ----------------------------------------------------------------------------


def test_release_upload_refuses_debug_and_publishes_signed(controller, backend, tmp_path):  # noqa: F811
    _, page = open_tab(controller, "releases")
    assert column(page.table, 0) == ["Application Parent"]
    debug = tmp_path / "app-debug.apk"
    debug.write_bytes(b"PK\x03\x04 ... CN=Android Debug ...")
    page.choose_file = lambda *_: str(debug)
    page.ask = lambda name: {
        "app": "TEACHER",
        "version_name": "1.0.0",
        "version_code": "1",
        "min_android": "8.0",
        "release_notes": "",
    }
    page.add()
    assert page.banner.isVisible() and len(backend.releases) == 1  # refused by the server
    signed = tmp_path / "app-release.apk"
    signed.write_bytes(b"PK\x03\x04 signed release")
    page.choose_file = lambda *_: str(signed)
    page.add()
    assert len(backend.releases) == 2
    select(page, "Application Enseignant")
    assert page.publish_button.isEnabled()
    page.set_status("PUBLISHED")
    teacher = next(r for r in backend.releases.values() if r["app"] == "TEACHER")
    assert teacher["status"] == "PUBLISHED"
    page.confirm = confirm_always([])
    select(page, "Application Enseignant")
    page.set_status("WITHDRAWN")
    assert teacher["status"] == "WITHDRAWN"


# --- profile and readiness ------------------------------------------------------------------------


def test_profile_and_readiness(controller, backend):  # noqa: F811
    _, page = open_tab(controller, "profile")
    assert page.fields["location_details"].text() == "Etoug-Ebe, Yaoundé"
    assert "point(s) bloquant(s)" in page.readiness_state.text()
    items = [page.readiness.item(i).text() for i in range(page.readiness.count())]
    assert any("Adresse exacte" in t for t in items)
    page.address_confirmed.setChecked(True)
    page.fields["office_hours"].setText("Lundi-vendredi, 7 h 30 - 16 h")
    page.save()
    assert backend.site_profile["address_confirmed"] is True
    assert backend.site_profile["office_hours"] == "Lundi-vendredi, 7 h 30 - 16 h"
    assert page.readiness_state.text().startswith("Prêt pour une ouverture")

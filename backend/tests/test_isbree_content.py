"""ISBREE public site and content administration (ADR 0032): only published
public rows reach anonymous visitors, files are checked by content (EXIF
removed, debug APK refused), editors only, other schools never reachable."""

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.audit.models import AuditLog
from apps.website import files
from apps.website import services as web
from apps.website.models import ContentImage, MobileAppRelease, Page
from apps.website.readiness import readiness_report

from .conftest import DB
from .factories import SchoolFactory
from .isbree_world import apk, client, data, jpeg, make_isbree_world, pdf

pytestmark = DB


@pytest.fixture
def w(school):
    return make_isbree_world(school)


def public(w, path):
    return f"/api/v1/public/{w.school.code}/{path}"


# --- public reading ----------------------------------------------------------------------


def test_public_site_exposes_identity_levels_and_never_an_unconfirmed_address(w):
    site = data(client().get(public(w, "site/")))
    assert site["school"]["phone"] == "+237698686729" and site["school"]["email"] == "contact@ecole.test"
    assert site["profile"]["address"] == "" and site["profile"]["address_confirmed"] is False
    assert [lv["name"] for lv in site["levels"]] == [w.level.name]
    assert [y["name"] for y in site["years"]] == [w.year.name]
    assert "legal_name" not in site["school"] and "id" not in site["school"]


def test_only_published_public_contents_are_listed(w):
    pages = data(client().get(public(w, "pages/")))
    assert [p["slug"] for p in pages] == [w.public_page.slug]  # no draft, no teacher page
    assert client().get(public(w, f"pages/{w.teacher_page.slug}/")).status_code == 404
    assert client().get(public(w, f"pages/{w.draft_page.slug}/")).status_code == 404
    assert [f["question"] for f in data(client().get(public(w, "faq/")))] == ["Comment ?"]
    news = data(client().get(public(w, "news/")))
    assert [n["slug"] for n in news] == [w.public_news.slug]  # the staff note stays private
    detail = data(client().get(public(w, f"news/{w.public_news.slug}/")))
    assert detail["body"] == "Détails" and detail["published_at"]


def test_unknown_or_other_school_is_a_404_and_contents_never_cross_schools(w):
    other = make_isbree_world(SchoolFactory())
    assert client().get("/api/v1/public/NOPE/site/").status_code == 404
    mine = {p["slug"] for p in data(client().get(public(w, "pages/")))}
    theirs = {p["slug"] for p in data(client().get(public(other, "pages/")))}
    assert mine == theirs  # same slugs, but each list comes from its own school only
    assert client().get(public(w, f"news/{other.staff_news.slug}/")).status_code == 404


def test_public_images_are_reencoded_without_exif_and_only_when_published(w):
    image = web.add_image(
        w.school, actor=w.editor, upload=jpeg(), values={"alt_text": "Une classe", "status": "PUBLISHED"}
    )
    body = b"".join(client().get(public(w, f"images/{image.pk}/")).streaming_content)
    assert (
        body.startswith(b"\xff\xd8")
        and b"Photographer" not in body
        and b"Secret place" not in body
        and b"Exif" not in body
    )
    draft = web.add_image(w.school, actor=w.editor, upload=jpeg(), values={"alt_text": "Brouillon"})
    assert client().get(public(w, f"images/{draft.pk}/")).status_code == 404
    gallery = data(client().get(public(w, "gallery/")))
    assert [g["id"] for g in gallery] == [str(image.pk)] and gallery[0]["is_illustration"] is True


# --- editing --------------------------------------------------------------------------------


def test_editors_create_publish_and_archive_with_audit(w):
    editor = client(w.editor)
    created = data(
        editor.post(
            "/api/v1/admin/website/faq/",
            {"category": "CONTACT", "question": "Téléphone ?", "answer": "Appelez.", "audiences": ["PUBLIC"]},
            format="json",
        ),
        201,
    )
    assert created["status"] == "DRAFT"  # nothing is published by default
    assert "Téléphone ?" not in str(data(client().get(public(w, "faq/"))))
    data(editor.patch(f"/api/v1/admin/website/faq/{created['id']}/", {"status": "PUBLISHED"}, format="json"))
    assert "Téléphone ?" in str(data(client().get(public(w, "faq/"))))
    data(editor.patch(f"/api/v1/admin/website/faq/{created['id']}/", {"status": "ARCHIVED"}, format="json"))
    assert "Téléphone ?" not in str(data(client().get(public(w, "faq/"))))
    assert AuditLog.objects.filter(action__startswith="WEBSITE_FAQENTRY", entity_id=created["id"]).count() == 3
    assert editor.delete(f"/api/v1/admin/website/faq/{created['id']}/").status_code == 405  # archived, never deleted


def test_editing_permissions_and_isolation(w, api):
    body = {"kind": "ABOUT", "title": "X", "audiences": ["PUBLIC"]}
    assert api.post("/api/v1/admin/website/pages/", body, format="json").status_code == 401
    for member in (w.tm_member, w.parent, w.guardian, w.staff_member):
        assert client(member).post("/api/v1/admin/website/pages/", body, format="json").status_code == 403
    other = make_isbree_world(SchoolFactory())
    url = f"/api/v1/admin/website/pages/{other.public_page.pk}/"
    assert client(w.editor).patch(url, {"title": "Pirate"}, format="json").status_code == 404
    bad = client(w.editor).post(
        "/api/v1/admin/website/resources/",
        {"kind": "SUPPLIES", "title": "X", "audiences": ["PARENT"], "school_class": str(other.klass.pk)},
        format="json",
    )
    assert bad.status_code == 403  # a class of another school is never accepted
    assert (
        client(w.editor)
        .post(
            "/api/v1/admin/website/resources/",
            {"kind": "SUPPLIES", "title": "X", "audiences": ["PUBLIC"]},
            format="json",
        )
        .status_code
        == 400
    )  # resources are for portal roles only


def test_slugs_are_generated_unique_and_drafts_are_listed_for_editors(w):
    a = data(
        client(w.editor).post(
            "/api/v1/admin/website/pages/",
            {"kind": "OTHER", "title": "Vie scolaire", "audiences": ["PUBLIC"]},
            format="json",
        ),
        201,
    )
    b = data(
        client(w.editor).post(
            "/api/v1/admin/website/pages/",
            {"kind": "OTHER", "title": "Vie scolaire", "audiences": ["PUBLIC"]},
            format="json",
        ),
        201,
    )
    assert (a["slug"], b["slug"]) == ("vie-scolaire", "vie-scolaire-2")
    drafts = data(client(w.editor).get("/api/v1/admin/website/pages/?status=DRAFT"))
    assert {p["slug"] for p in drafts} >= {"vie-scolaire", w.draft_page.slug}


# --- files ----------------------------------------------------------------------------------


def test_image_and_document_checks(w):
    with pytest.raises(ValidationError, match="Only PNG"):
        files.check_image(SimpleUploadedFile("x.svg", b"<svg onload=alert(1)>", content_type="image/svg+xml"))
    with pytest.raises(ValidationError, match="active content"):
        files.check_document(
            SimpleUploadedFile("x.pdf", b"%PDF-1.4 /JavaScript (alert)", content_type="application/pdf")
        )
    resource = w.class_supplies
    web.attach_document(resource, actor=w.editor, upload=pdf())
    resource.refresh_from_db()
    assert resource.document_name == "liste.pdf" and resource.document_size > 0


def test_only_signed_release_apks_are_accepted(w):
    upload = lambda f, code=1: client(w.editor).post(  # noqa: E731
        "/api/v1/admin/website/releases/",
        {"app": "PARENT", "version_name": "1.0.0", "version_code": code, "file": f},
        format="multipart",
    )
    unsigned = upload(apk(signed=False))
    assert unsigned.status_code == 400 and unsigned.json()["error"]["details"]["rule"] == "apk_unsigned"
    debug_v1 = upload(apk(certificate=b"CN=Android Debug, O=Android, C=US"))
    assert debug_v1.json()["error"]["details"]["rule"] == "apk_debug_build"
    debug_v2 = upload(apk(certificate=None, block=b"...CN=Android Debug..."))
    assert debug_v2.json()["error"]["details"]["rule"] == "apk_debug_build"
    assert upload(SimpleUploadedFile("x.apk", b"not a zip")).json()["error"]["details"]["rule"] == "apk_invalid"
    release = data(upload(apk(block=b"CN=ISBREE Release")), 201)
    assert release["status"] == "DRAFT" and len(release["sha256"]) == 64
    assert upload(apk(), code=1).json()["error"]["details"]["rule"] == "release_version_exists"
    assert MobileAppRelease.objects.count() == 1
    assert client(w.parent).post("/api/v1/admin/website/releases/", {}, format="multipart").status_code == 403


# --- readiness ------------------------------------------------------------------------------


def test_readiness_lists_what_blocks_a_production_opening(w):
    codes = {i["code"] for i in readiness_report(w.school)["items"]}
    assert {"profile_missing", "page_legal_notice", "page_privacy", "page_terms", "app_parent"} <= codes
    assert "contact_email" not in codes and "contact_phone" not in codes
    w.content("pages", kind="ABOUT", title="Démo", audiences=["PUBLIC"], is_demo=True)
    assert "page_demo" in {i["code"] for i in readiness_report(w.school)["items"]}
    report = data(client(w.editor).get("/api/v1/admin/website/readiness/"))
    assert report["ready"] is False
    assert Page.objects.filter(school=w.school).count() >= 4 and ContentImage.objects.count() == 0

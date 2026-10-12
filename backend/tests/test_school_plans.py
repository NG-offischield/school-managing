"""School plans: import (real PDF / PNG / JPEG, everything else refused),
versions, publication, withdrawal, AUTO / MANUAL distribution checked at
each read, private download, PLAN notifications — and PostgreSQL integrity."""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from PIL import Image
from pypdf import PdfWriter
from reportlab.pdfgen import canvas
from rest_framework.test import APIClient

from apps.communication.models import Notification
from apps.documents import plans
from apps.documents.models import PlanStatus, PlanVersionStatus, SchoolPlan, SchoolPlanVersion
from apps.people import services as people
from apps.people.models import ProfessionalStatus, TeacherProfile

from .communication_world import make_communication_world, verified_parent
from .conftest import DB
from .factories import SchoolClassFactory, SchoolFactory, StudentFactory

pytestmark = DB


# --- files --------------------------------------------------------------------------------


def pdf_bytes(pages=1, text="Plan du bâtiment A"):
    out = io.BytesIO()
    pdf = canvas.Canvas(out)
    for _ in range(pages):
        pdf.drawString(72, 720, text)
        pdf.rect(72, 300, 400, 300)
        pdf.showPage()
    pdf.save()
    return out.getvalue()


def image_bytes(fmt="PNG", size=(1600, 1200), exif=False):
    image = Image.new("RGB", size, (240, 240, 240))
    out = io.BytesIO()
    if fmt == "JPEG" and exif:
        data = Image.Exif()
        data[0x010F] = "Phone maker"  # Make
        data[0x8825] = {2: (4.0, 3.0, 0.0)}  # GPSInfo (latitude)
        image.save(out, format="JPEG", exif=data.tobytes())
    elif fmt == "PNG" and exif:
        from PIL import PngImagePlugin

        info = PngImagePlugin.PngInfo()
        info.add_text("Author", "Architecte X")
        image.save(out, format="PNG", pnginfo=info)
    else:
        image.save(out, format=fmt)
    return out.getvalue()


def upload(name, data, content_type="application/octet-stream"):
    return SimpleUploadedFile(name, data, content_type=content_type)


# --- world --------------------------------------------------------------------------------


@pytest.fixture
def w(school):
    w = make_communication_world(school)
    # A second class (4e C) with its own pupil and verified parent, taught by tf only.
    w.klass_c = SchoolClassFactory(school=school, name="4e C", academic_year=w.year, level=w.klass.level)
    w.pupil_c = StudentFactory(school=school, last_name="ÉlèveC")
    people.enroll_student(w.pupil_c, w.klass_c)
    w.parent_c = verified_parent(w, w.pupil_c)
    from apps.gradebook import services as gb

    gb.create_course(w.klass_c, w.french, w.tf, actor=w.admin)
    return w


def as_(member):
    client = APIClient()
    client.force_authenticate(member.user)
    return client


def published_plan(w, *, data=None, name="plan.pdf", distribution="AUTO", title="Bâtiment A"):
    plan = plans.create_plan(w.school, actor=w.admin, title=title, building="A", floor="RDC", distribution=distribution)
    version = plans.add_version(plan, actor=w.admin, upload=upload(name, data or pdf_bytes()))
    return plans.publish(plan, actor=w.admin, version=version), version


def plan_notes(**filters):
    return Notification.objects.filter(notification_type="PLAN", **filters)


# --- A. import ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "maker", "mime"),
    [
        ("plan.pdf", lambda: pdf_bytes(pages=2), "application/pdf"),
        ("plan.png", lambda: image_bytes("PNG"), "image/png"),
        ("plan.jpg", lambda: image_bytes("JPEG"), "image/jpeg"),
        ("PLAN.JPEG", lambda: image_bytes("JPEG"), "image/jpeg"),
    ],
)
def test_real_pdf_png_jpeg_are_accepted(w, name, maker, mime):
    plan = plans.create_plan(w.school, actor=w.admin, title="Site")
    version = plans.add_version(plan, actor=w.admin, upload=upload(name, maker()))
    assert (version.mime_type, version.status, version.number) == (mime, PlanVersionStatus.DRAFT, 1)
    assert version.storage_path.startswith(f"plans/{w.school.pk.hex}/") and name not in version.storage_path
    assert len(version.sha256) == 64 and version.size_bytes > 0
    if mime == "application/pdf":
        assert version.page_count == 2
    else:
        assert (version.width, version.height) == (1600, 1200)  # full resolution kept (no 800 px)


def test_image_metadata_is_dropped(w):
    plan = plans.create_plan(w.school, actor=w.admin, title="Site")
    jpeg = plans.add_version(plan, actor=w.admin, upload=upload("p.jpg", image_bytes("JPEG", exif=True)))
    png = plans.add_version(plan, actor=w.admin, upload=upload("p.png", image_bytes("PNG", exif=True)))
    with plans.plan_files.open_file(jpeg) as handle, Image.open(handle) as stored:
        assert not stored.getexif()  # no maker, no GPS
    with plans.plan_files.open_file(png) as handle, Image.open(handle) as stored:
        assert "Author" not in stored.info


def _encrypted_pdf():
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt("secret")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@pytest.mark.parametrize(
    ("name", "data", "code"),
    [
        ("plan.pdf", b"%PDF-1.7\nthis is not really a pdf", "plan_file_corrupted"),
        ("plan.png", b"\x89PNG\r\n\x1a\nbroken", "plan_file_corrupted"),
        ("plan.pdf", image_bytes("PNG"), "plan_extension_mismatch"),  # PNG named .pdf
        ("plan.pdf", b"MZ\x90\x00 an executable renamed", "plan_format_not_supported"),
        (
            "plan.svg",
            b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            "plan_format_not_supported",
        ),
        ("plan.dwg", b"AC1032\x00\x00\x00 autocad", "plan_format_not_supported"),
        ("plan.dxf", b"0\nSECTION\n2\nHEADER\n", "plan_format_not_supported"),
        ("plan.pdf", b"", "plan_file_empty"),
        ("plan.pdf", None, "plan_pdf_encrypted"),
        (
            "plan.pdf",
            b"%PDF-1.4\n1 0 obj << /OpenAction << /S /JavaScript /JS (app.alert(1)) >> >>",
            "plan_pdf_active_content",
        ),
    ],
)
def test_bad_files_are_refused_with_a_reason(w, name, data, code):
    plan = plans.create_plan(w.school, actor=w.admin, title="Site")
    response = as_(w.admin).post(
        f"/api/v1/admin/plans/{plan.pk}/versions/",
        {"file": upload(name, _encrypted_pdf() if data is None else data)},
        format="multipart",
    )
    assert response.status_code == 400, response.json()
    assert response.json()["error"]["details"]["rule"] == code
    assert not SchoolPlanVersion.objects.exists()


def test_size_and_dimension_limits(w, settings):
    plan = plans.create_plan(w.school, actor=w.admin, title="Site")
    settings.SCHOOL_PLAN_MAX_BYTES = 2000
    big = as_(w.admin).post(
        f"/api/v1/admin/plans/{plan.pk}/versions/", {"file": upload("p.pdf", pdf_bytes(pages=5))}, format="multipart"
    )
    assert big.json()["error"]["details"]["rule"] == "plan_file_too_large"
    settings.SCHOOL_PLAN_MAX_BYTES = 20 * 1024 * 1024
    settings.SCHOOL_PLAN_MAX_IMAGE_SIDE = 1000
    wide = as_(w.admin).post(
        f"/api/v1/admin/plans/{plan.pk}/versions/", {"file": upload("p.png", image_bytes())}, format="multipart"
    )
    assert wide.json()["error"]["details"]["rule"] == "plan_image_too_large"


# --- B. lifecycle -------------------------------------------------------------------------


def test_draft_publish_new_version_withdraw(w):
    admin = as_(w.admin)
    created = admin.post(
        "/api/v1/admin/plans/", {"title": "Bâtiment B", "building": "B", "floor": "1er étage"}, format="json"
    )
    assert created.status_code == 201 and created.json()["data"]["status"] == "DRAFT"
    plan_id = created.json()["data"]["id"]
    v1 = admin.post(
        f"/api/v1/admin/plans/{plan_id}/versions/", {"file": upload("b.pdf", pdf_bytes())}, format="multipart"
    )
    v1_id = v1.json()["data"]["id"]
    assert as_(w.parent).get("/api/v1/plans/").json()["data"] == []  # a draft is nobody's business
    published = admin.post(f"/api/v1/admin/plans/{plan_id}/publish/", {"version": v1_id}, format="json")
    assert published.json()["data"]["status"] == "PUBLISHED"
    assert published.json()["data"]["current_version"]["number"] == 1
    v2 = admin.post(
        f"/api/v1/admin/plans/{plan_id}/versions/", {"file": upload("b.png", image_bytes())}, format="multipart"
    )
    v2_id = v2.json()["data"]["id"]
    seen = as_(w.parent).get(f"/api/v1/plans/{plan_id}/").json()["data"]
    assert seen["version"]["number"] == 1  # an imported version changes nothing until published
    admin.post(f"/api/v1/admin/plans/{plan_id}/publish/", {"version": v2_id}, format="json")
    assert as_(w.parent).get(f"/api/v1/plans/{plan_id}/").json()["data"]["version"]["mime_type"] == "image/png"
    history = {v["number"]: v["status"] for v in admin.get(f"/api/v1/admin/plans/{plan_id}/versions/").json()["data"]}
    assert history == {1: "SUPERSEDED", 2: "PUBLISHED"}  # the old one is kept
    old = admin.get(f"/api/v1/admin/plans/{plan_id}/versions/{v1_id}/file/")
    assert old.status_code == 200 and old["Content-Type"] == "application/pdf"  # administration only
    withdrawn = admin.post(f"/api/v1/admin/plans/{plan_id}/withdraw/", {"reason": "Travaux"}, format="json")
    assert withdrawn.json()["data"]["status"] == "WITHDRAWN"
    assert as_(w.parent).get("/api/v1/plans/").json()["data"] == []
    assert as_(w.parent).get(f"/api/v1/plans/{plan_id}/file/").status_code == 404
    assert SchoolPlanVersion.objects.filter(plan_id=plan_id).count() == 2  # history kept


def test_metadata_change_does_not_notify(w):
    plan, _ = published_plan(w)
    before = plan_notes().count()
    as_(w.admin).patch(f"/api/v1/admin/plans/{plan.pk}/", {"title": "Bâtiment A (rénové)"}, format="json")
    assert plan_notes().count() == before


# --- C / D. permissions and AUTO ----------------------------------------------------------------


def test_auto_reaches_verified_parents_and_active_teachers_of_the_school(w):
    plan, version = published_plan(w)
    allowed = (w.parent, w.other_parent, w.parent_c, w.tm_member, w.tf_member, w.outsider_teacher, w.admin)
    for member in allowed:
        rows = as_(member).get("/api/v1/plans/").json()["data"]
        assert [r["id"] for r in rows] == [str(plan.pk)], member
        file = as_(member).get(f"/api/v1/plans/{plan.pk}/file/")
        assert file.status_code == 200 and file["Cache-Control"] == "private, no-store"
        assert "storage" not in file["Content-Disposition"] and version.stored_name not in file["Content-Disposition"]
    for member in (w.unverified, w.guardian, w.staff_member):
        assert as_(member).get("/api/v1/plans/").json()["data"] == [], member
        assert as_(member).get(f"/api/v1/plans/{plan.pk}/file/").status_code == 404, member


def test_inactive_teacher_and_other_school_are_refused(w):
    plan, _ = published_plan(w)
    TeacherProfile.objects.filter(employee__membership=w.outsider_teacher).update(
        professional_status=ProfessionalStatus.SUSPENDED
    )
    assert as_(w.outsider_teacher).get(f"/api/v1/plans/{plan.pk}/").status_code == 404
    other = make_communication_world(SchoolFactory())
    for member in (other.parent, other.tm_member, other.admin):
        assert as_(member).get(f"/api/v1/plans/{plan.pk}/").status_code == 404
        assert as_(member).get(f"/api/v1/plans/{plan.pk}/file/").status_code == 404
        assert as_(member).get("/api/v1/plans/").json()["data"] == []


def test_administration_only_for_management(w):
    plan, version = published_plan(w)
    for member in (w.parent, w.tm_member, w.staff_member, w.guardian):
        client = as_(member)
        assert client.get("/api/v1/admin/plans/").status_code == 403
        assert client.post("/api/v1/admin/plans/", {"title": "X"}, format="json").status_code == 403
        assert client.put(f"/api/v1/admin/plans/{plan.pk}/audience/", {"entries": []}, format="json").status_code == 403
        assert client.get(f"/api/v1/admin/plans/{plan.pk}/versions/{version.pk}/file/").status_code == 403
    other = make_communication_world(SchoolFactory())
    assert as_(other.admin).get(f"/api/v1/admin/plans/{plan.pk}/").status_code == 404


def test_unpublished_version_is_never_served_to_readers(w):
    plan, _ = published_plan(w)
    draft = plans.add_version(plan, actor=w.admin, upload=upload("next.png", image_bytes()))
    served = as_(w.parent).get(f"/api/v1/plans/{plan.pk}/file/")
    assert served["Content-Type"] == "application/pdf"  # still the published v1, not the draft PNG
    assert as_(w.parent).get(f"/api/v1/admin/plans/{plan.pk}/versions/{draft.pk}/file/").status_code == 403


# --- E. MANUAL --------------------------------------------------------------------------------


def test_manual_class_audience(w):
    plan = plans.create_plan(w.school, actor=w.admin, title="Aile 3e", distribution="MANUAL")
    version = plans.add_version(plan, actor=w.admin, upload=upload("p.pdf", pdf_bytes()))
    refused = as_(w.admin).post(f"/api/v1/admin/plans/{plan.pk}/publish/", {"version": str(version.pk)}, format="json")
    assert refused.status_code == 409 and refused.json()["error"]["details"]["rule"] == "plan_audience_empty"
    put = as_(w.admin).put(
        f"/api/v1/admin/plans/{plan.pk}/audience/",
        {
            "entries": [
                {"target": "CLASS_PARENTS", "school_class": str(w.klass.pk)},
                {"target": "CLASS_TEACHERS", "school_class": str(w.klass.pk)},
            ]
        },
        format="json",
    )
    assert put.status_code == 200 and len(put.json()["data"]) == 2
    plans.publish(plan, actor=w.admin, version=version)
    for member in (w.parent, w.other_parent, w.tm_member, w.tf_member):  # 3e A families / teachers
        assert as_(member).get(f"/api/v1/plans/{plan.pk}/file/").status_code == 200, member
    for member in (w.parent_c, w.outsider_teacher, w.unverified, w.guardian, w.staff_member):
        assert as_(member).get(f"/api/v1/plans/{plan.pk}/file/").status_code == 404, member
    access = as_(w.admin).get(f"/api/v1/admin/plans/{plan.pk}/access/").json()["data"]
    assert {r["id"] for r in access["readers"]} == {
        str(m.pk) for m in (w.parent, w.other_parent, w.tm_member, w.tf_member)
    }
    # Audience changed: access follows at the very next request.
    as_(w.admin).put(
        f"/api/v1/admin/plans/{plan.pk}/audience/",
        {"entries": [{"target": "CLASS_PARENTS", "school_class": str(w.klass_c.pk)}]},
        format="json",
    )
    assert as_(w.parent).get(f"/api/v1/plans/{plan.pk}/file/").status_code == 404
    assert as_(w.tm_member).get(f"/api/v1/plans/{plan.pk}/").status_code == 404
    assert as_(w.parent_c).get(f"/api/v1/plans/{plan.pk}/file/").status_code == 200
    emptied = as_(w.admin).put(f"/api/v1/admin/plans/{plan.pk}/audience/", {"entries": []}, format="json")
    assert emptied.status_code == 409  # a published MANUAL plan without readers: withdraw it instead


def test_manual_school_roles_and_other_school_classes(w):
    plan = plans.create_plan(w.school, actor=w.admin, title="Accueil", distribution="MANUAL")
    plans.set_audience(plan, actor=w.admin, entries=[("SCHOOL_TEACHERS", None)])
    version = plans.add_version(plan, actor=w.admin, upload=upload("p.png", image_bytes()))
    plans.publish(plan, actor=w.admin, version=version)
    assert as_(w.outsider_teacher).get(f"/api/v1/plans/{plan.pk}/").status_code == 200
    assert as_(w.parent).get(f"/api/v1/plans/{plan.pk}/").status_code == 404
    other = make_communication_world(SchoolFactory())
    foreign = as_(w.admin).put(
        f"/api/v1/admin/plans/{plan.pk}/audience/",
        {"entries": [{"target": "CLASS_PARENTS", "school_class": str(other.klass.pk)}]},
        format="json",
    )
    assert foreign.status_code == 404  # another school's class does not exist here


def test_losing_the_right_closes_the_access(w):
    plan, _ = published_plan(w)
    assert as_(w.parent).get(f"/api/v1/plans/{plan.pk}/file/").status_code == 200
    w.parent.parent_profile.children_links.update(active=False)  # no verified child any more
    assert as_(w.parent).get(f"/api/v1/plans/{plan.pk}/file/").status_code == 404


# --- F. notifications ---------------------------------------------------------------------------


def test_publication_notifies_the_readers_once_per_version(w):
    plan = plans.create_plan(w.school, actor=w.admin, title="Bâtiment A", building="A")
    v1 = plans.add_version(plan, actor=w.admin, upload=upload("p.pdf", pdf_bytes()))
    assert not plan_notes().exists()  # draft: nobody
    plans.publish(plan, actor=w.admin, version=v1)
    recipients = set(plan_notes(event_key=f"plan.version:{v1.pk}").values_list("recipient", flat=True))
    substitute = w.maths_substitute.employee.membership  # an active teacher of the school too
    readers = {w.parent.pk, w.other_parent.pk, w.parent_c.pk, w.tm_member.pk, w.tf_member.pk, w.outsider_teacher.pk}
    readers.add(substitute.pk)
    assert recipients == readers  # not the admin, guardian, staff, unverified parent
    note = plan_notes(recipient=w.parent).get()
    assert note.title == "Plan publié : Bâtiment A" and note.payload["plan"] == str(plan.pk)
    plans.publish(plan, actor=w.admin, version=v1)  # same version again: nothing
    plans.withdraw(plan, actor=w.admin)
    plans.publish(plan, actor=w.admin, version=v1)  # back after a withdrawal: no second notice
    assert plan_notes().count() == len(readers)
    v2 = plans.add_version(plan, actor=w.admin, upload=upload("p.png", image_bytes()))
    plans.publish(plan, actor=w.admin, version=v2)
    assert (
        plan_notes(recipient=w.parent, event_key=f"plan.version:{v2.pk}").get().title == "Plan mis à jour : Bâtiment A"
    )
    other = make_communication_world(SchoolFactory())
    assert not plan_notes(school=other.school).exists()


def test_withdrawal_notifies_nobody(w):
    plan, _ = published_plan(w)
    before = plan_notes().count()
    plans.withdraw(plan, actor=w.admin)
    assert plan_notes().count() == before


# --- PostgreSQL integrity (bypassing the services on purpose) -------------------------------------


def test_database_keeps_plans_consistent(w):
    plan, version = published_plan(w)
    other_plan = plans.create_plan(w.school, actor=w.admin, title="Autre")
    foreign = plans.add_version(other_plan, actor=w.admin, upload=upload("o.pdf", pdf_bytes()))
    with pytest.raises(IntegrityError), transaction.atomic():
        SchoolPlan.objects.filter(pk=plan.pk).update(current_version=foreign)  # another plan's version
    with pytest.raises(IntegrityError), transaction.atomic():
        SchoolPlan.objects.filter(pk=other_plan.pk).update(status=PlanStatus.PUBLISHED)  # published, no version
    second = plans.add_version(plan, actor=w.admin, upload=upload("n.pdf", pdf_bytes()))
    with pytest.raises(IntegrityError), transaction.atomic():
        SchoolPlanVersion.objects.filter(pk=second.pk).update(status=PlanVersionStatus.PUBLISHED)  # two published
    with pytest.raises(IntegrityError), transaction.atomic():
        SchoolPlanVersion.objects.filter(pk=second.pk).update(mime_type="image/svg+xml")


def test_publication_is_pushed_live_to_readers_only(w):
    from asgiref.sync import async_to_sync
    from channels.db import database_sync_to_async

    from .test_realtime import authenticated

    plan = plans.create_plan(w.school, actor=w.admin, title="Bâtiment A")
    version = plans.add_version(plan, actor=w.admin, upload=upload("p.pdf", pdf_bytes()))

    async def scenario():
        reader, _ = await authenticated(w.parent)
        guardian, _ = await authenticated(w.guardian)
        await database_sync_to_async(plans.publish)(plan, actor=w.admin, version=version)
        frame = await reader.receive_json_from(timeout=5)
        assert frame["type"] == "notification" and frame["data"]["notification_type"] == "PLAN"
        assert frame["data"]["payload"]["plan"] == str(plan.pk)
        assert await guardian.receive_nothing(timeout=0.5)
        await reader.disconnect()
        await guardian.disconnect()

    async_to_sync(scenario)()

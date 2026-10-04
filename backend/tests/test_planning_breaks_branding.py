"""Desktop planning phase (ADR 0021): school breaks can be edited (the only
backend addition), and official documents keep the SCHOOL's branding — the
software's name / logo (School Managing) never replaces it."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.audit.models import AuditLog
from apps.documents import services as docs
from apps.scheduling import services as planning
from apps.scheduling.models import SchoolBreak

from .communication_world import make_communication_world, png
from .conftest import DB
from .factories import SchoolFactory, member_with_role
from .test_classes_api import as_, data, error
from .test_documents import card_of, pdf_bytes
from .test_gradebook import fill_t1

pytestmark = DB
DOUALA = ZoneInfo("Africa/Douala")
SOFTWARE_NAME = "School Managing"


@pytest.fixture
def w(school):
    return make_communication_world(school)


def a_break(w):
    start = datetime(2025, 12, 20, 0, 0, tzinfo=DOUALA)
    return planning.create_school_break(
        w.year, actor=w.admin, name="Vacances de Noël", start_datetime=start, end_datetime=start + timedelta(days=14)
    )


def test_school_break_can_be_edited(w):
    school_break = a_break(w)
    url = f"/api/v1/admin/school-breaks/{school_break.pk}/"
    body = data(
        as_(w.admin).patch(
            url,
            {"name": "Congés de fin d'année", "end_datetime": "2026-01-05T00:00:00+01:00", "break_type": "HOLIDAY"},
            format="json",
        )
    )
    assert (body["name"], body["end_datetime"][:10]) == ("Congés de fin d'année", "2026-01-05")
    assert AuditLog.objects.filter(action="SCHOOL_BREAK_UPDATED", entity_id=school_break.pk).exists()
    err = error(as_(w.admin).patch(url, {"end_datetime": "2025-12-01T00:00:00+01:00"}, format="json"), 400)
    assert err["details"]["rule"] == "invalid_dates"
    assert error(as_(w.admin).patch(url, {"break_type": "NOPE"}, format="json"), 400)["details"]["rule"] == (
        "break_type_invalid"
    )
    assert error(as_(w.admin).patch(url, {"name": "  "}, format="json"), 400)
    assert SchoolBreak.objects.get(pk=school_break.pk).name == "Congés de fin d'année"  # refusals change nothing


def test_school_break_permissions_and_isolation(w):
    school_break = a_break(w)
    url = f"/api/v1/admin/school-breaks/{school_break.pk}/"
    assert error(as_(w.tm_member).patch(url, {"name": "x"}, format="json"), 403)
    other_admin = member_with_role(SchoolFactory(code="OTHERB"), "ADMIN")
    assert as_(other_admin).patch(url, {"name": "x"}, format="json").status_code == 404
    start = "2025-10-01T00:00:00+01:00"
    err = error(
        as_(w.admin).post(
            "/api/v1/admin/school-breaks/",
            {"academic_year": str(w.year.pk), "name": "X", "start_datetime": start, "end_datetime": start},
            format="json",
        ),
        400,
    )
    assert err["details"]["rule"] == "invalid_dates"  # explained, not a database error


def test_documents_carry_the_school_branding_never_the_software_brand(w):
    w.school.logo = SimpleUploadedFile("logo.png", png().read(), content_type="image/png")
    w.school.save()
    fill_t1(w)
    document, _ = docs.generate("REPORT_CARD", card_of(w), actor=w.admin)
    raw = pdf_bytes(document)
    assert document.content["school"]["name"] == w.school.name and document.content["school"]["logo"]
    assert b"/Subtype /Image" in raw  # the school's logo is drawn
    # The PDF only prints `content` through apps/documents: neither mentions the software brand.
    assert SOFTWARE_NAME.lower() not in json.dumps(document.content, ensure_ascii=False).lower()
    sources = Path(docs.__file__).resolve().parent
    for source in sources.glob("*.py"):
        text = source.read_text(encoding="utf-8").lower()
        assert SOFTWARE_NAME.lower() not in text and "school_managing" not in text, source.name

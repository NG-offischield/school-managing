"""seed_isbree (ADR 0032): idempotent, everything editorial flagged to
validate, demonstration data flagged, real roles and a VERIFIED child for the
demo parent, illustrations flagged, refused in production."""

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from apps.accounts.models import SchoolMembership
from apps.people.models import ParentStudent
from apps.website.isbree_seed import seed
from apps.website.models import ContentImage, FaqEntry, NewsArticle, Page, RoleResource, SiteLocation

from .conftest import DB
from .isbree_world import jpeg

pytestmark = DB
PASSWORD = "Demo-Isbree-2026-Solide"


def test_contents_only_then_demo_then_idempotent(tmp_path):
    first = seed(password=PASSWORD, contact_email="contact@ecole.test")
    school = first.school
    assert (school.code, school.phone, school.email) == ("ISBREE", "+237698686729", "contact@ecole.test")
    assert Page.objects.filter(school=school).count() == 10 and FaqEntry.objects.filter(school=school).count() >= 10
    assert not Page.objects.filter(school=school, to_validate=False).exists()  # all provisional
    assert not SiteLocation.objects.filter(school=school).exists()  # no demo data without --demo
    assert school.levels.count() == 0 if hasattr(school, "levels") else True

    (tmp_path / "1.jpg").write_bytes(jpeg().read())
    demo = seed(password=PASSWORD, demo=True, images=str(tmp_path))
    roles = {
        m.user.email: m.role_codes() for m in SchoolMembership.objects.filter(school=school).select_related("user")
    }
    assert roles["parent.demo@isbree.test"] == {"PARENT"} and roles["gardien.demo@isbree.test"] == {"GUARDIAN"}
    assert "TEACHER" in roles["enseignant.demo@isbree.test"] and "STAFF" in roles["personnel.demo@isbree.test"]
    assert ParentStudent.objects.filter(
        parent__membership__user__email="parent.demo@isbree.test", identity_verified=True, active=True
    ).exists()
    # Only the school's real location (address still to confirm): no invented campus.
    assert list(SiteLocation.objects.filter(school=school).values_list("name", "is_demo", "to_validate")) == [
        ("Établissement ISBREE", False, True)
    ]
    assert not NewsArticle.objects.filter(school=school, is_demo=False).exists()
    assert not RoleResource.objects.filter(school=school, is_demo=False).exists()
    image = ContentImage.objects.get(school=school)
    assert image.is_illustration and "ne représente pas ISBREE" in image.credit
    assert demo.created

    again = seed(password=PASSWORD, demo=True, images=str(tmp_path))
    assert again.created == []  # nothing duplicated, nothing rewritten


def test_password_required_and_refused_in_production():
    with pytest.raises(ImproperlyConfigured):
        seed(password=None)
    with override_settings(SETTINGS_MODULE="config.settings.production"), pytest.raises(ImproperlyConfigured):
        seed(password=PASSWORD)

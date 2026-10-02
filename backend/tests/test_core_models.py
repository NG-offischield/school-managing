"""Tenant core: School + configuration + branding (spec §4.1)."""

import pytest
from django.db import IntegrityError, transaction

from apps.core.models import School, SchoolConfiguration
from apps.core.services import create_school

from .conftest import DB

pytestmark = DB


def test_create_school_also_creates_configuration_and_branding():
    school = create_school(code="LYC1", name="Lycée 1", city="Douala", address="Akwa")

    assert school.configuration.default_late_threshold_minutes == 15
    assert school.branding.primary_color == "#173B73"
    assert school.currency == "XAF"
    assert school.timezone == "Africa/Douala"


def test_school_code_is_unique():
    create_school(code="LYC1", name="A", city="Douala", address="x")
    with pytest.raises(IntegrityError), transaction.atomic():
        create_school(code="LYC1", name="B", city="Yaoundé", address="y")


@pytest.mark.parametrize(
    "field,value",
    [("status", "DELETED"), ("currency", "BTC")],
)
def test_school_check_constraints_are_enforced_by_postgresql(field, value):
    school = create_school(code="LYC1", name="A", city="Douala", address="x")
    # .update() bypasses Python validation entirely: only the DB CHECK can stop it.
    with pytest.raises(IntegrityError), transaction.atomic():
        School.objects.filter(pk=school.pk).update(**{field: value})


def test_alert_thresholds_must_escalate():
    school = create_school(code="LYC1", name="A", city="Douala", address="x")
    with pytest.raises(IntegrityError), transaction.atomic():
        SchoolConfiguration.objects.filter(school=school).update(notification_red_hours=5)


def test_create_school_is_atomic(monkeypatch):
    """If configuration creation fails, no orphan school must remain."""

    def boom(**kwargs):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(SchoolConfiguration.objects, "create", boom)
    with pytest.raises(RuntimeError):
        create_school(code="LYC1", name="A", city="Douala", address="x")
    assert not School.objects.filter(code="LYC1").exists()

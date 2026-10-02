"""Security events vs business transactions and referential integrity (ADR 0005)."""

import pytest
from django.db import connection, transaction

from apps.accounts import services
from apps.accounts.models import SecurityEvent, SecurityEventType
from apps.accounts.services import ClientContext, record_security_event
from common.db_routers import SECURITY_LOG_ALIAS

from .conftest import DB, DEVICE
from .factories import SchoolFactory, UserFactory

pytestmark = DB


class BusinessFailure(Exception):
    pass


# --- Independence from the business transaction ------------------------------------


def test_security_events_use_the_dedicated_connection():
    assert SecurityEvent.objects.all().db == SECURITY_LOG_ALIAS


def test_immediate_event_survives_business_rollback(user):
    with pytest.raises(BusinessFailure), transaction.atomic():
        record_security_event(SecurityEventType.LOGIN_FAILED, user=user)
        raise BusinessFailure()

    event = SecurityEvent.objects.get(event_type=SecurityEventType.LOGIN_FAILED)
    assert event.user_id == user.id  # committed user: the FK link is kept


def test_failed_login_is_kept_even_if_the_request_transaction_rolls_back(user):
    with pytest.raises(services.InvalidCredentials), transaction.atomic():
        services.login(user.username, "wrong-password", DEVICE, ClientContext(ip_address="10.0.0.7"))

    event = SecurityEvent.objects.get(event_type=SecurityEventType.LOGIN_FAILED)
    assert (event.user_id, event.ip_address) == (user.id, "10.0.0.7")
    assert event.metadata == {"identifier": user.username}


def test_success_event_is_not_written_when_business_transaction_rolls_back(user):
    with pytest.raises(BusinessFailure), transaction.atomic():
        record_security_event(SecurityEventType.PASSWORD_CHANGED, user=user, after_commit=True)
        raise BusinessFailure()

    assert not SecurityEvent.objects.exists()


def test_success_event_is_written_once_committed(user):
    with transaction.atomic():
        record_security_event(SecurityEventType.PASSWORD_CHANGED, user=user, after_commit=True)
        # Not yet: on_commit callbacks fire at the real commit (end of block).
        assert not SecurityEvent.objects.exists()

    assert SecurityEvent.objects.get().user_id == user.id


# --- Referential integrity ------------------------------------------------------


def _fk_delete_actions():
    """{column: on-delete action} of the FKs of accounts_securityevent, as
    PostgreSQL really stores them ('n' = SET NULL)."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT a.attname, c.confdeltype
            FROM pg_constraint c
            JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
            WHERE c.conrelid = 'accounts_securityevent'::regclass AND c.contype = 'f'
            """
        )
        return dict(cursor.fetchall())


def test_foreign_keys_exist_with_on_delete_set_null_in_postgresql():
    assert _fk_delete_actions() == {"user_id": "n", "school_id": "n"}


def test_reference_to_a_missing_user_is_rejected_by_postgresql():
    """Integrity is real: a security event cannot point to a user that never existed."""
    import uuid

    from django.db import IntegrityError

    with pytest.raises(IntegrityError), transaction.atomic(using=SECURITY_LOG_ALIAS):
        SecurityEvent.objects.create(event_type=SecurityEventType.LOGIN_FAILED, user_id=uuid.uuid4())


def test_event_survives_deletion_of_its_user_and_school():
    """Even a raw SQL delete (no Django ORM involved) keeps the event and nulls the link."""
    user, school = UserFactory(), SchoolFactory()
    record_security_event(SecurityEventType.LOGIN_FAILED, user=user, school=school)

    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM core_schoolbranding WHERE school_id = %s", [school.id])
        cursor.execute("DELETE FROM core_schoolconfiguration WHERE school_id = %s", [school.id])
        cursor.execute("DELETE FROM core_school WHERE id = %s", [school.id])
        cursor.execute("DELETE FROM accounts_user WHERE id = %s", [user.id])

    event = SecurityEvent.objects.get()
    assert (event.user_id, event.school_id) == (None, None)
    assert event.event_type == SecurityEventType.LOGIN_FAILED


def test_event_referencing_an_uncommitted_row_is_kept_with_unresolved_ref():
    """The user below exists only inside the (later rolled back) business
    transaction: the security_log connection cannot see it, so the FK check
    fails. The event must not be lost: it is kept, the id moves to metadata."""
    with pytest.raises(BusinessFailure), transaction.atomic():
        ghost = UserFactory()
        record_security_event(SecurityEventType.LOGIN_FAILED, user=ghost, attempt="x")
        raise BusinessFailure()

    event = SecurityEvent.objects.get()
    assert event.user_id is None
    assert event.metadata == {"attempt": "x", "unresolved_refs": {"user_id": str(ghost.id)}}

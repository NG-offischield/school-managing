"""Security events vs business transactions (ADR 0005)."""

import pytest
from django.db import transaction

from apps.accounts import services
from apps.accounts.models import SecurityEvent, SecurityEventType
from apps.accounts.services import ClientContext, record_security_event
from common.db_routers import SECURITY_LOG_ALIAS

from .conftest import DB, DEVICE

pytestmark = DB


class BusinessFailure(Exception):
    pass


def test_security_events_use_the_dedicated_connection():
    assert SecurityEvent.objects.all().db == SECURITY_LOG_ALIAS


def test_immediate_event_survives_business_rollback(user):
    with pytest.raises(BusinessFailure), transaction.atomic():
        record_security_event(SecurityEventType.LOGIN_FAILED, user=user)
        raise BusinessFailure()

    assert SecurityEvent.objects.filter(event_type=SecurityEventType.LOGIN_FAILED, user=user).exists()


def test_failed_login_is_kept_even_if_the_request_transaction_rolls_back(user):
    """The view used to *return* an error to keep the event committed. With the
    dedicated connection, the event survives even when the surrounding
    transaction (ATOMIC_REQUESTS) is rolled back by an exception."""
    with pytest.raises(services.InvalidCredentials), transaction.atomic():
        services.login(user.username, "wrong-password", DEVICE, ClientContext(ip_address="10.0.0.7"))

    event = SecurityEvent.objects.get(event_type=SecurityEventType.LOGIN_FAILED)
    assert event.ip_address == "10.0.0.7"
    assert event.metadata == {"identifier": user.username}


def test_success_event_is_not_written_when_business_transaction_rolls_back(user, committed):
    with committed(), pytest.raises(BusinessFailure), transaction.atomic():
        record_security_event(SecurityEventType.PASSWORD_CHANGED, user=user, after_commit=True)
        raise BusinessFailure()

    assert not SecurityEvent.objects.exists()


def test_success_event_is_written_once_committed(user, committed):
    with committed():
        with transaction.atomic():
            record_security_event(SecurityEventType.PASSWORD_CHANGED, user=user, after_commit=True)
        # Not yet: on_commit callbacks fire at the real commit (end of block).
        assert not SecurityEvent.objects.exists()

    assert SecurityEvent.objects.filter(event_type=SecurityEventType.PASSWORD_CHANGED).count() == 1


def test_event_may_reference_a_row_not_yet_committed_by_the_business_connection(committed):
    """Why db_constraint=False: the user below exists only inside the business
    transaction; a DB-level foreign key would make the security log reject it."""
    from .factories import UserFactory

    with pytest.raises(BusinessFailure), transaction.atomic():
        ghost = UserFactory()
        record_security_event(SecurityEventType.LOGIN_FAILED, user=ghost)
        raise BusinessFailure()

    event = SecurityEvent.objects.get()
    assert event.user_id == ghost.id  # kept, pointing to a user that was rolled back

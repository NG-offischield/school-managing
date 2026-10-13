"""System notifications in the reader's language (French / English): REST
(Accept-Language) and WebSocket (connection language). Business data (names,
references, amounts, dates) and what people wrote stay exactly as they are;
the API keeps the same fields; rows created before the texts are shown as stored."""

import re
from decimal import Decimal

import pytest
from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.utils.translation import override
from rest_framework.test import APIClient

from apps.communication import messaging, notifications, texts
from apps.communication.consumers import connection_language
from apps.communication.models import Notification
from apps.communication.texts import label, text
from config.asgi import application

from .communication_world import make_communication_world
from .conftest import DB
from .test_notifications import inbox, late_scan
from .test_realtime import tokens

pytestmark = DB
API_FIELDS = {"id", "notification_type", "severity", "title", "message", "payload", "is_read", "read_at", "created_at"}


@pytest.fixture
def w(school):
    return make_communication_world(school)


def client(member, language=None):
    api = APIClient()
    api.force_authenticate(member.user)
    if language:
        api.credentials(HTTP_ACCEPT_LANGUAGE=language)
    return api


def listed(member, language=None, kind=None):
    url = "/api/v1/notifications/" + (f"?type={kind}" if kind else "")
    return client(member, language).get(url).json()["data"]


# --- the catalog ---------------------------------------------------------------------


def _sample(key):
    """`key` with every parameter filled by a recognisable value."""
    if key == "payment.admin.invoices":  # plural template: its form comes from n
        return text(key, n=2, numbers="<numbers>")
    with override("en"):
        names = set(re.findall(r"%\((\w+)\)s", str(texts.TEXTS[key])))
    return text(key, **{name: f"<{name}>" for name in names})


@pytest.mark.parametrize("key", sorted(texts.TEXTS))
def test_every_system_text_exists_in_french_and_english(key):
    spec = _sample(key)
    french, english = texts.render(spec, "fr"), texts.render(spec, "en")
    assert french and english
    for name, value in spec["params"].items():
        if name != "n":  # business data inserted untouched, in both languages
            assert value in french and value in english, (key, name)
    if key not in {"attendance.absent.title", "schedule.message", "plan.version.located", "plan.version"}:
        assert french != english, f"{key}: no French translation (compiled catalog?)"


@pytest.mark.parametrize("group", sorted(texts.LABELS))
def test_status_labels_exist_in_both_languages(group):
    for code in texts.LABELS[group]:
        french = texts.render(text("schedule.message", change=label(group, code)), "fr")
        english = texts.render(text("schedule.message", change=label(group, code)), "en")
        assert french and english and (french != english or code == "MISSED")


def test_unsupported_language_falls_back_to_french():
    spec = text("payment.confirmed.title")
    assert texts.render(spec, "de") == texts.render(spec, "fr") == "Paiement confirmé"
    assert connection_language("de-DE,en;q=0.5") == "en"
    assert connection_language("en-GB,en;q=0.9") == "en"
    assert connection_language("es") == "fr" and connection_language("") == "fr" and connection_language(None) == "fr"


def test_schedule_labels_are_real_words_not_constant_names():
    """Before: « Planning : Session Cancelled » (choices without labels)."""
    change = label("change_type", "SESSION_CANCELLED")
    assert texts.render(text("schedule.teacher.title", change=change), "fr") == "Planning : Séance annulée"
    assert texts.render(text("schedule.teacher.title", change=change), "en") == "Schedule: Lesson cancelled"


# --- REST: Accept-Language -----------------------------------------------------------


def test_attendance_notification_follows_the_request_language(w):
    late_scan(w, w.students[0])
    note = inbox(w.parent, "ATTENDANCE_LATE").get()
    name = w.students[0].full_name
    assert note.title == f"Retard — {name}"  # stored French rendering, as before
    french = listed(w.parent, "fr", "ATTENDANCE_LATE")[0]
    english = listed(w.parent, "en", "ATTENDANCE_LATE")[0]
    default = listed(w.parent, None, "ATTENDANCE_LATE")[0]
    assert french["title"] == default["title"] == f"Retard — {name}"
    assert english["title"] == f"Late arrival — {name}"
    date = "/".join(reversed(note.payload["date"].split("-")))  # the attendance day, dd/mm/yyyy
    assert english["message"] == f"{name} arrived {note.payload['late_minutes']} min late on {date}."
    assert french["message"] == note.message and "est arrivé(e) avec" in french["message"]
    # same fields, same business payload, nothing internal exposed
    assert set(english) == set(french) == API_FIELDS
    assert english["payload"] == french["payload"] == note.payload


def test_amounts_and_references_are_never_rewritten(w):
    spec = text(
        "payment.payer.message",
        reference="PAY-2026-0042",
        amount=Decimal("60000.50"),
        currency="XAF",
        status=label("payment_status", "SUCCEEDED", lower=True),
    )
    note = notifications.notify(
        w.parent,
        school=w.school,
        notification_type="PAYMENT",
        title=text("payment.confirmed.title"),
        message=spec,
        event_key="test:language:payment",
        payload={"amount": "60000.50"},
    )
    assert note.message == "Paiement PAY-2026-0042 de 60000.50 XAF : réussi."
    english = listed(w.parent, "en", "PAYMENT")[0]
    assert english["title"] == "Payment confirmed"
    assert english["message"] == "Payment PAY-2026-0042 of 60000.50 XAF: succeeded."
    assert english["payload"] == {"amount": "60000.50"}


def test_what_people_wrote_is_never_translated(w):
    body = "Bonjour, l'élève sera absent demain — merci de prévenir."
    conversation, _ = messaging.create_conversation(
        w.parent, conversation_type="PARENT_TEACHER", participants=[w.tm_member], student=w.students[0], body=body
    )
    sender = w.parent.user.full_name
    english = listed(w.tm_member, "en", "MESSAGE")[0]
    french = listed(w.tm_member, "fr", "MESSAGE")[0]
    assert english["title"] == f"Message from {sender}" and french["title"] == f"Message de {sender}"
    assert english["message"] == french["message"] == body  # the person's own words
    assert english["payload"]["conversation"] == str(conversation.pk)


def test_rows_without_a_text_description_are_shown_as_stored(w):
    """Notifications created before the texts (or user-written titles)."""
    note = notifications.notify(
        w.parent,
        school=w.school,
        notification_type="ANNOUNCEMENT",
        title="Sortie au musée",
        message="Vendredi 9h, prévoir un pique-nique.",
        event_key="test:language:raw",
    )
    assert note.text == {}
    english = listed(w.parent, "en", "ANNOUNCEMENT")[0]
    assert (english["title"], english["message"]) == ("Sortie au musée", "Vendredi 9h, prévoir un pique-nique.")


def test_the_text_description_is_immutable_like_the_rest(w):
    from django.db import IntegrityError, transaction
    from django.db.utils import DatabaseError

    late_scan(w, w.students[0])
    note = inbox(w.parent, "ATTENDANCE_LATE").get()
    with pytest.raises((IntegrityError, DatabaseError)), transaction.atomic():
        Notification.objects.filter(pk=note.pk).update(text={})


# --- WebSocket: the connection's language --------------------------------------------


async def _socket(member, language=None):
    issued = await database_sync_to_async(tokens)(member)
    headers = [(b"authorization", f"Bearer {issued.access_token}".encode())]
    if language:
        headers.append((b"accept-language", language.encode()))
    communicator = WebsocketCommunicator(application, "/ws/v1/realtime/", headers=headers)
    connected, _ = await communicator.connect()
    assert connected and (await communicator.receive_json_from())["type"] == "auth.ok"
    return communicator


def test_real_time_frames_are_rendered_per_connection(w):
    name = w.students[0].full_name

    async def scenario():
        english = await _socket(w.parent, "en-GB,en;q=0.9")
        french = await _socket(w.parent, "fr")
        await database_sync_to_async(late_scan)(w, w.students[0])
        en_frame = await english.receive_json_from(timeout=2)
        fr_frame = await french.receive_json_from(timeout=2)
        assert en_frame["data"]["title"] == f"Late arrival — {name}"
        assert fr_frame["data"]["title"] == f"Retard — {name}"
        assert "text" not in en_frame and set(en_frame["data"]) == API_FIELDS
        assert en_frame["data"]["payload"] == fr_frame["data"]["payload"]
        await english.send_json_to({"type": "sync"})
        synced = await english.receive_json_from(timeout=2)
        assert [n["title"] for n in synced["notifications"]] == [f"Late arrival — {name}"]
        for socket in (english, french):
            await socket.disconnect()

    async_to_sync(scenario)()


def test_browser_auth_frame_can_carry_the_language(w):
    name = w.students[0].full_name

    async def scenario():
        issued = await database_sync_to_async(tokens)(w.parent)
        socket = WebsocketCommunicator(application, "/ws/v1/realtime/", headers=[(b"origin", b"http://localhost")])
        assert (await socket.connect())[0]
        await socket.send_json_to({"type": "auth", "token": issued.access_token, "language": "en"})
        assert (await socket.receive_json_from())["type"] == "auth.ok"
        await database_sync_to_async(late_scan)(w, w.students[0])
        assert (await socket.receive_json_from(timeout=2))["data"]["title"] == f"Late arrival — {name}"
        await socket.disconnect()

    async_to_sync(scenario)()

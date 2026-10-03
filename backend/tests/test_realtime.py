"""WebSocket `ws/v1/realtime/`: same tokens and scope as REST, notifications
to their recipient only, real-time conversations, resynchronisation after a
reconnection, revocation, origin check."""

from datetime import timedelta

import pytest
from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.utils import timezone

from apps.accounts.services import ClientContext, login, revoke_session
from apps.communication import consumers, messaging
from config.asgi import application

from .communication_world import make_communication_world
from .conftest import DB, DEVICE
from .factories import DEFAULT_PASSWORD, SchoolFactory
from .test_notifications import late_scan

pytestmark = DB
PATH = "/ws/v1/realtime/"


@pytest.fixture
def w(school):
    return make_communication_world(school)


def tokens(member):
    return login(member.user.username, DEFAULT_PASSWORD, DEVICE, ClientContext())


def run(scenario):
    async_to_sync(scenario)()


async def open_socket(token=None, origin=None):
    headers = []
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    if origin:
        headers.append((b"origin", origin.encode()))
    communicator = WebsocketCommunicator(application, PATH, headers=headers)
    connected, _ = await communicator.connect()
    return communicator, connected


async def authenticated(member):
    issued = await database_sync_to_async(tokens)(member)
    communicator, connected = await open_socket(issued.access_token)
    assert connected
    hello = await communicator.receive_json_from()
    assert hello["type"] == "auth.ok" and hello["membership"] == str(member.pk)
    return communicator, issued


async def closed_with(communicator, code):
    output = await communicator.receive_output()
    if output["type"] == "websocket.send":  # an error frame first
        output = await communicator.receive_output()
    return output == {"type": "websocket.close", "code": code}


def test_header_authentication_ping_and_bad_tokens(w):
    async def scenario():
        socket, _ = await authenticated(w.parent)
        await socket.send_json_to({"type": "ping"})
        assert await socket.receive_json_from() == {"type": "pong"}
        await socket.disconnect()
        bad, connected = await open_socket("not-a-token")
        assert connected and await closed_with(bad, consumers.UNAUTHORIZED)

    run(scenario)


def test_first_frame_authentication_for_browsers(w):
    async def scenario():
        issued = await database_sync_to_async(tokens)(w.tm_member)
        socket, connected = await open_socket(origin="http://localhost")
        assert connected
        await socket.send_json_to({"type": "auth", "token": issued.access_token})
        assert (await socket.receive_json_from())["type"] == "auth.ok"
        await socket.disconnect()
        anonymous, _ = await open_socket()
        await anonymous.send_json_to({"type": "subscribe", "conversation": "x"})
        assert (await anonymous.receive_json_from())["code"] == "NOT_AUTHENTICATED"
        assert await closed_with(anonymous, consumers.UNAUTHORIZED)

    run(scenario)


def test_foreign_browser_origin_is_refused(w):
    async def scenario():
        issued = await database_sync_to_async(tokens)(w.parent)
        _, connected = await open_socket(issued.access_token, origin="https://evil.example")
        assert not connected

    run(scenario)


def test_notifications_reach_their_recipient_only(w):
    """Mutation target: real-time delivery goes to the explicit recipient."""

    async def scenario():
        parent, _ = await authenticated(w.parent)
        other, _ = await authenticated(w.other_parent)
        teacher, _ = await authenticated(w.tm_member)
        await database_sync_to_async(late_scan)(w, w.students[0])
        frame = await parent.receive_json_from(timeout=2)
        assert frame["type"] == "notification" and frame["data"]["notification_type"] == "ATTENDANCE_LATE"
        assert await other.receive_nothing(timeout=0.3)
        assert await teacher.receive_nothing(timeout=0.3)
        for socket in (parent, other, teacher):
            await socket.disconnect()

    run(scenario)


def test_conversation_in_real_time_with_deduplicated_resend(w):
    conversation, _ = messaging.create_conversation(
        w.parent, conversation_type="PARENT_TEACHER", participants=[w.tm_member], student=w.students[0], body="Bonjour"
    )

    async def scenario():
        parent, _ = await authenticated(w.parent)
        teacher, _ = await authenticated(w.tm_member)
        outsider, _ = await authenticated(w.other_parent)
        for socket in (parent, teacher):
            await socket.send_json_to({"type": "subscribe", "conversation": str(conversation.pk)})
            subscribed = await socket.receive_json_from()
            assert subscribed["type"] == "subscribed" and [m["body"] for m in subscribed["messages"]] == ["Bonjour"]
        await outsider.send_json_to({"type": "subscribe", "conversation": str(conversation.pk)})
        assert (await outsider.receive_json_from())["code"] == "NOT_FOUND"
        frame = {"type": "message.send", "conversation": str(conversation.pk), "body": "Réponse", "client_id": "t-1"}
        await teacher.send_json_to(frame)
        replies = [await teacher.receive_json_from(timeout=2) for _ in range(2)]
        ack = next(r for r in replies if r["type"] == "message.ack")
        assert ack["created"] is True
        pushed = await parent.receive_json_from(timeout=2)
        assert pushed["type"] == "message.created" and pushed["data"]["body"] == "Réponse"
        # A notification frame for the new message arrives too (member group).
        notification = await parent.receive_json_from(timeout=2)
        assert notification["data"]["notification_type"] == "MESSAGE"
        await teacher.send_json_to(frame)  # resend after a "reconnection"
        assert (await teacher.receive_json_from())["created"] is False
        assert await parent.receive_nothing(timeout=0.3)
        assert await outsider.receive_nothing(timeout=0.3)
        for socket in (parent, teacher, outsider):
            await socket.disconnect()

    run(scenario)


def test_sync_after_reconnection_returns_what_was_missed(w):
    before = timezone.now() - timedelta(seconds=1)
    late_scan(w, w.students[0])  # happened while the parent was offline

    async def scenario():
        socket, _ = await authenticated(w.parent)
        await socket.send_json_to({"type": "sync", "since": before.isoformat()})
        frame = await socket.receive_json_from()
        assert frame["type"] == "sync" and frame["unread_notifications"] == 1
        assert [n["notification_type"] for n in frame["notifications"]] == ["ATTENDANCE_LATE"]
        await socket.disconnect()

    run(scenario)


def test_revoked_session_is_disconnected(w, monkeypatch):
    monkeypatch.setattr(consumers, "REVALIDATE_SECONDS", 0)

    async def scenario():
        socket, issued = await authenticated(w.parent)
        await database_sync_to_async(revoke_session)(issued.session)
        await socket.send_json_to({"type": "ping"})
        assert await closed_with(socket, consumers.UNAUTHORIZED)

    run(scenario)


def test_no_cross_school_subscription(w):
    conversation, _ = messaging.create_conversation(
        w.parent, conversation_type="PARENT_TEACHER", participants=[w.tm_member], student=w.students[0], body="x"
    )
    other = make_communication_world(SchoolFactory())

    async def scenario():
        socket, _ = await authenticated(other.admin)
        await socket.send_json_to({"type": "subscribe", "conversation": str(conversation.pk)})
        assert (await socket.receive_json_from())["code"] == "NOT_FOUND"
        await socket.send_json_to({"type": "message.send", "conversation": str(conversation.pk), "body": "x"})
        assert (await socket.receive_json_from())["code"] == "NOT_FOUND"
        await socket.disconnect()

    run(scenario)


def test_missing_origin_is_not_an_authentication_bypass(w):
    """ADR 0015: a missing Origin is tolerated for native token clients only.
    The socket never authenticates from a cookie / Django session, so a
    browser's ambient credentials grant nothing, with or without Origin."""
    from django.test import Client

    browser = Client()
    browser.force_login(w.admin.user)
    cookie = f"sessionid={browser.cookies['sessionid'].value}".encode()

    async def scenario():
        # Valid session cookie, no token, no Origin: connected but anonymous.
        socket = WebsocketCommunicator(application, PATH, headers=[(b"cookie", cookie)])
        connected, _ = await socket.connect()
        assert connected
        await socket.send_json_to({"type": "sync"})
        assert (await socket.receive_json_from())["code"] == "NOT_AUTHENTICATED"
        assert await closed_with(socket, consumers.UNAUTHORIZED)
        # Same cookie from a foreign page: refused at the handshake.
        hijack = WebsocketCommunicator(
            application, PATH, headers=[(b"cookie", cookie), (b"origin", b"https://evil.example")]
        )
        connected, _ = await hijack.connect()
        assert not connected
        # No Origin and no token: nothing is accepted before authentication.
        native = WebsocketCommunicator(application, PATH)
        connected, _ = await native.connect()
        assert connected
        await native.send_json_to({"type": "auth", "token": "forged"})
        assert (await native.receive_json_from())["code"] == "NOT_AUTHENTICATED"
        assert await closed_with(native, consumers.UNAUTHORIZED)

    run(scenario)

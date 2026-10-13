"""Real-time WebSocket endpoint `ws/v1/realtime/` (ADR 0015).

One consumer on the existing Channels stack, same rules as REST (spec §9):

Authentication (same tokens as REST, revocation effective immediately):
- native clients (Flutter, PySide6): `Authorization: Bearer <access>` header
  at the handshake (+ optional `X-School-Code`);
- browsers (cannot set headers): first frame {"type": "auth", "token": ...,
  "school": optional code, "language": optional}. Nothing else is accepted before it.
Language: `Accept-Language` at the handshake (or "language" of the auth
frame), fr / en, French otherwise. System notification texts are rendered in
it (notifications.localized); what people wrote is forwarded untouched.
Failure -> close code 4401. The session and the membership are re-checked
at least every REVALIDATE_SECONDS while the socket lives.

Client -> server frames
    {"type": "ping"}                                   -> {"type": "pong"}
    {"type": "sync", "since": ISO}                     -> missed notifications + unread count
    {"type": "subscribe", "conversation": id, "since": ISO?}
                                                       -> subscribed + missed messages
    {"type": "unsubscribe", "conversation": id}
    {"type": "message.send", "conversation": id, "body": ..., "client_id": ...}
                                                       -> message.ack (a resend with the same
                                                          client_id is acknowledged, not duplicated)
    {"type": "read", "conversation": id}
Server -> client frames
    notification, message.created, message.deleted, participant.joined, error

Robust reconnection: every frame carries server timestamps; after a
reconnection the client sends "sync" / "subscribe" with the last timestamp
it saw and receives what it missed; message resends are deduplicated by
client_id. Every forwarded conversation event re-checks that the member may
still read the conversation.
"""

import time
import uuid

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils.dateparse import parse_datetime

from apps.accounts.authentication import session_from_access_token
from apps.accounts.models import MembershipStatus, SchoolMembership, UserSession
from common.tenancy import resolve_membership

from . import access, messaging, realtime, texts
from .models import Conversation, Message, Notification
from .notifications import localized, serialize, unread_count

REVALIDATE_SECONDS = 30
SYNC_LIMIT = 100
UNAUTHORIZED = 4401


# --- synchronous helpers (database) ---------------------------------------------


def _authenticate(token, school_code):
    session = session_from_access_token(token)
    if session is None:
        return None
    membership = resolve_membership(session.user, school_code)
    if membership is None:
        return None
    return {"membership": membership.pk, "session": session.pk, "unread": unread_count(membership)}


def _still_valid(membership_id, session_id):
    session = UserSession.objects.filter(pk=session_id).first()
    return (
        session is not None
        and session.is_usable()
        and SchoolMembership.objects.active().filter(pk=membership_id, status=MembershipStatus.ACTIVE).exists()
    )


def _member(membership_id):
    return SchoolMembership.objects.select_related("school", "user").get(pk=membership_id)


def _conversation(membership, conversation_id):
    try:
        conversation_uuid = uuid.UUID(str(conversation_id))
    except ValueError:
        return None
    conversation = Conversation.objects.filter(pk=conversation_uuid, school=membership.school).first()
    if conversation is None or not access.can_read_conversation(membership, conversation):
        return None
    return conversation


def connection_language(value):
    """'en-GB,en;q=0.9,fr;q=0.8' -> 'en'; unsupported or missing -> 'fr'."""
    for part in str(value or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in ("fr", "en"):
            return code
    return texts.DEFAULT_LANGUAGE


def localize_frame(frame, language):
    """A notification frame from notify(): title / message rendered in the
    connection's language; the internal text description is not forwarded."""
    if frame.get("type") != "notification":
        return frame
    frame = dict(frame)
    description = frame.pop("text", None) or {}
    data = dict(frame["data"])
    if description:
        holder = Notification(title=data["title"], message=data["message"], text=description)
        data["title"], data["message"] = localized(holder, language)
    frame["data"] = data
    return frame


def _sync(membership_id, since, language=texts.DEFAULT_LANGUAGE):
    membership = _member(membership_id)
    notifications = Notification.objects.filter(recipient=membership)
    if since is not None:
        notifications = notifications.filter(created_at__gt=since)
    latest = list(notifications.order_by("-created_at")[:SYNC_LIMIT])
    return {
        "type": "sync",
        "notifications": [serialize(n, language) for n in reversed(latest)],
        "unread_notifications": unread_count(membership),
    }


def _subscribe(membership_id, conversation_id, since):
    membership = _member(membership_id)
    conversation = _conversation(membership, conversation_id)
    if conversation is None:
        return None
    messages = Message.objects.filter(conversation=conversation).select_related("sender__user")
    if since is not None:
        messages = messages.filter(created_at__gt=since)
    missed = list(messages.order_by("-created_at")[:SYNC_LIMIT])
    return {
        "type": "subscribed",
        "conversation": str(conversation.pk),
        "messages": [messaging.serialize_message(m, membership) for m in reversed(missed)],
    }


def _can_read(membership_id, conversation_id):
    membership = _member(membership_id)
    return _conversation(membership, conversation_id) is not None


def _send(membership_id, conversation_id, body, client_id):
    membership = _member(membership_id)
    conversation = _conversation(membership, conversation_id)
    if conversation is None:
        return {"type": "error", "code": "NOT_FOUND", "client_id": client_id}
    try:
        message, created = messaging.send_message(conversation, actor=membership, body=body, client_id=client_id)
    except PermissionDenied:
        return {"type": "error", "code": "PERMISSION_DENIED", "client_id": client_id}
    except ValidationError as exc:
        return {"type": "error", "code": "BUSINESS_RULE_VIOLATION", "rule": exc.code, "client_id": client_id}
    return {
        "type": "message.ack",
        "client_id": client_id,
        "message": str(message.pk),
        "created": created,
        "created_at": message.created_at.isoformat(),
    }


def _read(membership_id, conversation_id):
    membership = _member(membership_id)
    conversation = _conversation(membership, conversation_id)
    if conversation is None:
        return {"type": "error", "code": "NOT_FOUND"}
    try:
        messaging.mark_read(conversation, actor=membership)
    except PermissionDenied:
        return {"type": "error", "code": "PERMISSION_DENIED"}
    return {"type": "read.ack", "conversation": str(conversation.pk)}


def _since(value):
    return parse_datetime(value) if isinstance(value, str) else None


# --- consumer ------------------------------------------------------------------------


class RealtimeConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.membership_id = None
        self.session_id = None
        self.conversations = set()
        self.checked_at = 0.0
        await self.accept()
        headers = dict(self.scope.get("headers", []))
        self.language = connection_language(headers.get(b"accept-language", b"").decode("latin1"))
        authorization = headers.get(b"authorization", b"").decode("latin1")
        if authorization:
            scheme, _, token = authorization.partition(" ")
            school = headers.get(b"x-school-code", b"").decode("latin1") or None
            if scheme.lower() != "bearer" or not await self._login(token.strip(), school):
                await self.close(code=UNAUTHORIZED)

    async def disconnect(self, code):
        if self.membership_id is not None:
            await self.channel_layer.group_discard(realtime.member_group(self.membership_id), self.channel_name)
        for conversation in self.conversations:
            await self.channel_layer.group_discard(realtime.conversation_group(conversation), self.channel_name)

    async def _login(self, token, school):
        result = await database_sync_to_async(_authenticate)(token, school)
        if result is None:
            return False
        self.membership_id, self.session_id = result["membership"], result["session"]
        self.checked_at = time.monotonic()
        await self.channel_layer.group_add(realtime.member_group(self.membership_id), self.channel_name)
        await self.send_json(
            {"type": "auth.ok", "membership": str(self.membership_id), "unread_notifications": result["unread"]}
        )
        return True

    async def _valid(self):
        """Session revoked, logged out or membership suspended -> closed."""
        if time.monotonic() - self.checked_at < REVALIDATE_SECONDS:
            return True
        if await database_sync_to_async(_still_valid)(self.membership_id, self.session_id):
            self.checked_at = time.monotonic()
            return True
        await self.close(code=UNAUTHORIZED)
        return False

    async def receive_json(self, content, **kwargs):
        kind = content.get("type") if isinstance(content, dict) else None
        if self.membership_id is None:
            if kind == "auth" and content.get("language"):
                self.language = connection_language(content.get("language"))
            if kind == "auth" and await self._login(str(content.get("token") or ""), content.get("school")):
                return
            await self.send_json({"type": "error", "code": "NOT_AUTHENTICATED"})
            await self.close(code=UNAUTHORIZED)
            return
        if not await self._valid():
            return
        if kind == "ping":
            await self.send_json({"type": "pong"})
        elif kind == "sync":
            await self.send_json(
                await database_sync_to_async(_sync)(self.membership_id, _since(content.get("since")), self.language)
            )
        elif kind == "subscribe":
            frame = await database_sync_to_async(_subscribe)(
                self.membership_id, content.get("conversation"), _since(content.get("since"))
            )
            if frame is None:
                await self.send_json(
                    {"type": "error", "code": "NOT_FOUND", "conversation": content.get("conversation")}
                )
                return
            conversation = uuid.UUID(frame["conversation"])
            self.conversations.add(conversation)
            await self.channel_layer.group_add(realtime.conversation_group(conversation), self.channel_name)
            await self.send_json(frame)
        elif kind == "unsubscribe":
            try:
                conversation = uuid.UUID(str(content.get("conversation")))
            except ValueError:
                return
            self.conversations.discard(conversation)
            await self.channel_layer.group_discard(realtime.conversation_group(conversation), self.channel_name)
        elif kind == "message.send":
            await self.send_json(
                await database_sync_to_async(_send)(
                    self.membership_id, content.get("conversation"), content.get("body"), content.get("client_id")
                )
            )
        elif kind == "read":
            await self.send_json(await database_sync_to_async(_read)(self.membership_id, content.get("conversation")))
        else:
            await self.send_json({"type": "error", "code": "UNKNOWN_FRAME"})

    # --- group events (from realtime.py) ---

    async def member_event(self, event):
        if await self._valid():
            await self.send_json(localize_frame(event["frame"], self.language))

    async def conversation_event(self, event):
        conversation = uuid.UUID(event["conversation"])
        if conversation not in self.conversations or not await self._valid():
            return
        # Removed from the conversation since subscribing? Stop forwarding.
        if not await database_sync_to_async(_can_read)(self.membership_id, conversation):
            self.conversations.discard(conversation)
            await self.channel_layer.group_discard(realtime.conversation_group(conversation), self.channel_name)
            return
        await self.send_json(event["frame"])

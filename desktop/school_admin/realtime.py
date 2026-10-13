"""Real-time client of the EXISTING Channels endpoint `ws/v1/realtime/`
(backend communication/consumers.py, ADR 0015 / 0023). No second
infrastructure: Qt's own QWebSocket, the same access token as REST.

    connection   handshake with `Authorization: Bearer <access>` (native client)
                 -> {"type": "auth.ok", "unread_notifications": n}
    resync       after every (re)connection: {"type": "sync", "since": last seen}
                 and {"type": "subscribe", "conversation", "since"} for the open
                 conversations -> what was missed while offline
    keep-alive   {"type": "ping"} every 25 s
    pushes       notification, message.created, message.deleted, participant.joined
    close 4401   token expired, session revoked or membership suspended:
                 one token refresh through the REST client, then reconnection;
                 a failed refresh -> `session_expired` (back to the login)
    other drops  reconnection with backoff (1, 2, 4 … 30 s)

The server re-checks every permission; this client only relays frames.
"""

import json
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkRequest

from .i18n import language

UNAUTHORIZED = 4401
PING_MS = 25_000
BACKOFF = (1, 2, 4, 8, 15, 30)


def socket_url(api_url):
    """'http://h:8000/api/v1/' -> 'ws://h:8000/ws/v1/realtime/' (wss for https)."""
    parts = urlsplit(api_url)
    scheme = "wss" if parts.scheme == "https" else "ws"
    return f"{scheme}://{parts.netloc}/ws/v1/realtime/"


def _qt_socket():
    from PySide6.QtWebSockets import QWebSocket

    return QWebSocket()


class RealtimeClient(QObject):
    state_changed = Signal(str)  # "connecting" | "online" | "offline" | "expired" | "stopped"
    notification = Signal(dict)
    notifications_synced = Signal(list)
    unread_changed = Signal(int)
    message_created = Signal(dict)
    message_deleted = Signal(dict)
    conversation_synced = Signal(str, list)
    session_expired = Signal()

    def __init__(self, api, url, *, socket_factory=_qt_socket, parent=None):
        super().__init__(parent)
        self.api, self.url, self.socket_factory = api, url, socket_factory
        self.socket = None
        self.state = "stopped"
        self.last_seen = None  # server timestamp of the last notification seen
        self.conversations = {}  # id -> server timestamp of the last message seen
        self.attempt = 0
        self._refreshed = False
        self.ping_timer = QTimer(self, interval=PING_MS, timeout=lambda: self._send({"type": "ping"}))
        self.retry_timer = QTimer(self, singleShot=True, timeout=self.start)

    # --- lifecycle -----------------------------------------------------------------------
    def start(self):
        if not self.api.access_token:
            self._set_state("expired")
            self.session_expired.emit()
            return
        self._drop_socket()
        self.socket = self.socket_factory()
        self.socket.connected.connect(self._on_connected)
        self.socket.disconnected.connect(self._on_disconnected)
        self.socket.textMessageReceived.connect(self._on_text)
        request = QNetworkRequest(QUrl(self.url))
        request.setRawHeader(b"Authorization", f"Bearer {self.api.access_token}".encode())
        # the server renders system notifications in the interface language
        request.setRawHeader(b"Accept-Language", language().encode())
        self._set_state("connecting")
        self.socket.open(request)

    def stop(self):
        self.retry_timer.stop()
        self.ping_timer.stop()
        self._drop_socket()
        self._set_state("stopped")

    def _drop_socket(self):
        if self.socket is not None:
            socket, self.socket = self.socket, None
            for signal in (socket.connected, socket.disconnected, socket.textMessageReceived):
                try:
                    signal.disconnect()
                except (RuntimeError, TypeError):
                    pass
            socket.close()

    def _set_state(self, state):
        if state != self.state:
            self.state = state
            self.state_changed.emit(state)

    # --- conversations -------------------------------------------------------------------
    def watch(self, conversation_id, since=None):
        """Receive the messages of a conversation live (re-subscribed after a reconnection)."""
        self.conversations[conversation_id] = since or self.conversations.get(conversation_id)
        if self.state == "online":
            self._subscribe(conversation_id)

    def unwatch(self, conversation_id):
        self.conversations.pop(conversation_id, None)
        self._send({"type": "unsubscribe", "conversation": conversation_id})

    def _subscribe(self, conversation_id):
        frame = {"type": "subscribe", "conversation": conversation_id}
        if self.conversations.get(conversation_id):
            frame["since"] = self.conversations[conversation_id]
        self._send(frame)

    # --- socket events -------------------------------------------------------------------
    def _send(self, frame):
        if self.socket is not None and self.state == "online":
            self.socket.sendTextMessage(json.dumps(frame))

    def _on_connected(self):
        pass  # authenticated by the Bearer header: wait for auth.ok

    def _on_disconnected(self):
        code = self.socket.closeCode() if self.socket is not None else None
        self.ping_timer.stop()
        if self.state == "stopped":
            return
        if code == UNAUTHORIZED:
            # Expired token, revoked session or suspended membership: one refresh, else login.
            if not self._refreshed and self.api._try_refresh():
                self._refreshed = True
                self._set_state("connecting")
                QTimer.singleShot(0, self.start)
                return
            self._drop_socket()
            self._set_state("expired")
            self.session_expired.emit()
            return
        self._set_state("offline")
        delay = BACKOFF[min(self.attempt, len(BACKOFF) - 1)]
        self.attempt += 1
        self.retry_timer.start(delay * 1000)

    def _on_text(self, text):
        try:
            frame = json.loads(text)
        except ValueError:
            return
        kind = frame.get("type")
        if kind == "auth.ok":
            self.attempt, self._refreshed = 0, False
            self._set_state("online")
            self.ping_timer.start()
            self.unread_changed.emit(int(frame.get("unread_notifications") or 0))
            sync = {"type": "sync"}
            if self.last_seen:
                sync["since"] = self.last_seen
            self._send(sync)
            for conversation_id in list(self.conversations):
                self._subscribe(conversation_id)
        elif kind == "notification":
            data = frame.get("data") or {}
            self.last_seen = data.get("created_at") or self.last_seen
            self.notification.emit(data)
        elif kind == "sync":
            rows = frame.get("notifications") or []
            if rows:
                self.last_seen = rows[-1].get("created_at") or self.last_seen
            self.notifications_synced.emit(rows)
            self.unread_changed.emit(int(frame.get("unread_notifications") or 0))
        elif kind == "subscribed":
            rows = frame.get("messages") or []
            conversation_id = frame.get("conversation")
            if rows and conversation_id in self.conversations:
                self.conversations[conversation_id] = rows[-1].get("created_at")
            self.conversation_synced.emit(conversation_id, rows)
        elif kind == "message.created":
            data = frame.get("data") or {}
            if data.get("conversation") in self.conversations:
                self.conversations[data["conversation"]] = data.get("created_at")
            self.message_created.emit(data)
        elif kind == "message.deleted":
            self.message_deleted.emit(frame)

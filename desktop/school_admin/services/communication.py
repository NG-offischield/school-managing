"""Communication (backend communication/api.py, ADR 0015 / 0023). Thin
client: visibility (who may read a conversation, a thread, a complaint),
transitions of a complaint, moderation and attachment checks (PDF / PNG /
JPEG, real content, size, private storage) are the server's. Nothing is
deleted: a message or a post is hidden, a complaint is cancelled.

    GET  /notifications/?is_read=&type=&severity=   GET /notifications/unread-count/
    POST /notifications/{id}/read/   POST /notifications/read-all/
    GET/POST /conversations/   GET /conversations/{id}/   GET/POST /conversations/{id}/messages/
    POST /conversations/{id}/read/ | /participants/   DELETE /messages/{id}/
    GET  /forum/spaces/   POST /admin/forum/spaces/   GET/POST /forum/threads/?space=
    GET/POST /forum/threads/{id}/posts/   DELETE /forum/posts/{id}/ {reason}
    POST /admin/forum/threads/{id}/status/ {status, reason}
    GET  /complaints/?status=&category=   GET /complaints/{id}/   POST /complaints/{id}/cancel/
    POST /admin/complaints/{id}/status/ {status?, reason, assigned_to?}   POST /complaints/{id}/attachments/
    GET  /attachments/{message|complaint}/{id}/download/
    GET  /admin/communication/members/?search=&role=
"""

import mimetypes
import uuid
from pathlib import Path

from ..api.errors import ValidationFailed
from ..i18n import tr
from ..models import ChatMessage, Complaint, Conversation, ForumSpace, Member, Notification, Post, Thread

ACCEPTED = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def _require(**fields):
    missing = {name: [tr("Obligatoire.")] for name, value in fields.items() if value in (None, "", [])}
    if missing:
        raise ValidationFailed("Formulaire incomplet.", details=missing)


def read_attachment(path):
    """(bare name, bytes, declared type) of a local file chosen by the user.
    Only the name and the bytes are sent; the server checks the real content."""
    local = Path(path)
    content_type = (
        ACCEPTED.get(local.suffix.lower()) or mimetypes.guess_type(local.name)[0] or "application/octet-stream"
    )
    return local.name, local.read_bytes(), content_type


class CommunicationService:
    PAGE_SIZE = 50

    def __init__(self, api):
        self.api = api

    # --- notifications ----------------------------------------------------------------
    def notifications(self, *, page=1, is_read=None, kind=None, severity=None):
        rows, total = self.api.page(
            "notifications/",
            page=page,
            page_size=self.PAGE_SIZE,
            is_read=None if is_read is None else str(bool(is_read)).lower(),
            type=kind or None,
            severity=severity or None,
        )
        return [Notification.from_api(r) for r in rows], total

    def unread_notifications(self):
        return int((self.api.get("notifications/unread-count/") or {}).get("unread", 0))

    def mark_read(self, notification_id):
        return Notification.from_api(self.api.post(f"notifications/{notification_id}/read/"))

    def mark_all_read(self):
        return int((self.api.post("notifications/read-all/") or {}).get("marked", 0))

    # --- members (administration directory) -------------------------------------------
    def members(self, *, search=None, role=None):
        rows = self.api.list_all("admin/communication/members/", search=(search or "").strip() or None, role=role)
        return [Member.from_api(r) for r in rows]

    # --- conversations ----------------------------------------------------------------
    def conversations(self, *, kind=None):
        return [Conversation.from_api(r) for r in self.api.list_all("conversations/", type=kind or None)]

    def conversation(self, conversation_id):
        return Conversation.from_api(self.api.get(f"conversations/{conversation_id}/"))

    def unread_messages(self):
        return sum(c.unread for c in self.conversations())

    def start_conversation(self, *, participant_ids, title, body, files=()):
        _require(participants=list(participant_ids), body=(body or "").strip())
        fields = {
            "conversation_type": "ADMINISTRATION",
            "participants": list(participant_ids),
            "title": (title or "").strip(),
            "body": body.strip(),
            "client_id": str(uuid.uuid4()),
        }
        if files:
            data = self.api.post_multipart("conversations/", fields, [("attachments", f) for f in files])
        else:
            data = self.api.post("conversations/", fields)
        return Conversation.from_api(data)

    def messages(self, conversation_id):
        """Oldest first (the API pages newest first)."""
        rows = self.api.list_all(f"conversations/{conversation_id}/messages/")
        return [ChatMessage.from_api(r) for r in reversed(rows)]

    def send(self, conversation_id, body, *, files=(), client_id=None):
        """`client_id`: one per message intent — a resend after a network
        failure is recognised by the server (no duplicate)."""
        _require(body=(body or "").strip())
        fields = {"body": body.strip(), "client_id": client_id or str(uuid.uuid4())}
        path = f"conversations/{conversation_id}/messages/"
        if files:
            data = self.api.post_multipart(path, fields, [("attachments", f) for f in files])
        else:
            data = self.api.post(path, fields)
        return ChatMessage.from_api(data)

    def mark_conversation_read(self, conversation_id):
        return self.api.post(f"conversations/{conversation_id}/read/")

    def add_participant(self, conversation_id, member_id):
        _require(member=member_id)
        return Conversation.from_api(
            self.api.post(f"conversations/{conversation_id}/participants/", {"member": member_id})
        )

    def hide_message(self, message_id):
        """Hidden for everybody, kept for the administration (never destroyed)."""
        return ChatMessage.from_api(self.api.delete(f"messages/{message_id}/"))

    # --- forum ------------------------------------------------------------------------
    def spaces(self):
        return [ForumSpace.from_api(r) for r in self.api.get("forum/spaces/") or []]

    def create_space(self, *, name, audience, roles=(), class_id=None, announcements_only=False, description=None):
        _require(name=(name or "").strip(), audience=audience)
        payload = {
            "name": name.strip(),
            "audience": audience,
            "roles": list(roles),
            "school_class": class_id or None,
            "announcements_only": bool(announcements_only),
            "description": (description or "").strip(),
        }
        return ForumSpace.from_api(self.api.post("admin/forum/spaces/", payload))

    def threads(self, *, space_id=None):
        return [Thread.from_api(r) for r in self.api.list_all("forum/threads/", space=space_id or None)]

    def publish(self, *, space_id, title, body, announcement=False):
        _require(space=space_id, title=(title or "").strip(), body=(body or "").strip())
        payload = {
            "space": space_id,
            "title": title.strip(),
            "body": body.strip(),
            "thread_type": "ANNOUNCEMENT" if announcement else "GENERAL",
        }
        return Thread.from_api(self.api.post("forum/threads/", payload))

    def posts(self, thread_id):
        return [Post.from_api(r) for r in self.api.list_all(f"forum/threads/{thread_id}/posts/")]

    def reply(self, thread_id, body):
        _require(body=(body or "").strip())
        return Post.from_api(self.api.post(f"forum/threads/{thread_id}/posts/", {"body": body.strip()}))

    def moderate_post(self, post_id, reason):
        _require(reason=(reason or "").strip())
        return Post.from_api(self.api.request("DELETE", f"forum/posts/{post_id}/", json={"reason": reason.strip()})[0])

    def set_thread_status(self, thread_id, status, reason=None):
        payload = {"status": status, "reason": (reason or "").strip()}
        return Thread.from_api(self.api.post(f"admin/forum/threads/{thread_id}/status/", payload))

    # --- complaints -------------------------------------------------------------------
    def complaints(self, *, status=None, category=None):
        rows = self.api.list_all("complaints/", status=status or None, category=category or None)
        return [Complaint.from_api(r) for r in rows]

    def complaint(self, complaint_id):
        return Complaint.from_api(self.api.get(f"complaints/{complaint_id}/"))

    def change_status(self, complaint_id, *, status=None, reason=None, assigned_to=None):
        if not status and not assigned_to:
            raise ValidationFailed("Formulaire incomplet.", details={"status": [tr("Choisissez un statut.")]})
        payload = {"reason": (reason or "").strip()}
        if status:
            payload["status"] = status
        if assigned_to:
            payload["assigned_to"] = assigned_to
        return Complaint.from_api(self.api.post(f"admin/complaints/{complaint_id}/status/", payload))

    def cancel_complaint(self, complaint_id, reason):
        _require(reason=(reason or "").strip())
        return Complaint.from_api(self.api.post(f"complaints/{complaint_id}/cancel/", {"reason": reason.strip()}))

    def attach_to_complaint(self, complaint_id, files):
        _require(files=list(files))
        rows = self.api.post_multipart(
            f"complaints/{complaint_id}/attachments/", {}, [("attachments", f) for f in files]
        )
        return len(rows or [])

    # --- private files ----------------------------------------------------------------
    def download(self, attachment):
        """Bytes of a private attachment, after the server's permission check."""
        return self.api.get_bytes(f"attachments/{attachment.kind}/{attachment.id}/download/")

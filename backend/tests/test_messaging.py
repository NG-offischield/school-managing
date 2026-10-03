"""Private messaging and private attachments: who may talk to whom, read /
unread, soft deletion, history, isolation, download permissions."""

import pytest
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.communication import access, messaging
from apps.communication.models import Conversation, Message, MessageAttachment, Notification

from .communication_world import fake, make_communication_world, pdf, png
from .conftest import DB
from .factories import SchoolFactory

pytestmark = DB


@pytest.fixture
def w(school):
    return make_communication_world(school)


def as_(member):
    client = APIClient()
    client.force_authenticate(member.user)
    return client


def data(response, expected=200):
    assert response.status_code == expected, response.json()
    return response.json()["data"]


def error(response, expected):
    assert response.status_code == expected, response.json()
    return response.json()["error"]


def parent_teacher(w, body="Bonjour, une question sur les devoirs."):
    conversation, _ = messaging.create_conversation(
        w.parent, conversation_type="PARENT_TEACHER", participants=[w.tm_member], student=w.students[0], body=body
    )
    return conversation


# =============================================================================
# Who may talk to whom
# =============================================================================


def test_parent_and_teacher_of_the_pupil_can_talk(w):
    conversation = parent_teacher(w)
    assert set(conversation.participants.values_list("membership_id", flat=True)) == {w.parent.pk, w.tm_member.pk}
    # The same pair about the same pupil reuses the conversation.
    again, created = messaging.create_conversation(
        w.tm_member, conversation_type="PARENT_TEACHER", participants=[w.parent], student=w.students[0]
    )
    assert (again.pk, created) == (conversation.pk, False)


@pytest.mark.parametrize(
    "case",
    ["unverified_parent", "teacher_not_teaching", "parent_of_another_pupil", "guardian", "two_parents"],
)
def test_forbidden_pairs(w, case):
    actor, other = {
        "unverified_parent": (w.unverified, w.tm_member),
        "teacher_not_teaching": (w.parent, w.outsider_teacher),
        "parent_of_another_pupil": (w.other_parent, w.tm_member),
        "guardian": (w.guardian, w.tm_member),
        "two_parents": (w.parent, w.other_parent),
    }[case]
    with pytest.raises(PermissionDenied):
        messaging.create_conversation(
            actor, conversation_type="PARENT_TEACHER", participants=[other], student=w.students[0]
        )
    assert not Conversation.objects.filter(conversation_type="PARENT_TEACHER").exists()


def test_administration_conversations(w):
    conversation, _ = messaging.create_conversation(w.parent, conversation_type="ADMINISTRATION", body="Bonjour")
    assert set(conversation.participants.values_list("membership_id", flat=True)) == {w.parent.pk, w.admin.pk}
    with pytest.raises(PermissionDenied):  # a parent writes to the administration, not to anybody
        messaging.create_conversation(w.parent, conversation_type="ADMINISTRATION", participants=[w.tm_member])
    with pytest.raises(PermissionDenied):
        messaging.create_conversation(w.guardian, conversation_type="ADMINISTRATION")
    by_admin, _ = messaging.create_conversation(
        w.admin, conversation_type="ADMINISTRATION", participants=[w.staff_member], body="Réunion lundi"
    )
    assert by_admin.participants.count() == 2


# =============================================================================
# Messages, read / unread, history
# =============================================================================


def test_messages_unread_and_notifications(w):
    conversation = parent_teacher(w)
    assert messaging.unread_messages(conversation, w.tm_member) == 1
    assert messaging.unread_messages(conversation, w.parent) == 0
    note = Notification.objects.get(notification_type="MESSAGE")
    assert note.recipient == w.tm_member  # the sender is not notified of their own message
    messaging.mark_read(conversation, actor=w.tm_member)
    assert messaging.unread_messages(conversation, w.tm_member) == 0
    messaging.send_message(conversation, actor=w.tm_member, body="Réponse")
    assert messaging.unread_messages(conversation, w.parent) == 1


def test_resend_with_the_same_client_id_is_not_duplicated(w):
    conversation = parent_teacher(w)
    first, created = messaging.send_message(conversation, actor=w.parent, body="Re", client_id="c-1")
    again, created_again = messaging.send_message(conversation, actor=w.parent, body="Re", client_id="c-1")
    assert (created, created_again, again.pk) == (True, False, first.pk)


def test_delete_own_message_only_and_it_stays_in_history(w):
    conversation = parent_teacher(w)
    message = conversation.messages.get()
    with pytest.raises(PermissionDenied):
        messaging.delete_message(message, actor=w.tm_member)
    messaging.delete_message(message, actor=w.parent)
    message.refresh_from_db()
    assert message.deleted_at and message.body.startswith("Bonjour")  # hidden, not destroyed
    assert messaging.serialize_message(message, w.tm_member)["body"] is None
    assert messaging.serialize_message(message, w.admin)["body"].startswith("Bonjour")
    for attempt in (
        lambda: Message.objects.filter(pk=message.pk).update(body="réécrit"),
        lambda: Message.objects.filter(pk=message.pk).update(deleted_at=None),
        lambda: Message.objects.filter(pk=message.pk).delete(),
        lambda: Conversation.objects.filter(pk=conversation.pk).delete(),
    ):
        with pytest.raises(IntegrityError), transaction.atomic():
            attempt()


def test_only_participants_can_write_even_in_raw_sql(w):
    conversation = parent_teacher(w)
    with pytest.raises(IntegrityError), transaction.atomic():
        Message.objects.create(school=w.school, conversation=conversation, sender=w.other_parent, body="intrus")


def test_administration_reads_and_joins_visibly(w):
    conversation = parent_teacher(w)
    assert conversation in messaging.visible_conversations(w.admin)
    assert conversation not in messaging.visible_conversations(w.other_parent)
    messaging.send_message(conversation, actor=w.admin, body="L'administration suit cet échange.")
    assert conversation.participants.filter(membership=w.admin).exists()


# =============================================================================
# API, attachments, isolation
# =============================================================================


def test_api_conversation_flow_and_404_for_outsiders(w):
    parent = as_(w.parent)
    created = data(
        parent.post(
            "/api/v1/conversations/",
            {
                "conversation_type": "PARENT_TEACHER",
                "participants": [str(w.tm_member.pk)],
                "student": str(w.students[0].pk),
                "body": "Bonjour",
            },
            format="json",
        ),
        201,
    )
    cid = created["id"]
    teacher_view = data(as_(w.tm_member).get("/api/v1/conversations/"))
    assert [(c["id"], c["unread_count"]) for c in teacher_view] == [(cid, 1)]
    sent = data(as_(w.tm_member).post(f"/api/v1/conversations/{cid}/messages/", {"body": "Merci"}), 201)
    messages = data(parent.get(f"/api/v1/conversations/{cid}/messages/"))
    assert [m["body"] for m in messages] == ["Merci", "Bonjour"]
    data(parent.post(f"/api/v1/conversations/{cid}/read/"))
    assert data(parent.get(f"/api/v1/conversations/{cid}/"))["unread_count"] == 0
    for outsider in (w.other_parent, w.unverified, w.guardian, w.outsider_teacher):
        assert error(as_(outsider).get(f"/api/v1/conversations/{cid}/messages/"), 404)["code"] == "NOT_FOUND"
        assert data(as_(outsider).get("/api/v1/conversations/")) == []
    err = error(parent.delete(f"/api/v1/messages/{sent['id']}/"), 403)
    assert err["code"] == "PERMISSION_DENIED"


def test_cross_school_conversations_are_impossible(w):
    other = make_communication_world(SchoolFactory())
    conversation = parent_teacher(w)
    # Another school's admin: 404; a member of another school as participant: 404.
    assert error(as_(other.admin).get(f"/api/v1/conversations/{conversation.pk}/"), 404)["code"] == "NOT_FOUND"
    assert data(as_(other.admin).get("/api/v1/conversations/")) == []  # no conversation of school A
    assert not access.can_read_conversation(other.admin, conversation)  # the rule itself, not only the lookup
    response = as_(w.admin).post(
        "/api/v1/conversations/",
        {
            "conversation_type": "ADMINISTRATION",
            "participants": [str(other.parent.pk)],
            "body": "x",
        },
        format="json",
    )
    assert error(response, 404)["code"] == "NOT_FOUND"
    with pytest.raises(PermissionDenied):
        messaging.create_conversation(w.admin, conversation_type="ADMINISTRATION", participants=[other.parent])


def test_attachments_are_validated_private_and_permission_checked(w):
    conversation = parent_teacher(w)
    parent = as_(w.parent)
    url = f"/api/v1/conversations/{conversation.pk}/messages/"
    sent = data(
        parent.post(url, {"body": "Voici le certificat", "attachments": [pdf(), png()]}, format="multipart"), 201
    )
    assert [a["mime_type"] for a in sent["attachments"]] == ["application/pdf", "image/png"]
    stored = MessageAttachment.objects.get(mime_type="application/pdf")
    assert stored.stored_name != "doc.pdf" and "doc.pdf" not in stored.storage_path  # random physical name
    download = sent["attachments"][0]["download_url"]
    response = as_(w.tm_member).get(download)
    assert response.status_code == 200 and b"".join(response.streaming_content).startswith(b"%PDF-")
    assert response["Cache-Control"] == "private, no-store" and "attachment" in response["Content-Disposition"]
    for outsider in (w.other_parent, w.outsider_teacher, make_communication_world(SchoolFactory()).admin):
        assert as_(outsider).get(download).status_code == 404
    assert APIClient().get(download).status_code == 401
    # No public route serves the private storage.
    assert APIClient().get(f"/media/{stored.storage_path}").status_code == 404
    # Content is checked, not the name or the declared type.
    err = error(parent.post(url, {"body": "x", "attachments": [fake()]}, format="multipart"), 400)
    assert err["details"]["rule"] == "attachment_type_not_allowed"
    w.school.configuration.default_attachment_limit_mb = 0
    w.school.configuration.save()
    err = error(parent.post(url, {"body": "x", "attachments": [png()]}, format="multipart"), 400)
    assert err["details"]["rule"] == "attachment_too_large"
    # Attachment rows are append-only; a deleted message hides its files.
    with pytest.raises(IntegrityError), transaction.atomic():
        MessageAttachment.objects.filter(pk=stored.pk).delete()
    messaging.delete_message(stored.message, actor=w.parent)
    assert as_(w.tm_member).get(download).status_code == 404
    assert as_(w.admin).get(download).status_code == 200

"""Forum / announcements and complaints: computed membership, strict
permissions, moderation with reasons, workflow, cancellation without
deletion, immutable history, attachments, isolation."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.communication import complaints as comp
from apps.communication import forum
from apps.communication.models import (
    Complaint,
    ComplaintAttachment,
    ComplaintStatusHistory,
    ForumPost,
    Notification,
)

from .communication_world import make_communication_world, png, verified_parent
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


def rule(exc):
    return exc.value.code


# =============================================================================
# Forum
# =============================================================================


def class_space(w):
    return forum.create_space(
        w.school, actor=w.admin, name="Parents & profs 3e A", audience="CLASS", school_class=w.klass
    )


def test_space_membership_is_computed_from_existing_links(w):
    space = class_space(w)
    members = set(forum.members_of(space))
    assert {w.parent, w.other_parent, w.tm_member, w.tf_member, w.admin} <= members
    for outsider in (w.unverified, w.outsider_teacher, w.guardian, w.staff_member):
        assert outsider not in members and not forum.is_member(outsider, space)
    staff_space = forum.create_space(
        w.school, actor=w.admin, name="Équipe", audience="SCHOOL", roles=["TEACHER", "STAFF"]
    )
    assert forum.is_member(w.staff_member, staff_space) and not forum.is_member(w.parent, staff_space)
    with pytest.raises(PermissionDenied):
        forum.create_space(w.school, actor=w.tm_member, name="X", audience="SCHOOL", roles=["TEACHER"])


def test_announcements_are_admin_only_read_only_and_notify_the_space(w):
    space = class_space(w)
    with pytest.raises(PermissionDenied):
        forum.create_thread(space, actor=w.tm_member, title="Info", body="x", thread_type="ANNOUNCEMENT")
    thread = forum.create_thread(
        space, actor=w.admin, title="Sortie au musée", body="Vendredi 9h", thread_type="ANNOUNCEMENT"
    )
    recipients = set(Notification.objects.filter(notification_type="ANNOUNCEMENT").values_list("recipient", flat=True))
    assert {w.parent.pk, w.tm_member.pk} <= recipients
    assert not recipients & {w.unverified.pk, w.guardian.pk, w.admin.pk, w.outsider_teacher.pk}
    with pytest.raises(PermissionDenied):
        forum.add_post(thread, actor=w.parent, body="Question ?")


def test_discussion_moderation_and_history(w):
    space = class_space(w)
    thread = forum.create_thread(space, actor=w.parent, title="Covoiturage", body="Qui part de Bonapriso ?")
    post = forum.add_post(thread, actor=w.tm_member, body="Bonne idée")
    with pytest.raises(PermissionDenied):
        forum.add_post(thread, actor=w.guardian, body="x")
    with pytest.raises(PermissionDenied):
        forum.delete_post(post, actor=w.parent)  # not theirs
    with pytest.raises(ValidationError) as exc:
        forum.delete_post(post, actor=w.admin)  # moderation needs a reason
    assert rule(exc) == "reason_required"
    forum.delete_post(post, actor=w.admin, reason="Hors sujet")
    post.refresh_from_db()
    assert post.body == "Bonne idée" and post.deletion_reason == "Hors sujet"
    for attempt in (
        lambda: ForumPost.objects.filter(pk=post.pk).update(body="x"),
        lambda: ForumPost.objects.filter(pk=post.pk).delete(),
    ):
        with pytest.raises(IntegrityError), transaction.atomic():
            attempt()
    with pytest.raises(ValidationError):
        forum.set_thread_status(thread, actor=w.admin, status="LOCKED")
    forum.set_thread_status(thread, actor=w.admin, status="LOCKED", reason="Discussion close")
    with pytest.raises(ValidationError) as exc:
        forum.add_post(thread, actor=w.parent, body="encore")
    assert rule(exc) == "thread_locked"


def test_forum_api_isolation(w):
    space = class_space(w)
    thread = forum.create_thread(space, actor=w.admin, title="Rentrée", body="Infos", thread_type="ANNOUNCEMENT")
    assert [s["id"] for s in data(as_(w.parent).get("/api/v1/forum/spaces/"))] == [str(space.pk)]
    assert data(as_(w.guardian).get("/api/v1/forum/spaces/")) == []
    for outsider in (w.guardian, w.unverified, make_communication_world(SchoolFactory()).admin):
        assert error(as_(outsider).get(f"/api/v1/forum/threads/{thread.pk}/posts/"), 404)["code"] == "NOT_FOUND"
    posts = data(as_(w.parent).get(f"/api/v1/forum/threads/{thread.pk}/posts/"))
    assert [p["post_type"] for p in posts] == ["ANNOUNCEMENT"]
    err = error(as_(w.parent).post(f"/api/v1/forum/threads/{thread.pk}/posts/", {"body": "?"}), 403)
    assert err["code"] == "PERMISSION_DENIED"
    assert error(as_(w.parent).post("/api/v1/admin/forum/spaces/", {"name": "x", "audience": "SCHOOL"}), 403)


# =============================================================================
# Complaints
# =============================================================================


def parent_complaint(w, submit=True):
    return comp.create_complaint(
        w.parent,
        category="PEDAGOGY",
        subject="Notes de maths",
        description="La note semble erronée.",
        student=w.students[0],
        concerned_member=w.tm_member,
        submit=submit,
    )


def statuses(complaint):
    return list(complaint.history.order_by("created_at").values_list("old_status", "new_status"))


def test_complaint_workflow_with_reasons_and_history(w):
    complaint = parent_complaint(w)
    assert complaint.status == "OPEN" and complaint.conversation is not None
    participants = set(complaint.conversation.participants.values_list("membership_id", flat=True))
    assert {w.parent.pk, w.tm_member.pk, w.admin.pk} <= participants
    assert Notification.objects.filter(notification_type="COMPLAINT", recipient=w.tm_member).exists()
    comp.change_status(complaint, actor=w.tm_member, status="IN_PROGRESS")
    with pytest.raises(ValidationError) as exc:
        comp.change_status(complaint, actor=w.tm_member, status="RESOLVED")
    assert rule(exc) == "reason_required"
    comp.change_status(complaint, actor=w.tm_member, status="RESOLVED", reason="Note corrigée : 14/20")
    with pytest.raises(PermissionDenied):
        comp.change_status(complaint, actor=w.tm_member, status="CLOSED", reason="x")  # the author confirms
    comp.change_status(complaint, actor=w.parent, status="CLOSED", reason="Merci")
    complaint.refresh_from_db()
    assert complaint.status == "CLOSED" and complaint.resolved_at and complaint.closed_at
    assert statuses(complaint) == [
        (None, "DRAFT"),
        ("DRAFT", "OPEN"),
        ("OPEN", "IN_PROGRESS"),
        ("IN_PROGRESS", "RESOLVED"),
        ("RESOLVED", "CLOSED"),
    ]
    assert complaint.history.get(new_status="RESOLVED").comment == "Note corrigée : 14/20"
    # Final: nothing changes any more, even in raw SQL; no message in its thread.
    with pytest.raises(ValidationError) as exc:
        comp.change_status(complaint, actor=w.admin, status="IN_PROGRESS", reason="x")
    assert rule(exc) == "complaint_final"
    with pytest.raises(IntegrityError), transaction.atomic():
        Complaint.objects.filter(pk=complaint.pk).update(status="OPEN")


def test_cancellation_never_deletes(w):
    complaint = parent_complaint(w)
    with pytest.raises(ValidationError):
        comp.cancel_complaint(complaint, actor=w.parent)  # submitted: a reason is required
    comp.cancel_complaint(complaint, actor=w.parent, reason="Réglé par téléphone")
    complaint.refresh_from_db()
    assert complaint.status == "CANCELLED" and complaint.cancelled_at
    assert Complaint.objects.filter(pk=complaint.pk).exists()
    assert statuses(complaint)[-1] == ("OPEN", "CANCELLED")
    for attempt in (
        lambda: Complaint.objects.filter(pk=complaint.pk).delete(),
        lambda: ComplaintStatusHistory.objects.filter(complaint=complaint).delete(),
        lambda: ComplaintStatusHistory.objects.filter(complaint=complaint).update(comment="x"),
    ):
        with pytest.raises(IntegrityError), transaction.atomic():
            attempt()
    # Processed complaints cannot be cancelled by their author.
    second = parent_complaint(w)
    comp.change_status(second, actor=w.admin, status="IN_PROGRESS")
    with pytest.raises(PermissionDenied):
        comp.cancel_complaint(second, actor=w.parent, reason="x")
    comp.cancel_complaint(second, actor=w.admin, reason="Doublon")


def test_submitted_content_is_frozen_and_drafts_are_private(w):
    draft = parent_complaint(w, submit=False)
    assert not comp.can_view(w.admin, draft) and not comp.can_view(w.tm_member, draft)
    comp.update_draft(draft, actor=w.parent, subject="Notes de maths (T1)")
    comp.submit_complaint(draft, actor=w.parent)
    with pytest.raises(ValidationError) as exc:
        comp.update_draft(draft, actor=w.parent, subject="autre")
    assert rule(exc) == "complaint_not_draft"
    with pytest.raises(IntegrityError), transaction.atomic():
        Complaint.objects.filter(pk=draft.pk).update(description="réécrite")


def test_complaint_rights(w):
    no_right = verified_parent(w, w.students[0], can_submit_complaints=False)
    for actor, kwargs in (
        (no_right, {"student": w.students[0]}),
        (w.unverified, {"student": w.students[0]}),
        (w.other_parent, {"student": w.students[0]}),
        (w.guardian, {}),
        (w.parent, {"student": w.students[0], "concerned_member": w.outsider_teacher}),
        (w.outsider_teacher, {"student": w.students[0]}),
    ):
        with pytest.raises(PermissionDenied):
            comp.create_complaint(actor, category="OTHER", subject="s", description="d", **kwargs)
    # A teacher files about a pupil they teach, towards a verified parent.
    by_teacher = comp.create_complaint(
        w.tm_member,
        category="BEHAVIOR",
        subject="Bavardages",
        description="Répété",
        student=w.students[0],
        concerned_member=w.parent,
        submit=True,
    )
    assert comp.can_view(w.parent, by_teacher) and not comp.can_view(w.other_parent, by_teacher)
    # Staff: what is assigned to them.
    complaint = parent_complaint(w)
    assert not comp.can_view(w.staff_member, complaint)
    complaint = comp.assign(complaint, actor=w.admin, assignee=w.staff_member)
    assert comp.can_view(w.staff_member, complaint)
    comp.change_status(complaint, actor=w.staff_member, status="IN_PROGRESS")


def test_complaint_api_attachments_and_isolation(w):
    parent = as_(w.parent)
    created = data(
        parent.post(
            "/api/v1/complaints/",
            {
                "category": "PEDAGOGY",
                "subject": "Devoir",
                "description": "Consigne floue",
                "student": str(w.students[0].pk),
                "concerned_member": str(w.tm_member.pk),
                "submit": True,
            },
            format="json",
        ),
        201,
    )
    cid = created["id"]
    files = data(
        parent.post(f"/api/v1/complaints/{cid}/attachments/", {"attachments": [png()]}, format="multipart"), 201
    )
    download = files[0]["download_url"]
    assert as_(w.tm_member).get(download).status_code == 200
    other = make_communication_world(SchoolFactory())
    for outsider in (w.other_parent, w.staff_member, other.admin):
        assert error(as_(outsider).get(f"/api/v1/complaints/{cid}/"), 404)["code"] == "NOT_FOUND"
        assert as_(outsider).get(download).status_code == 404
    assert data(as_(w.other_parent).get("/api/v1/complaints/")) == []
    err = error(as_(w.tm_member).post(f"/api/v1/admin/complaints/{cid}/status/", {"status": "IN_PROGRESS"}), 403)
    assert err["code"] == "PERMISSION_DENIED"
    done = data(
        as_(w.admin).post(
            f"/api/v1/admin/complaints/{cid}/status/",
            {
                "assigned_to": str(w.staff_member.pk),
                "status": "RESOLVED",
                "reason": "Consigne reprécisée",
            },
        )
    )
    assert (done["status"], done["assigned_to"]) == ("RESOLVED", str(w.staff_member.pk))
    err = error(parent.post(f"/api/v1/complaints/{cid}/cancel/", {"reason": "x"}), 403)
    assert err["code"] == "PERMISSION_DENIED"
    data(parent.post(f"/api/v1/complaints/{cid}/status/", {"status": "CLOSED", "reason": "OK"}))
    err = error(
        parent.post(f"/api/v1/complaints/{cid}/attachments/", {"attachments": [png()]}, format="multipart"), 409
    )
    assert err["details"]["rule"] == "complaint_final"
    with pytest.raises(IntegrityError), transaction.atomic():
        ComplaintAttachment.objects.all().delete()

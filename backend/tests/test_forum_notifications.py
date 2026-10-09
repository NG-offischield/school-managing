"""Forum activity notifications (type FORUM): who is notified of a new
discussion and of a reply, through the one notification service (persisted,
idempotent, switchable, pushed live), and never across schools."""

import pytest
from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from django.core.exceptions import PermissionDenied

from apps.communication import forum
from apps.communication.models import Notification, NotificationPreference
from apps.communication.notifications import serialize

from .communication_world import make_communication_world
from .conftest import DB
from .factories import SchoolFactory
from .test_realtime import authenticated

pytestmark = DB


@pytest.fixture
def w(school):
    return make_communication_world(school)


def school_space(w, roles=("PARENT", "TEACHER", "STAFF")):
    return forum.create_space(w.school, actor=w.admin, name="Vie de l'école", audience="SCHOOL", roles=list(roles))


def class_space(w):
    return forum.create_space(w.school, actor=w.admin, name="3e A", audience="CLASS", school_class=w.klass)


def forum_recipients(event_key):
    return set(
        Notification.objects.filter(notification_type="FORUM", event_key=event_key).values_list("recipient", flat=True)
    )


def test_new_discussion_notifies_the_members_of_its_school_space(w):
    space = school_space(w, roles=("PARENT", "TEACHER"))
    thread = forum.create_thread(space, actor=w.parent, title="Covoiturage", body="Qui part de Bonapriso ?")
    recipients = forum_recipients(f"forum.thread:{thread.pk}")
    assert {w.other_parent.pk, w.tm_member.pk, w.outsider_teacher.pk, w.admin.pk} <= recipients
    # Not the author, not a role outside the space, not an unverified parent account, not a guardian.
    assert not recipients & {w.parent.pk, w.staff_member.pk, w.guardian.pk}
    notification = Notification.objects.get(recipient=w.admin, event_key=f"forum.thread:{thread.pk}")
    assert notification.payload == {"thread": str(thread.pk), "space": str(space.pk)}
    assert notification.title == "Nouveau sujet : Covoiturage"


def test_new_discussion_in_a_class_space_stays_in_the_class(w):
    space = class_space(w)
    thread = forum.create_thread(space, actor=w.tm_member, title="Devoirs", body="Pour lundi")
    recipients = forum_recipients(f"forum.thread:{thread.pk}")
    assert {w.parent.pk, w.other_parent.pk, w.tf_member.pk, w.admin.pk} <= recipients
    assert not recipients & {w.tm_member.pk, w.outsider_teacher.pk, w.unverified.pk, w.staff_member.pk, w.guardian.pk}


def test_a_reply_notifies_the_discussion_not_the_whole_school(w):
    space = school_space(w)
    thread = forum.create_thread(space, actor=w.parent, title="Kermesse", body="Des idées ?")
    forum.add_post(thread, actor=w.tm_member, body="Un stand de jeux")
    reply = forum.add_post(thread, actor=w.other_parent, body="Je peux aider")
    recipients = forum_recipients(f"forum.post:{reply.pk}")
    assert recipients == {w.parent.pk, w.tm_member.pk}  # the author and the people who posted
    # The rest of the space (staff, other teachers, administration) is not spammed by replies.
    assert not recipients & {w.staff_member.pk, w.outsider_teacher.pk, w.admin.pk, w.other_parent.pk}
    notification = Notification.objects.get(recipient=w.parent, event_key=f"forum.post:{reply.pk}")
    assert notification.payload["thread"] == str(thread.pk) and notification.payload["post"] == str(reply.pk)


def test_a_removed_post_or_a_lost_membership_stops_the_notifications(w):
    space = class_space(w)
    thread = forum.create_thread(space, actor=w.tm_member, title="Sortie", body="Vendredi")
    gone = forum.add_post(thread, actor=w.parent, body="Présent")
    forum.delete_post(gone, actor=w.parent)
    other = forum.add_post(thread, actor=w.other_parent, body="Aussi")
    assert forum_recipients(f"forum.post:{other.pk}") == {w.tm_member.pk}  # the removed poster is out
    # The teacher leaves the class (course deactivated): no more class notifications.
    w.course_maths.active = False
    w.course_maths.save(update_fields=["active"])
    later = forum.add_post(thread, actor=w.other_parent, body="Et samedi ?")
    assert w.tm_member.pk not in forum_recipients(f"forum.post:{later.pk}")


def test_announcements_keep_their_own_notification(w):
    space = school_space(w)
    thread = forum.create_thread(space, actor=w.admin, title="Rentrée", body="Lundi 8 h", thread_type="ANNOUNCEMENT")
    assert Notification.objects.filter(notification_type="ANNOUNCEMENT", event_key=f"announcement:{thread.pk}").exists()
    assert not Notification.objects.filter(notification_type="FORUM").exists()
    forum.add_post(thread, actor=w.admin, body="Précision : salle 12")
    assert not Notification.objects.filter(notification_type="FORUM").exists()


def test_forum_notifications_are_idempotent_and_switchable(w):
    space = school_space(w)
    NotificationPreference.objects.create(
        school=w.school, membership=w.tm_member, notification_type="FORUM", in_app_enabled=False
    )
    thread = forum.create_thread(space, actor=w.parent, title="Bibliothèque", body="Horaires ?")
    recipients = forum_recipients(f"forum.thread:{thread.pk}")
    assert w.tm_member.pk not in recipients and w.other_parent.pk in recipients
    before = Notification.objects.count()
    forum.notify_many(  # replaying the same event never notifies twice
        [w.other_parent],
        school=w.school,
        notification_type="FORUM",
        title="x",
        message="x",
        event_key=f"forum.thread:{thread.pk}",
    )
    assert Notification.objects.count() == before


def test_forum_activity_is_pushed_live_to_the_recipient_only(w):
    space = class_space(w)

    async def scenario():
        teacher, _ = await authenticated(w.tm_member)
        outsider, _ = await authenticated(w.outsider_teacher)
        thread = await database_sync_to_async(forum.create_thread)(
            space, actor=w.parent, title="Question", body="Le contrôle est-il reporté ?"
        )
        frame = await teacher.receive_json_from(timeout=5)
        assert frame["type"] == "notification" and frame["data"]["notification_type"] == "FORUM"
        assert frame["data"]["payload"]["thread"] == str(thread.pk)
        assert await outsider.receive_nothing(timeout=0.5)  # not in the class space
        await teacher.disconnect()
        await outsider.disconnect()

    async_to_sync(scenario)()


def test_missed_forum_notification_comes_back_with_get_and_sync(w):
    space = school_space(w)
    thread = forum.create_thread(space, actor=w.parent, title="Covoiturage", body="?")
    reply = forum.add_post(thread, actor=w.tm_member, body="Oui")
    rows = Notification.objects.filter(recipient=w.parent, notification_type="FORUM")
    assert [serialize(n)["payload"]["post"] for n in rows] == [str(reply.pk)]


def test_never_across_schools(w):
    other = make_communication_world(SchoolFactory())
    space = school_space(w)
    forum.create_thread(space, actor=w.parent, title="Interne", body="Seulement chez nous")
    assert not Notification.objects.filter(school=other.school, notification_type="FORUM").exists()
    assert not Notification.objects.filter(recipient__school=other.school, notification_type="FORUM").exists()
    with pytest.raises(PermissionDenied):
        forum.create_thread(space, actor=other.parent, title="Intrus", body="x")

"""Communication API (spec §6.11, ADR 0015).

Notifications (own only):
    GET  /notifications/              (?is_read=, ?type=, ?severity=)   paginated
    GET  /notifications/unread-count/
    POST /notifications/{id}/read/    POST /notifications/read-all/
    GET/PUT /notifications/preferences/
Private messaging:
    GET/POST /conversations/          (?type=, ?student=)
    GET  /conversations/{id}/         GET/POST /conversations/{id}/messages/ (multipart: attachments)
    POST /conversations/{id}/read/    POST /conversations/{id}/participants/ (administration)
    DELETE /messages/{id}/            own message only, hidden not destroyed
    GET  /teacher/contacts/           (?student=)  teacher only: the pupils I teach now and
                                      their verified parents (who I may write to)
Forum:
    GET  /forum/spaces/               POST /admin/forum/spaces/
    GET/POST /forum/threads/          (?space=)
    GET  /forum/threads/{id}/         GET/POST /forum/threads/{id}/posts/
    DELETE /forum/posts/{id}/         own post, or moderation with {reason}
    POST /admin/forum/threads/{id}/status/ {status, reason}
Complaints:
    GET/POST /complaints/             (?status=, ?category=)
    GET/PATCH /complaints/{id}/       (PATCH: draft only)
    POST /complaints/{id}/submit/ | /cancel/ {reason} | /status/ {status, reason}
    POST /complaints/{id}/attachments/  (multipart)
    POST /admin/complaints/{id}/status/ {status, reason, assigned_to?}
Administration directory (ADR 0023, read only):
    GET  /admin/communication/members/  (?search=, ?role=)   active members: id, name, roles
         (participants of a conversation, assignee of a complaint)
Private attachments (permission checked, never a public URL):
    GET  /attachments/message/{id}/download/   GET /attachments/complaint/{id}/download/

Everything is resolved inside the caller's school; what the caller may not
see answers 404 exactly like what does not exist.
"""

from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.urls import path
from django.utils.dateparse import parse_datetime
from rest_framework import generics, serializers, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.models import SchoolClass
from apps.accounts.models import SchoolMembership
from apps.people.models import Student
from common.permissions import HasSchoolRole
from common.tenancy import scope_to_current_school
from common.views import SchoolScopedMixin

from . import access, attachments, complaints, forum, messaging, notifications
from .models import (
    Complaint,
    ComplaintAttachment,
    ComplaintCategory,
    ComplaintPriority,
    ComplaintStatus,
    Conversation,
    ConversationType,
    ForumPost,
    ForumSpace,
    ForumThread,
    Message,
    MessageAttachment,
    Notification,
    NotificationPreference,
    NotificationType,
    SpaceAudience,
    ThreadStatus,
    ThreadType,
)

ADMIN = {"ADMIN", "SUPER_ADMIN"}
PARSERS = [JSONParser, MultiPartParser, FormParser]


def scoped(model, pk, request):
    return get_object_or_404(scope_to_current_school(model.objects.all(), request), pk=pk)


def optional_scoped(model, pk, request):
    return scoped(model, pk, request) if pk else None


def files_of(request):
    return request.FILES.getlist("attachments") if hasattr(request, "FILES") else []


class AdminMixin(SchoolScopedMixin):
    permission_classes = [HasSchoolRole]
    required_roles = ADMIN


# =============================================================================
# Notifications
# =============================================================================


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = [
            "id",
            "notification_type",
            "severity",
            "title",
            "message",
            "payload",
            "is_read",
            "read_at",
            "created_at",
        ]

    def to_representation(self, instance):
        """Same fields; a system title / message in the request's language."""
        data = super().to_representation(instance)
        data["title"], data["message"] = notifications.localized(instance)
        return data


class NotificationList(SchoolScopedMixin, generics.ListAPIView):
    queryset = Notification.objects.order_by("-created_at")
    serializer_class = NotificationSerializer

    def restrict(self, queryset):
        queryset = queryset.filter(recipient=self.membership())  # explicit recipient only
        params = self.request.query_params
        if params.get("is_read") in ("true", "false"):
            queryset = queryset.filter(is_read=params["is_read"] == "true")
        if params.get("type"):
            queryset = queryset.filter(notification_type=params["type"])
        if params.get("severity"):
            queryset = queryset.filter(severity=params["severity"])
        return queryset


class NotificationUnreadCount(SchoolScopedMixin, APIView):
    def get(self, request):
        return Response({"unread": notifications.unread_count(self.membership())})


class NotificationRead(SchoolScopedMixin, APIView):
    def post(self, request, pk):
        notification = get_object_or_404(Notification.objects.filter(recipient=self.membership()), pk=pk)
        return Response(NotificationSerializer(notifications.mark_read(notification, actor=self.membership())).data)


class NotificationReadAll(SchoolScopedMixin, APIView):
    def post(self, request):
        return Response({"marked": notifications.mark_all_read(self.membership())})


class PreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = ["notification_type", "in_app_enabled", "push_enabled"]


class PreferenceInput(serializers.Serializer):
    notification_type = serializers.ChoiceField(choices=NotificationType.choices)
    in_app_enabled = serializers.BooleanField(required=False)
    push_enabled = serializers.BooleanField(required=False)


class NotificationPreferences(SchoolScopedMixin, APIView):
    def get(self, request):
        member = self.membership()
        stored = {p.notification_type: p for p in NotificationPreference.objects.filter(membership=member)}
        return Response(
            [
                {
                    "notification_type": kind,
                    "in_app_enabled": notifications.preference(member, kind)[0],
                    "push_enabled": stored[kind].push_enabled if kind in stored else True,
                    "mandatory": kind in notifications.MANDATORY_TYPES,
                }
                for kind in NotificationType.values
            ]
        )

    def put(self, request):
        data = PreferenceInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        pref = notifications.set_preference(
            self.membership(),
            v["notification_type"],
            in_app_enabled=v.get("in_app_enabled"),
            push_enabled=v.get("push_enabled"),
        )
        return Response(PreferenceSerializer(pref).data)


# =============================================================================
# Conversations and messages
# =============================================================================


def conversation_data(conversation, viewer):
    participants = conversation.participants.select_related("membership__user")
    return {
        "id": str(conversation.pk),
        "conversation_type": conversation.conversation_type,
        "title": conversation.title,
        "student": str(conversation.student_id) if conversation.student_id else None,
        "active": conversation.active,
        "last_message_at": conversation.last_message_at,
        "participants": [
            {"member": str(p.membership_id), "name": p.membership.user.full_name, "active": p.active}
            for p in participants
        ],
        "unread_count": messaging.unread_messages(conversation, viewer),
        "is_participant": access.participant(viewer, conversation) is not None,
    }


class ConversationListSerializer(serializers.BaseSerializer):
    def to_representation(self, instance):
        return conversation_data(instance, self.context["viewer"])


class ConversationInput(serializers.Serializer):
    conversation_type = serializers.ChoiceField(
        choices=[ConversationType.ADMINISTRATION, ConversationType.PARENT_TEACHER]
    )
    participants = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    student = serializers.UUIDField(required=False, allow_null=True)
    title = serializers.CharField(max_length=160, required=False, allow_blank=True)
    body = serializers.CharField(required=False, allow_blank=True)
    client_id = serializers.CharField(max_length=64, required=False)


class Conversations(SchoolScopedMixin, generics.ListAPIView):
    parser_classes = PARSERS
    serializer_class = ConversationListSerializer

    def get_queryset(self):
        queryset = messaging.visible_conversations(self.membership()).order_by("-last_message_at", "-created_at")
        if self.request.query_params.get("type"):
            queryset = queryset.filter(conversation_type=self.request.query_params["type"])
        student = self.uuid_param("student")
        return queryset.filter(student_id=student) if student else queryset

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "viewer": self.membership()}

    def post(self, request):
        data = ConversationInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        conversation, created = messaging.create_conversation(
            self.membership(),
            conversation_type=v["conversation_type"],
            participants=[scoped(SchoolMembership, pk, request) for pk in v["participants"]],
            student=optional_scoped(Student, v.get("student"), request),
            title=v.get("title"),
            body=v.get("body") or None,
            files=files_of(request),
            client_id=v.get("client_id"),
        )
        return Response(
            conversation_data(conversation, self.membership()),
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class ConversationMixin(SchoolScopedMixin):
    def conversation(self, pk):
        conversation = scoped(Conversation, pk, self.request)
        if not access.can_read_conversation(self.membership(), conversation):
            raise Http404
        return conversation


class ConversationDetail(ConversationMixin, APIView):
    def get(self, request, pk):
        return Response(conversation_data(self.conversation(pk), self.membership()))


class MessageListSerializer(serializers.BaseSerializer):
    def to_representation(self, instance):
        return messaging.serialize_message(instance, self.context["viewer"])


class MessageInput(serializers.Serializer):
    body = serializers.CharField()
    client_id = serializers.CharField(max_length=64, required=False)


class ConversationMessages(ConversationMixin, generics.ListAPIView):
    parser_classes = PARSERS
    serializer_class = MessageListSerializer

    def get_queryset(self):
        conversation = self.conversation(self.kwargs["pk"])
        queryset = (
            Message.objects.filter(conversation=conversation)
            .select_related("sender__user")
            .prefetch_related("attachments")
        )
        since = parse_datetime(self.request.query_params.get("since") or "")
        if since:
            queryset = queryset.filter(created_at__gt=since)
        return queryset.order_by("-created_at")

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "viewer": self.membership()}

    def post(self, request, pk):
        data = MessageInput(data=request.data)
        data.is_valid(raise_exception=True)
        message, created = messaging.send_message(
            self.conversation(pk),
            actor=self.membership(),
            body=data.validated_data["body"],
            files=files_of(request),
            client_id=data.validated_data.get("client_id"),
        )
        return Response(
            messaging.serialize_message(message, self.membership()),
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class ConversationRead(ConversationMixin, APIView):
    def post(self, request, pk):
        participant = messaging.mark_read(self.conversation(pk), actor=self.membership())
        return Response({"last_read_at": participant.last_read_at})


class ParticipantInput(serializers.Serializer):
    member = serializers.UUIDField()


class ConversationParticipants(ConversationMixin, APIView):
    def post(self, request, pk):
        data = ParticipantInput(data=request.data)
        data.is_valid(raise_exception=True)
        conversation = self.conversation(pk)
        messaging.add_participant(
            conversation, scoped(SchoolMembership, data.validated_data["member"], request), actor=self.membership()
        )
        return Response(conversation_data(conversation, self.membership()), status=status.HTTP_201_CREATED)


class MessageDelete(SchoolScopedMixin, APIView):
    def delete(self, request, pk):
        message = scoped(Message, pk, request)
        if not access.can_read_conversation(self.membership(), message.conversation):
            raise Http404
        message = messaging.delete_message(message, actor=self.membership())
        return Response(messaging.serialize_message(message, self.membership()))


# =============================================================================
# Forum
# =============================================================================


class SpaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ForumSpace
        fields = ["id", "name", "description", "audience", "roles", "school_class", "announcements_only", "active"]


class ForumSpaces(SchoolScopedMixin, APIView):
    def get(self, request):
        return Response(SpaceSerializer(forum.visible_spaces(self.membership()), many=True).data)


class SpaceInput(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    description = serializers.CharField(required=False, allow_blank=True)
    audience = serializers.ChoiceField(choices=SpaceAudience.choices)
    roles = serializers.ListField(child=serializers.CharField(max_length=30), required=False, default=list)
    school_class = serializers.UUIDField(required=False, allow_null=True)
    announcements_only = serializers.BooleanField(default=False)


class AdminForumSpaces(AdminMixin, APIView):
    def post(self, request):
        data = SpaceInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        space = forum.create_space(
            self.membership().school,
            actor=self.membership(),
            name=v["name"],
            audience=v["audience"],
            roles=v["roles"],
            school_class=optional_scoped(SchoolClass, v.get("school_class"), request),
            announcements_only=v["announcements_only"],
            description=v.get("description") or None,
        )
        return Response(SpaceSerializer(space).data, status=status.HTTP_201_CREATED)


class ThreadSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="created_by.user.full_name", read_only=True)

    class Meta:
        model = ForumThread
        fields = [
            "id",
            "space",
            "title",
            "thread_type",
            "status",
            "status_reason",
            "created_by",
            "author_name",
            "created_at",
            "last_post_at",
        ]


class ThreadInput(serializers.Serializer):
    space = serializers.UUIDField()
    title = serializers.CharField(max_length=200)
    body = serializers.CharField()
    thread_type = serializers.ChoiceField(choices=ThreadType.choices, default=ThreadType.GENERAL)


class ForumMixin(SchoolScopedMixin):
    def space(self, pk):
        space = scoped(ForumSpace, pk, self.request)
        if not forum.is_member(self.membership(), space):
            raise Http404
        return space

    def thread(self, pk):
        thread = scoped(ForumThread, pk, self.request)
        self.space(thread.space_id)
        return thread


class ForumThreads(ForumMixin, generics.ListAPIView):
    serializer_class = ThreadSerializer

    def get_queryset(self):
        spaces = [s.pk for s in forum.visible_spaces(self.membership())]
        queryset = ForumThread.objects.filter(school=self.membership().school, space_id__in=spaces).select_related(
            "created_by__user"
        )
        space = self.uuid_param("space")
        return queryset.filter(space_id=space) if space else queryset

    def post(self, request):
        data = ThreadInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        thread = forum.create_thread(
            self.space(v["space"]),
            actor=self.membership(),
            title=v["title"],
            body=v["body"],
            thread_type=v["thread_type"],
        )
        return Response(ThreadSerializer(thread).data, status=status.HTTP_201_CREATED)


class ForumThreadDetail(ForumMixin, APIView):
    def get(self, request, pk):
        return Response(ThreadSerializer(self.thread(pk)).data)


class PostSerializer(serializers.BaseSerializer):
    def to_representation(self, post):
        hidden = post.deleted_at is not None and not access.is_admin(self.context["viewer"])
        return {
            "id": str(post.pk),
            "thread": str(post.thread_id),
            "author": str(post.author_id),
            "author_name": post.author.user.full_name,
            "post_type": post.post_type,
            "body": None if hidden else post.body,
            "created_at": post.created_at,
            "deleted_at": post.deleted_at,
            "deletion_reason": None if hidden else post.deletion_reason,
        }


class PostInput(serializers.Serializer):
    body = serializers.CharField()


class ForumThreadPosts(ForumMixin, generics.ListAPIView):
    serializer_class = PostSerializer

    def get_queryset(self):
        thread = self.thread(self.kwargs["pk"])
        return ForumPost.objects.filter(thread=thread).select_related("author__user").order_by("created_at")

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "viewer": self.membership()}

    def post(self, request, pk):
        data = PostInput(data=request.data)
        data.is_valid(raise_exception=True)
        post = forum.add_post(self.thread(pk), actor=self.membership(), body=data.validated_data["body"])
        return Response(
            PostSerializer(post, context={"viewer": self.membership()}).data, status=status.HTTP_201_CREATED
        )


class ReasonInput(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class ForumPostDelete(ForumMixin, APIView):
    def delete(self, request, pk):
        post = scoped(ForumPost, pk, request)
        self.thread(post.thread_id)
        data = ReasonInput(data=request.data)
        data.is_valid(raise_exception=True)
        post = forum.delete_post(post, actor=self.membership(), reason=data.validated_data.get("reason"))
        return Response(PostSerializer(post, context={"viewer": self.membership()}).data)


class ThreadStatusInput(serializers.Serializer):
    status = serializers.ChoiceField(choices=ThreadStatus.choices)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=1000)


class AdminThreadStatus(AdminMixin, APIView):
    def post(self, request, pk):
        data = ThreadStatusInput(data=request.data)
        data.is_valid(raise_exception=True)
        thread = forum.set_thread_status(
            scoped(ForumThread, pk, request),
            actor=self.membership(),
            status=data.validated_data["status"],
            reason=data.validated_data.get("reason"),
        )
        return Response(ThreadSerializer(thread).data)


# =============================================================================
# Complaints
# =============================================================================


def complaint_data(complaint, *, full=False):
    data = {
        "id": str(complaint.pk),
        "author": str(complaint.author_id),
        "student": str(complaint.student_id) if complaint.student_id else None,
        "concerned_member": str(complaint.concerned_member_id) if complaint.concerned_member_id else None,
        "include_administration": complaint.include_administration,
        "category": complaint.category,
        "subject": complaint.subject,
        "description": complaint.description,
        "priority": complaint.priority,
        "status": complaint.status,
        "assigned_to": str(complaint.assigned_to_id) if complaint.assigned_to_id else None,
        "conversation": str(complaint.conversation_id) if complaint.conversation_id else None,
        "created_at": complaint.created_at,
        "submitted_at": complaint.submitted_at,
        "resolved_at": complaint.resolved_at,
        "closed_at": complaint.closed_at,
        "cancelled_at": complaint.cancelled_at,
    }
    if full:
        data["history"] = [
            {
                "old_status": h.old_status,
                "new_status": h.new_status,
                "changed_by": str(h.changed_by_id),
                "comment": h.comment,
                "at": h.created_at,
            }
            for h in complaint.history.all()
        ]
        data["attachments"] = [attachments.serialize(a, "complaint") for a in complaint.attachments.all()]
    return data


class ComplaintListSerializer(serializers.BaseSerializer):
    def to_representation(self, instance):
        return complaint_data(instance)


class ComplaintInput(serializers.Serializer):
    category = serializers.ChoiceField(choices=ComplaintCategory.choices)
    subject = serializers.CharField(max_length=200)
    description = serializers.CharField()
    student = serializers.UUIDField(required=False, allow_null=True)
    concerned_member = serializers.UUIDField(required=False, allow_null=True)
    include_administration = serializers.BooleanField(default=True)
    priority = serializers.ChoiceField(choices=ComplaintPriority.choices, default=ComplaintPriority.NORMAL)
    submit = serializers.BooleanField(default=False)


class Complaints(SchoolScopedMixin, generics.ListAPIView):
    serializer_class = ComplaintListSerializer

    def get_queryset(self):
        queryset = complaints.visible_complaints(self.membership()).order_by("-created_at")
        for param in ("status", "category"):
            if self.request.query_params.get(param):
                queryset = queryset.filter(**{param: self.request.query_params[param]})
        return queryset

    def post(self, request):
        data = ComplaintInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        complaint = complaints.create_complaint(
            self.membership(),
            category=v["category"],
            subject=v["subject"],
            description=v["description"],
            student=optional_scoped(Student, v.get("student"), request),
            concerned_member=optional_scoped(SchoolMembership, v.get("concerned_member"), request),
            include_administration=v["include_administration"],
            priority=v["priority"],
            submit=v["submit"],
        )
        return Response(complaint_data(complaint, full=True), status=status.HTTP_201_CREATED)


class ComplaintMixin(SchoolScopedMixin):
    def complaint(self, pk):
        complaint = scoped(Complaint, pk, self.request)
        if not complaints.can_view(self.membership(), complaint):
            raise Http404
        return complaint


class DraftInput(serializers.Serializer):
    subject = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(required=False)
    category = serializers.ChoiceField(choices=ComplaintCategory.choices, required=False)
    priority = serializers.ChoiceField(choices=ComplaintPriority.choices, required=False)


class ComplaintDetail(ComplaintMixin, APIView):
    def get(self, request, pk):
        return Response(complaint_data(self.complaint(pk), full=True))

    def patch(self, request, pk):
        data = DraftInput(data=request.data)
        data.is_valid(raise_exception=True)
        complaint = complaints.update_draft(self.complaint(pk), actor=self.membership(), **data.validated_data)
        return Response(complaint_data(complaint, full=True))


class ComplaintSubmit(ComplaintMixin, APIView):
    def post(self, request, pk):
        complaint = complaints.submit_complaint(self.complaint(pk), actor=self.membership())
        return Response(complaint_data(complaint, full=True))


class ComplaintCancel(ComplaintMixin, APIView):
    def post(self, request, pk):
        data = ReasonInput(data=request.data)
        data.is_valid(raise_exception=True)
        complaint = complaints.cancel_complaint(
            self.complaint(pk), actor=self.membership(), reason=data.validated_data.get("reason")
        )
        return Response(complaint_data(complaint, full=True))


class StatusInput(serializers.Serializer):
    status = serializers.ChoiceField(choices=ComplaintStatus.choices)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class ComplaintStatusChange(ComplaintMixin, APIView):
    def post(self, request, pk):
        data = StatusInput(data=request.data)
        data.is_valid(raise_exception=True)
        complaint = complaints.change_status(
            self.complaint(pk),
            actor=self.membership(),
            status=data.validated_data["status"],
            reason=data.validated_data.get("reason"),
        )
        return Response(complaint_data(complaint, full=True))


class AdminStatusInput(StatusInput):
    status = serializers.ChoiceField(choices=ComplaintStatus.choices, required=False)
    assigned_to = serializers.UUIDField(required=False, allow_null=True)


class AdminComplaintStatus(AdminMixin, APIView):
    """Spec §6.11: administrative workflow update (status and/or assignee)."""

    def post(self, request, pk):
        data = AdminStatusInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        complaint = scoped(Complaint, pk, request)
        if not complaints.can_view(self.membership(), complaint):
            raise Http404
        if v.get("assigned_to"):
            complaint = complaints.assign(
                complaint,
                actor=self.membership(),
                assignee=scoped(SchoolMembership, v["assigned_to"], request),
                reason=v.get("reason"),
            )
        if v.get("status"):
            complaint = complaints.change_status(
                complaint, actor=self.membership(), status=v["status"], reason=v.get("reason")
            )
        return Response(complaint_data(complaint, full=True))


class ComplaintAttachments(ComplaintMixin, APIView):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        created = complaints.add_attachments(self.complaint(pk), actor=self.membership(), files=files_of(request))
        return Response([attachments.serialize(a, "complaint") for a in created], status=status.HTTP_201_CREATED)


# =============================================================================
# Teacher contacts (parent–teacher conversations)
# =============================================================================


class TeacherContacts(SchoolScopedMixin, APIView):
    """Mirror of GET /parents/children/{id}/teachers/: the pupils a teacher
    teaches now, each with the verified parents he or she may write to. No
    e-mail or phone; no search over the school's parents."""

    permission_classes = [HasSchoolRole]
    required_roles = {"TEACHER"}

    def get(self, request):
        links = access.teacher_contacts(self.membership())
        student = self.uuid_param("student")
        if student:
            links = links.filter(student_id=student)
        pupils = {}
        for link in links:
            entry = pupils.setdefault(
                link.student_id,
                {"student": str(link.student_id), "name": link.student.full_name, "parents": []},
            )
            member = link.parent.membership
            entry["parents"].append(
                {"member": str(member.pk), "name": member.user.full_name, "relationship": link.relationship_type}
            )
        return Response(list(pupils.values()))


# =============================================================================
# Administration directory (ADR 0023)
# =============================================================================


class MemberSerializer(serializers.BaseSerializer):
    def to_representation(self, membership):
        return {
            "id": str(membership.pk),
            "name": membership.user.full_name,
            "roles": sorted(
                r.role.code
                for r in membership.membership_roles.all()
                if r.active  # prefetched
            ),
        }


class AdminMembers(AdminMixin, generics.ListAPIView):
    """Active members of the school (no e-mail, phone or other personal data)."""

    serializer_class = MemberSerializer

    def get_queryset(self):
        queryset = (
            notifications.active_members(self.membership().school)
            .select_related("user")
            .prefetch_related("membership_roles__role")
            .order_by("user__last_name", "user__first_name", "id")
        )
        params = self.request.query_params
        search = (params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(Q(user__first_name__icontains=search) | Q(user__last_name__icontains=search))
        if params.get("role"):
            queryset = queryset.filter(
                membership_roles__active=True, membership_roles__role__code=params["role"]
            ).distinct()
        return queryset


# =============================================================================
# Private attachment download
# =============================================================================


class AttachmentDownload(SchoolScopedMixin, APIView):
    """Streams a private file after checking the permission on the object
    it belongs to. Not visible = 404 (no hint that the file exists)."""

    def get(self, request, kind, pk):
        member = self.membership()
        if kind == "message":
            attachment = scoped(MessageAttachment, pk, request)
            message = attachment.message
            if not access.can_read_conversation(member, message.conversation):
                raise Http404
            if message.deleted_at is not None and not access.is_admin(member):
                raise Http404
        elif kind == "complaint":
            attachment = scoped(ComplaintAttachment, pk, request)
            if not complaints.can_view(member, attachment.complaint):
                raise Http404
        else:
            raise Http404
        response = FileResponse(
            attachments.open_file(attachment),
            as_attachment=True,
            filename=attachment.original_name,
            content_type=attachment.mime_type,
        )
        response["Cache-Control"] = "private, no-store"
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return response


urlpatterns = [
    path("notifications/", NotificationList.as_view()),
    path("notifications/unread-count/", NotificationUnreadCount.as_view()),
    path("notifications/read-all/", NotificationReadAll.as_view()),
    path("notifications/preferences/", NotificationPreferences.as_view()),
    path("notifications/<uuid:pk>/read/", NotificationRead.as_view()),
    path("conversations/", Conversations.as_view()),
    path("conversations/<uuid:pk>/", ConversationDetail.as_view()),
    path("conversations/<uuid:pk>/messages/", ConversationMessages.as_view()),
    path("conversations/<uuid:pk>/read/", ConversationRead.as_view()),
    path("conversations/<uuid:pk>/participants/", ConversationParticipants.as_view()),
    path("messages/<uuid:pk>/", MessageDelete.as_view()),
    path("forum/spaces/", ForumSpaces.as_view()),
    path("admin/forum/spaces/", AdminForumSpaces.as_view()),
    path("forum/threads/", ForumThreads.as_view()),
    path("forum/threads/<uuid:pk>/", ForumThreadDetail.as_view()),
    path("forum/threads/<uuid:pk>/posts/", ForumThreadPosts.as_view()),
    path("forum/posts/<uuid:pk>/", ForumPostDelete.as_view()),
    path("admin/forum/threads/<uuid:pk>/status/", AdminThreadStatus.as_view()),
    path("complaints/", Complaints.as_view()),
    path("complaints/<uuid:pk>/", ComplaintDetail.as_view()),
    path("complaints/<uuid:pk>/submit/", ComplaintSubmit.as_view()),
    path("complaints/<uuid:pk>/cancel/", ComplaintCancel.as_view()),
    path("complaints/<uuid:pk>/status/", ComplaintStatusChange.as_view()),
    path("complaints/<uuid:pk>/attachments/", ComplaintAttachments.as_view()),
    path("admin/complaints/<uuid:pk>/status/", AdminComplaintStatus.as_view()),
    path("admin/communication/members/", AdminMembers.as_view()),
    path("teacher/contacts/", TeacherContacts.as_view()),
    path("attachments/<str:kind>/<uuid:pk>/download/", AttachmentDownload.as_view()),
]

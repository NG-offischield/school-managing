"""Django admin registrations — developer tooling only (read-only: every
change goes through the services, which check rights and keep history)."""

from django.contrib import admin

from . import models


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


for model in (
    models.Notification,
    models.NotificationDelivery,
    models.NotificationPreference,
    models.Conversation,
    models.ConversationParticipant,
    models.Message,
    models.MessageAttachment,
    models.ForumSpace,
    models.ForumThread,
    models.ForumPost,
    models.Complaint,
    models.ComplaintStatusHistory,
    models.ComplaintAttachment,
):
    admin.site.register(model, ReadOnlyAdmin)

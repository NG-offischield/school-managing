from django.apps import AppConfig


class CommunicationConfig(AppConfig):
    """Notifications, private messaging, forum, complaints, private
    attachments, real-time WebSocket (spec 4.6, 6.11, ADR 0015)."""

    name = "apps.communication"
    label = "communication"
    verbose_name = "Communication"

    def ready(self):
        # Listen to the source domains (attendance, planning, finance,
        # payroll, gradebook) without them importing this app.
        from . import events

        events.connect()

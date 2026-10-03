"""Real-time fan-out through the EXISTING Channels layer (ADR 0015).

Groups (one per audience, never per school-wide broadcast):
    member.<membership uuid hex>        a membership's own events (notifications)
    conversation.<conversation hex>     events of one conversation

Events are sent only AFTER the business transaction commits
(transaction.on_commit): a rolled-back message or notification is never
pushed. A push failure (Redis down) is logged and ignored — the data is in
PostgreSQL and the client resynchronises on reconnection ("sync" frame).
The consumer re-checks permissions before forwarding anything (consumers.py).
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

logger = logging.getLogger(__name__)


def member_group(membership_id):
    return f"member.{membership_id.hex}"


def conversation_group(conversation_id):
    return f"conversation.{conversation_id.hex}"


def _send(group, event):
    def push():
        try:
            layer = get_channel_layer()
            if layer is not None:
                async_to_sync(layer.group_send)(group, event)
        except Exception:  # pragma: no cover - transport failure only
            logger.exception("Real-time push failed for group %s", group)

    transaction.on_commit(push)


def to_member(membership_id, frame):
    """`frame` = what the client receives (JSON-serialisable dict)."""
    _send(member_group(membership_id), {"type": "member.event", "frame": frame})


def to_conversation(conversation_id, frame):
    _send(
        conversation_group(conversation_id),
        {"type": "conversation.event", "conversation": str(conversation_id), "frame": frame},
    )

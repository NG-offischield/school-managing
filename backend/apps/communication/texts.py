"""Texts of the SYSTEM notifications, rendered in the reader's language (ADR 0007).

A system notification is stored with a language-neutral description of its
text (`Notification.text`): a key of TEXTS and its parameters. The title and
message are rendered when READ, in the language of the request
(Accept-Language) or of the real-time connection; `title` / `message` also
keep the French rendering made at creation (default language, compatibility,
rows created before this module: rendered as stored).

Three kinds of content, never mixed up:
- system wording ("Paiement confirmé", "est absent(e) le") -> translated here;
- business data (names, references, amounts, dates, plan or period names)
  -> parameters, inserted as they are, never translated;
- what people wrote (messages, forum posts, complaints, announcements)
  -> passed as plain strings to notify(): stored and shown untouched.

Source strings are English (Django convention, ADR 0007); the French texts
are in locale/fr/LC_MESSAGES/django.po. Dates are formatted dd/mm/yyyy in
both languages (the clients' convention); amounts as the finance module does.
"""

from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy, override, pgettext_lazy

# key -> template (a plural template picks its form from the parameter `n`)
TEXTS = {
    # attendance (parents)
    "attendance.late.title": _("Late arrival — %(student)s"),
    "attendance.absent.title": _("Absence — %(student)s"),
    "attendance.late.message": _("%(student)s arrived %(minutes)s min late on %(date)s."),
    "attendance.absent.message": _("%(student)s is absent on %(date)s."),
    # convocations (the convened parent)
    "convocation.scheduled.title": _("Meeting notice — %(student)s"),
    "convocation.status.title": _("Meeting notice: %(status)s"),
    "convocation.scheduled.message": _("You are asked to attend on %(date)s at %(time)s."),
    "convocation.status.message": _("The status of your meeting notice has changed."),
    # timetable changes (teachers / parents of the class)
    "schedule.teacher.title": _("Schedule: %(change)s"),
    "schedule.parent.title": _("Timetable: %(change)s"),
    "schedule.message.dated": _("%(change)s on %(date)s."),
    "schedule.message": _("%(change)s."),
    # payments
    "payment.confirmed.title": _("Payment confirmed"),
    "payment.failed.title": _("Payment not completed"),
    "payment.payer.message": _("Payment %(reference)s of %(amount)s %(currency)s: %(status)s."),
    "payment.admin.title": _("Payment confirmed — %(about)s — %(amount)s"),
    "payment.admin.invoices": ngettext_lazy("invoice %(numbers)s", "invoices %(numbers)s", "n"),
    "payment.admin.free": _("free payment"),
    "payment.admin.message": _(
        "%(student)s: payment %(reference)s by mobile wallet, confirmed on %(date)s at %(time)s."
    ),
    "refund.title": _("Refund completed"),
    "refund.message": _("%(amount)s %(currency)s refunded on payment %(reference)s."),
    # payroll (the employee)
    "payroll.paid.title": _("Pay paid out"),
    "payroll.approved.title": _("Pay approved"),
    "payroll.paid.message": _("%(period)s: %(amount)s %(currency)s paid out."),
    "payroll.approved.message": _("%(period)s: %(amount)s %(currency)s approved by the administration."),
    # report cards (parents)
    "report_card.title": _("Report card available — %(student)s"),
    "report_card.message": _("The report card for %(period)s is available."),
    # complaints: the subject / description / comments are the people's own words
    "complaint.new.title": _("New complaint: %(subject)s"),
    "complaint.status.title": _("Complaint: %(status)s"),
    "complaint.cancelled.title": _("Complaint cancelled"),
    "complaint.assigned.title": _("Complaint assigned"),
    # forum / messaging: titles and bodies are the people's own words
    "forum.thread.title": _("New topic: %(title)s"),
    "forum.reply.title": _("Reply: %(title)s"),
    "forum.excerpt": _("%(author)s: %(body)s"),
    "message.title": _("Message from %(sender)s"),
    # school plans
    "plan.published.title": _("Map published: %(title)s"),
    "plan.updated.title": _("Map updated: %(title)s"),
    "plan.version.located": _("%(where)s — version %(number)s."),
    "plan.version": _("Version %(number)s."),
}

# Status labels shown inside a notification (the models keep their own labels);
# the context tells the translator which noun they agree with.
LABELS = {
    "convocation_status": {
        "SCHEDULED": pgettext_lazy("convocation_status", "Scheduled"),
        "HELD": pgettext_lazy("convocation_status", "Held"),
        "MISSED": pgettext_lazy("convocation_status", "Parent absent"),
        "CANCELLED": pgettext_lazy("convocation_status", "Cancelled"),
    },
    "change_type": {
        "SLOT_CREATED": pgettext_lazy("change_type", "New weekly slot"),
        "SLOT_ENDED": pgettext_lazy("change_type", "Weekly slot ended"),
        "SLOT_ARCHIVED": pgettext_lazy("change_type", "Weekly slot withdrawn"),
        "SESSION_CREATED": pgettext_lazy("change_type", "Exceptional lesson"),
        "SESSION_CANCELLED": pgettext_lazy("change_type", "Lesson cancelled"),
        "SESSION_MOVED": pgettext_lazy("change_type", "Lesson moved"),
        "SESSION_ROOM_CHANGED": pgettext_lazy("change_type", "Room changed"),
        "TEACHER_SUBSTITUTED": pgettext_lazy("change_type", "Substitute teacher"),
        "TEACHER_RESTORED": pgettext_lazy("change_type", "Usual teacher back"),
        "SESSIONS_SWAPPED": pgettext_lazy("change_type", "Lessons swapped"),
    },
    "payment_status": {
        "PENDING": pgettext_lazy("payment_status", "Created / pending"),
        "SUCCEEDED": pgettext_lazy("payment_status", "Succeeded"),
        "DECLINED": pgettext_lazy("payment_status", "Declined"),
        "INSUFFICIENT_FUNDS": pgettext_lazy("payment_status", "Insufficient funds"),
        "TIMEOUT": pgettext_lazy("payment_status", "Timed out"),
        "PROVIDER_ERROR": pgettext_lazy("payment_status", "Provider error"),
        "CANCELLED": pgettext_lazy("payment_status", "Cancelled"),
        "PARTIALLY_REFUNDED": pgettext_lazy("payment_status", "Partially refunded"),
        "REFUNDED": pgettext_lazy("payment_status", "Refunded"),
    },
    "complaint_status": {
        "DRAFT": pgettext_lazy("complaint_status", "Draft"),
        "OPEN": pgettext_lazy("complaint_status", "Open"),
        "IN_PROGRESS": pgettext_lazy("complaint_status", "In progress"),
        "RESOLVED": pgettext_lazy("complaint_status", "Resolved"),
        "CANCELLED": pgettext_lazy("complaint_status", "Cancelled"),
        "CLOSED": pgettext_lazy("complaint_status", "Closed"),
    },
}

DEFAULT_LANGUAGE = "fr"


def text(key, **params):
    """Language-neutral description of a system text (JSON, stored)."""
    if key not in TEXTS:
        raise KeyError(key)
    # business values (Decimal amounts, numbers…) kept as the text they print as
    params = {name: v if isinstance(v, dict) or name == "n" else str(v) for name, v in params.items()}
    return {"key": key, "params": params}


def label(group, code, *, lower=False):
    """A status label inside a text, translated with it (`lower`: as in a sentence)."""
    if code not in LABELS[group]:
        raise KeyError(f"{group}.{code}")
    return {"label": group, "code": code, "lower": lower}


def _render(value):
    if not isinstance(value, dict):
        return str(value)  # business data: as it is
    if "label" in value:
        word = str(LABELS[value["label"]][value["code"]])
        return word.lower() if value.get("lower") else word
    template = TEXTS[value["key"]]
    params = {name: v if name == "n" else _render(v) for name, v in value.get("params", {}).items()}
    return template % params if params else str(template)


def render(spec, language=DEFAULT_LANGUAGE):
    """The text of `spec` in `language` (fr / en; anything else -> French)."""
    with override(language if language in ("fr", "en") else DEFAULT_LANGUAGE):
        return _render(spec)


def is_text(value):
    return isinstance(value, dict) and "key" in value

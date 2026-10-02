"""Teacher / subject compatibility evaluation (spec §15).

"Teacher compatibility is machine-checked but the final decision belongs to
the administrator; overrides are audited."

Inputs:  teacher category + teacher primary subject + declared subject + level
Output:  a *recommendation* (CompatibilityResult), never a decision.

Algorithm (first match wins):

1. An active CompatibilityOverride covers (teacher, subject, level)
   -> OVERRIDDEN. An override with level NULL covers every level.
2. The most specific SubjectCompatibilityRule for
   (teacher category, subject): a rule for this exact level beats an
   "all levels" rule; then the highest `priority` wins.
       compatible & not review  -> COMPATIBLE
       review requested         -> REQUIRES_REVIEW (compatible or not)
       incompatible & no review -> INCOMPATIBLE
3. No rule at all:
       subject is the teacher's primary subject, or belongs to the
       teacher's own pedagogical category -> COMPATIBLE
       otherwise                            -> REQUIRES_REVIEW
   (an unknown case is never silently accepted nor silently refused).
"""

from dataclasses import dataclass

from django.db.models import Q
from django.utils import timezone

from apps.academics.models import SubjectCompatibilityRule

from .models import CompatibilityOverride, CompatibilityResult


@dataclass(frozen=True)
class Evaluation:
    result: CompatibilityResult
    rule: SubjectCompatibilityRule | None = None
    override: CompatibilityOverride | None = None


def _active_override(teacher, subject, level, now):
    level_scope = Q(level__isnull=True) | Q(level=level) if level is not None else Q(level__isnull=True)
    return (
        CompatibilityOverride.objects.filter(teacher=teacher, subject=subject)
        .filter(level_scope)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .order_by("-created_at")
        .first()
    )


def _best_rule(teacher, subject, level):
    rules = SubjectCompatibilityRule.objects.filter(
        school=teacher.school, pedagogical_category=teacher.pedagogical_category, subject=subject
    )
    if level is None:
        return rules.filter(level__isnull=True).order_by("-priority").first()
    # Level-specific rules first (level IS NULL sorts last in descending
    # order of "has a level"), then by priority.
    candidates = list(rules.filter(Q(level=level) | Q(level__isnull=True)))
    candidates.sort(key=lambda r: (r.level_id is not None, r.priority), reverse=True)
    return candidates[0] if candidates else None


def evaluate(teacher, subject, level=None, now=None) -> Evaluation:
    now = now or timezone.now()

    override = _active_override(teacher, subject, level, now)
    if override is not None:
        return Evaluation(CompatibilityResult.OVERRIDDEN, override=override)

    rule = _best_rule(teacher, subject, level)
    if rule is not None:
        if rule.requires_admin_review:
            result = CompatibilityResult.REQUIRES_REVIEW
        elif rule.compatible:
            result = CompatibilityResult.COMPATIBLE
        else:
            result = CompatibilityResult.INCOMPATIBLE
        return Evaluation(result, rule=rule)

    if subject.pk == teacher.primary_subject_id or (
        subject.category_id is not None and subject.category_id == teacher.pedagogical_category_id
    ):
        return Evaluation(CompatibilityResult.COMPATIBLE)
    return Evaluation(CompatibilityResult.REQUIRES_REVIEW)

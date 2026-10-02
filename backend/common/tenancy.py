"""Resolution of the tenant (school) a request acts on.

Spec §8: "Tenant scope is resolved from the authenticated SchoolMembership and
must match the target school." The client never sends a school *id* that the
server trusts blindly: it may only *choose* among schools where the user has an
ACTIVE membership.
"""

from .errors import ApiPermissionError, ErrorCode

# Optional header letting a multi-school user pick a school (future use).
SCHOOL_HEADER = "HTTP_X_SCHOOL_CODE"


def get_active_membership(request):
    """Return the SchoolMembership the current request operates under.

    Rules:
    1. Only ACTIVE memberships in ACTIVE schools are candidates.
    2. If the client sends `X-School-Code`, it must match one candidate.
    3. Otherwise the membership flagged `is_primary_school` wins; if the user
       has a single membership (the normal V1 case) that one is used.
    The result is cached on the request to avoid repeated queries.
    """
    if hasattr(request, "_active_membership"):
        return request._active_membership

    # Imported lazily: common/ must not depend on apps at import time.
    from apps.accounts.models import SchoolMembership

    candidates = SchoolMembership.objects.active().filter(user=request.user).select_related("school")

    code = request.META.get(SCHOOL_HEADER)
    if code:
        membership = candidates.filter(school__code=code).first()
    else:
        memberships = list(candidates)
        primary = [m for m in memberships if m.is_primary_school]
        if len(primary) == 1:
            membership = primary[0]
        elif len(memberships) == 1:
            membership = memberships[0]
        else:
            membership = None

    if membership is None:
        # Same message whether the school does not exist or the user is not a
        # member: do not reveal which schools exist.
        raise ApiPermissionError(ErrorCode.NO_ACTIVE_MEMBERSHIP)

    request._active_membership = membership
    return membership


def get_current_school(request):
    """The School (tenant) the current request operates on."""
    return get_active_membership(request).school


def scope_to_current_school(queryset, request, school_field="school"):
    """Restrict a queryset to rows of the current school.

    This is the pattern every business endpoint must follow for object lookups:

        obj = get_object_or_404(scope_to_current_school(Model.objects.all(), request), pk=pk)

    An id belonging to another school then yields 404, exactly like an id that
    does not exist: changing an identifier in the URL reveals nothing about,
    and gives no access to, the other tenant's data.
    """
    return queryset.filter(**{school_field: get_current_school(request)})

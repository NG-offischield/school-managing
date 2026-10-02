"""Reusable DRF permission classes.

The frontend is never a security boundary (spec §8): every view declares its
permissions here, on the server, even if the client already hides the button.
Object-level rules (students, grades, invoices...) will extend these in the
phases that introduce those objects.
"""

from rest_framework.permissions import BasePermission

from .tenancy import get_active_membership


class IsSchoolMember(BasePermission):
    """Authenticated AND acting inside a school where the user is ACTIVE."""

    message = "No active school membership for this request."

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        # Raises ApiPermissionError(NO_ACTIVE_MEMBERSHIP) when no membership matches.
        get_active_membership(request)
        return True


class HasSchoolRole(IsSchoolMember):
    """Requires one of `required_roles` in the active school.

    Usage on a view:
        permission_classes = [HasSchoolRole]
        required_roles = {RoleCode.ADMIN, RoleCode.SUPER_ADMIN}

    Roles are tenant-scoped: being ADMIN in school A grants nothing in school B.
    """

    message = "You do not have the required role in this school."

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        required = getattr(view, "required_roles", None)
        if not required:
            # A view using this class without declaring roles is a programming
            # error: fail closed rather than open.
            return False
        membership = get_active_membership(request)
        return bool(membership.role_codes() & set(required))


# Roles allowed to administer school data (spec §8 matrix: CRUD columns).
ADMIN_ROLES = frozenset({"SUPER_ADMIN", "ADMIN"})


def membership_has_role(membership, roles) -> bool:
    """True if `membership` is ACTIVE and holds one of `roles` (codes)."""
    return membership is not None and membership.status == "ACTIVE" and bool(membership.role_codes() & set(roles))


def require_role(membership, roles, *, school, message="This action requires an administrator of the school."):
    """Service-level guard: services are callable from anywhere (API, admin
    desktop, commands), so they check the actor themselves instead of
    trusting the caller.

    `school` is mandatory: the actor must hold the role IN THE SCHOOL OF THE
    DATA being changed. An administrator of school B is nobody in school A.
    """
    from django.core.exceptions import PermissionDenied

    if membership is None or membership.school_id != school.pk or not membership_has_role(membership, roles):
        raise PermissionDenied(message)

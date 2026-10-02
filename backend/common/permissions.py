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

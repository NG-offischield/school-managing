"""Parent registrations and verified parent–pupil links (backend
people/parent_workflow_api.py, ADR 0026). Thin client: the server decides
everything (identity match, pupil's approval, sponsor's rights, school).

    GET  /admin/registrations/?status=&search=      POST …/{id}/approve/ | /reject/ {reason}
    GET  /admin/link-requests/?status=&search=      GET  …/{id}/
    POST …/{id}/verify-identity/   {document_type, document_number}
    POST …/{id}/student-approval/  {decision, note}
    POST …/{id}/approve/           {can_pay, can_view_financial_data, can_receive_notifications,
                                    can_submit_complaints}
    POST …/{id}/reject/            {reason}

The identity document number typed here is read from the PHYSICAL document
shown at the school; it is sent once for the comparison and never kept.
"""

from ..api.errors import ValidationFailed
from ..models import LinkRequest, ParentRegistration


def _reason(reason):
    reason = (reason or "").strip()
    if not reason:
        raise ValidationFailed("Formulaire incomplet.", details={"reason": ["Indiquez le motif."]})
    return reason


class ParentAdminService:
    PAGE_SIZE = 50

    def __init__(self, api):
        self.api = api

    # --- registrations -----------------------------------------------------------
    def registrations(self, *, page=1, status=None, search=None):
        rows, total = self.api.page(
            "admin/registrations/",
            page=page,
            page_size=self.PAGE_SIZE,
            status=status or None,
            search=(search or "").strip() or None,
        )
        return [ParentRegistration.from_api(r) for r in rows], total

    def approve_registration(self, registration_id):
        return ParentRegistration.from_api(self.api.post(f"admin/registrations/{registration_id}/approve/"))

    def reject_registration(self, registration_id, reason):
        return ParentRegistration.from_api(
            self.api.post(f"admin/registrations/{registration_id}/reject/", {"reason": _reason(reason)})
        )

    # --- link requests -----------------------------------------------------------
    def link_requests(self, *, page=1, status=None, search=None):
        rows, total = self.api.page(
            "admin/link-requests/",
            page=page,
            page_size=self.PAGE_SIZE,
            status=status or None,
            search=(search or "").strip() or None,
        )
        return [LinkRequest.from_api(r) for r in rows], total

    def link_request(self, request_id):
        return LinkRequest.from_api(self.api.get(f"admin/link-requests/{request_id}/"))

    def verify_identity(self, request_id, document_type, document_number):
        number = (document_number or "").strip()
        if not document_type or not number:
            raise ValidationFailed(
                "Formulaire incomplet.", details={"document_number": ["Saisissez le numéro de la pièce présentée."]}
            )
        return LinkRequest.from_api(
            self.api.post(
                f"admin/link-requests/{request_id}/verify-identity/",
                {"document_type": document_type, "document_number": number},
            )
        )

    def record_student_approval(self, request_id, decision, note=""):
        return LinkRequest.from_api(
            self.api.post(
                f"admin/link-requests/{request_id}/student-approval/",
                {"decision": decision, "note": (note or "").strip()},
            )
        )

    def approve(
        self,
        request_id,
        *,
        can_pay=False,
        can_view_financial_data=False,
        can_receive_notifications=True,
        can_submit_complaints=True,
    ):
        return LinkRequest.from_api(
            self.api.post(
                f"admin/link-requests/{request_id}/approve/",
                {
                    "can_pay": bool(can_pay),
                    "can_view_financial_data": bool(can_view_financial_data),
                    "can_receive_notifications": bool(can_receive_notifications),
                    "can_submit_complaints": bool(can_submit_complaints),
                },
            )
        )

    def reject(self, request_id, reason):
        return LinkRequest.from_api(
            self.api.post(f"admin/link-requests/{request_id}/reject/", {"reason": _reason(reason)})
        )

"""Parent registrations and link requests part of the fake API (mixin of
FakeBackend, ADR 0026), with the server rules the desktop must surface:
409 registration_not_pending / request_not_pending / identity_mismatch (3
mismatches -> identity_rejected) / identity_not_verified /
student_approval_required / rights_exceed_sponsor; 400 without a reason."""

import httpx

NOW = "2026-03-04T10:00:00+01:00"
DECLARED_NUMBER = "CM12345678"  # what the fake "parent" declared (normalised)


def _norm(number):
    return "".join(ch for ch in (number or "").upper() if ch.isalnum())


class ParentsFake:
    def init_parents(self):
        self.registrations = {}
        self.link_requests = {}

    def seed_parents(self):
        for key, name, email, status in (
            ("reg1", "Awa Mbarga", "awa@example.cm", "PENDING"),
            ("reg2", "Paul Ndiaye", "paul@example.cm", "PENDING"),
            ("reg3", "Ancien Parent", "ancien@example.cm", "APPROVED"),
        ):
            self.registrations[key] = {
                "id": key,
                "status": status,
                "applicant_name": name,
                "applicant_email": email,
                "applicant_phone": "+237 600 00 00 00",
                "school_name": "École de test",
                "submitted_at": NOW,
                "reviewed_at": NOW if status != "PENDING" else None,
                "rejection_reason": None,
            }
        for key, parent, student, sponsored in (
            ("lr1", "Awa Mbarga", "Élève Zéro", False),
            ("lr2", "Paul Ndiaye", "Élève Zéro", True),
        ):
            self.link_requests[key] = {
                "id": key,
                "student": {"id": "s0", "name": student, "student_number": "MAT00001"},
                "relationship_type": "MOTHER" if not sponsored else "FATHER",
                "status": "PENDING",
                "student_approval_status": "PENDING",
                "identity_status": "VERIFIED" if sponsored else "PENDING",
                "identity_method": "SPONSOR_2FA" if sponsored else "ID_DOCUMENT",
                "document_type": "CNI",
                "sponsored": sponsored,
                "created_at": NOW,
                "decided_at": None,
                "decision_reason": None,
                "parent": {"id": f"p-{key}", "name": parent, "email": "x@example.cm", "phone": None},
                "class_name": "3e A",
                "identity_failed_checks": 0,
                "student_approval_note": None,
                "sponsor_name": "Marie Mbarga" if sponsored else None,
                "initiated_by": "PARENT",
                # sponsor's rights (server side only)
                "_sponsor_rights": {"can_pay": True, "can_view_financial_data": False},
            }

    def _p_ok(self, data, status=200):
        return httpx.Response(status, json={"success": True, "data": data, "message": None, "meta": None})

    def _p_fail(self, status, code, rule=None):
        error = {"code": code, "message": code}
        if rule:
            error["details"] = {"rule": rule}
        return httpx.Response(status, json={"success": False, "error": error})

    @staticmethod
    def _public(row):
        return {k: v for k, v in row.items() if not k.startswith("_")}

    def _p_list(self, rows, request, fields):
        status = request.url.params.get("status")
        search = (request.url.params.get("search") or "").lower()
        if status:
            rows = [r for r in rows if r["status"] == status]
        if search:
            rows = [r for r in rows if any(search in (f(r) or "").lower() for f in fields)]
        return self._page([self._public(r) for r in rows], request)

    def _parents(self, request, path, body, admin):
        if not admin:
            return self._p_fail(403, "PERMISSION_DENIED")
        parts = [p for p in path.split("/") if p]  # admin, registrations|link-requests, [id, [action]]
        family = parts[1]
        if family == "registrations":
            if len(parts) == 2:
                rows = list(self.registrations.values())
                return self._p_list(rows, request, (lambda r: r["applicant_name"], lambda r: r["applicant_email"]))
            row = self.registrations.get(parts[2])
            if row is None:
                return self._p_fail(404, "NOT_FOUND")
            action = parts[3] if len(parts) > 3 else ""
            if action in ("approve", "reject") and row["status"] != "PENDING":
                return self._p_fail(409, "CONFLICT", "registration_not_pending")
            if action == "reject" and not (body or {}).get("reason"):
                return self._p_fail(400, "VALIDATION_ERROR")
            if action:
                row["status"] = "APPROVED" if action == "approve" else "REJECTED"
                row["reviewed_at"] = NOW
                row["rejection_reason"] = (body or {}).get("reason")
            return self._p_ok(self._public(row))

        if len(parts) == 2:
            rows = list(self.link_requests.values())
            return self._p_list(rows, request, (lambda r: r["student"]["name"], lambda r: r["parent"]["name"]))
        row = self.link_requests.get(parts[2])
        if row is None:
            return self._p_fail(404, "NOT_FOUND")
        action = parts[3] if len(parts) > 3 else ""
        if not action:
            return self._p_ok(self._public(row))
        if row["status"] != "PENDING":
            return self._p_fail(409, "CONFLICT", "request_not_pending")
        body = body or {}
        if action == "verify-identity":
            if row["identity_status"] == "REJECTED":
                return self._p_fail(409, "CONFLICT", "identity_rejected")
            if row["identity_status"] == "VERIFIED":
                return self._p_ok(self._public(row))
            if body.get("document_type") == row["document_type"] and _norm(body.get("document_number")) == (
                DECLARED_NUMBER
            ):
                row["identity_status"] = "VERIFIED"
                return self._p_ok(self._public(row))
            row["identity_failed_checks"] += 1
            if row["identity_failed_checks"] >= 3:
                row["identity_status"] = "REJECTED"
            return self._p_fail(409, "CONFLICT", "identity_mismatch")
        if action == "student-approval":
            row["student_approval_status"] = body.get("decision")
            row["student_approval_note"] = body.get("note") or None
            return self._p_ok(self._public(row))
        if action == "approve":
            if row["identity_status"] != "VERIFIED":
                return self._p_fail(409, "CONFLICT", "identity_not_verified")
            if row["student_approval_status"] not in ("APPROVED", "NOT_REQUIRED"):
                return self._p_fail(409, "CONFLICT", "student_approval_required")
            if row["sponsored"] and any(body.get(k) and not v for k, v in row["_sponsor_rights"].items()):
                return self._p_fail(409, "CONFLICT", "rights_exceed_sponsor")
            row["status"], row["decided_at"], row["_rights"] = "APPROVED", NOW, dict(body)
            return self._p_ok(self._public(row))
        if action == "reject":
            if not body.get("reason"):
                return self._p_fail(400, "VALIDATION_ERROR")
            row["status"], row["decision_reason"] = "REJECTED", body["reason"]
            return self._p_ok(self._public(row))
        return None

"""Fake of the attendance / guardian administration endpoints (backend
attendance/api.py: admin/attendance/daily/, admin/scans/; people/
guardian_admin_api.py) for the desktop tests: the CONTRACT — attendance
computed by the server and corrected with a reason (/correct/), scans
filtered by guardian, annual QR codes (issue, issue-class, reissue, revoke),
guardians created without password (activation and suspension: admin/accounts/)."""

import uuid

import httpx

TODAY = "2026-03-02"


class AttendanceFake:
    def init_attendance(self):
        self.guardians = {}
        self.daily_rows = [
            {
                "id": "d1",
                "student": "s1",
                "date": TODAY,
                "status": "PRESENT",
                "arrival_time": f"{TODAY}T07:12:00+01:00",
                "late_minutes": 0,
                "student_name": "Awa Ndiaye",
                "student_number": "MAT-001",
                "school_class_name": "6e A",
                "school_class": "c-6a",
            },
            {
                "id": "d2",
                "student": "s2",
                "date": TODAY,
                "status": "LATE",
                "arrival_time": f"{TODAY}T07:48:00+01:00",
                "late_minutes": 18,
                "student_name": "Paul Kamga",
                "student_number": "MAT-002",
                "school_class_name": "6e A",
                "school_class": "c-6a",
            },
            {
                "id": "d3",
                "student": "s3",
                "date": TODAY,
                "status": "ABSENT",
                "arrival_time": None,
                "late_minutes": 0,
                "student_name": "Bruno Ekane",
                "student_number": "MAT-003",
                "school_class_name": "5e A",
                "school_class": "c-5a",
            },
        ]
        self.scan_rows = []
        self.attendance_queries = []
        self.qr_codes = {}  # id -> QRSerializer row
        self.corrections = []  # bodies received by /correct/
        gid = self.add_guardian("Moussa", "Bello", "G-01", activated=True)
        self.scan_rows += [
            {
                "id": "sc1",
                "scanned_at": f"{TODAY}T07:12:00+01:00",
                "result": "ACCEPTED",
                "student_name": "Awa Ndiaye",
                "scanned_by_name": "Moussa Bello",
                "guardian": gid,
            },
            {
                "id": "sc2",
                "scanned_at": f"{TODAY}T07:20:00+01:00",
                "result": "UNKNOWN_TOKEN",
                "student_name": None,
                "scanned_by_name": "Moussa Bello",
                "guardian": gid,
            },
        ]

    # --- attendance.services.correct_attendance / QR codes (the rules the screens rely on) ---
    def _correct(self, record_id, body):
        record = next((r for r in self.daily_rows if r["id"] == record_id), None)
        if record is None:
            return self._at_fail(404, "NOT_FOUND")
        if not (body.get("reason") or "").strip():
            return self._at_fail(400, "BUSINESS_RULE_VIOLATION", "reason_required")
        status = body.get("status")
        if status not in ("PRESENT", "LATE", "ABSENT", "EXCUSED"):
            return self._at_fail(400, "VALIDATION_ERROR", details={"status": ["Invalid choice."]})
        self.corrections.append(dict(body))
        if status in ("PRESENT", "LATE"):
            arrival = body.get("arrival_time") or record["arrival_time"]
            if not arrival:
                return self._at_fail(400, "BUSINESS_RULE_VIOLATION", "arrival_required")
            hour, minute = int(arrival[11:13]), int(arrival[14:16])
            late = max(0, hour * 60 + minute - (7 * 60 + 30))  # policy: late after 07:30
            record.update(status="LATE" if late else "PRESENT", arrival_time=arrival, late_minutes=late)
        else:
            record.update(status=status, arrival_time=None, late_minutes=0)
        record["note"] = body["reason"].strip()
        return self._at_ok(record)

    def _enrolled(self, student_id):
        return (
            any(e["student"] == student_id and e["status"] == "ACTIVE" for e in self.student_enrollments.values())
            and self.students.get(student_id, {}).get("status") == "ACTIVE"
        )

    def _issue_qr(self, student_id):
        active = next(
            (q for q in self.qr_codes.values() if q["student"] == student_id and q["status"] == "ACTIVE"), None
        )
        if active:
            return active  # idempotent
        version = 1 + max((q["version"] for q in self.qr_codes.values() if q["student"] == student_id), default=0)
        qid = str(uuid.uuid4())
        self.qr_codes[qid] = {
            "id": qid,
            "student": student_id,
            "academic_year": "y1",
            "token": uuid.uuid4().hex + "abcdefghijk",  # 43 characters, like the server's
            "version": version,
            "status": "ACTIVE",
            "issued_at": f"{TODAY}T08:00:00+01:00",
            "revoked_at": None,
            "revocation_reason": None,
        }
        return self.qr_codes[qid]

    def _revoke_qr(self, qr, reason):
        qr.update(status="REVOKED", revoked_at=f"{TODAY}T09:00:00+01:00", revocation_reason=reason.strip())

    def _qr(self, request, parts, body):
        if request.method == "GET" and len(parts) == 2:
            params = request.url.params
            rows = list(self.qr_codes.values())
            if params.get("student"):
                rows = [q for q in rows if q["student"] == params["student"]]
            if params.get("status"):
                rows = [q for q in rows if q["status"] == params["status"]]
            return self._page(rows, request)
        action = parts[2]
        if action in ("issue", "reissue"):
            student = body.get("student")
            if student not in self.students:
                return self._at_fail(404, "NOT_FOUND")
            if not self._enrolled(student):
                return self._at_fail(400, "BUSINESS_RULE_VIOLATION", "student_not_enrolled")
            if action == "reissue":
                if not (body.get("reason") or "").strip():
                    return self._at_fail(400, "BUSINESS_RULE_VIOLATION", "reason_required")
                for qr in [q for q in self.qr_codes.values() if q["student"] == student and q["status"] == "ACTIVE"]:
                    self._revoke_qr(qr, body["reason"])
            return self._at_ok(self._issue_qr(student), 201)
        if action == "issue-class":
            enrolled = [
                e["student"]
                for e in self.student_enrollments.values()
                if e["school_class"] == body.get("school_class") and e["status"] != "WITHDRAWN"
            ]
            return self._at_ok([self._issue_qr(s) for s in enrolled if self._enrolled(s)], 201)
        qr = self.qr_codes.get(action)
        if qr is None or len(parts) < 4 or parts[3] != "revoke":
            return self._at_fail(404, "NOT_FOUND")
        if not (body.get("reason") or "").strip():
            return self._at_fail(400, "BUSINESS_RULE_VIOLATION", "reason_required")
        if qr["status"] == "REVOKED":
            return self._at_fail(400, "BUSINESS_RULE_VIOLATION", "qr_already_revoked")
        self._revoke_qr(qr, body["reason"])
        return self._at_ok(qr)

    def add_guardian(self, first, last, number, *, activated=False, status="ACTIVE"):
        gid = str(uuid.uuid4())
        self.guardians[gid] = {
            "id": gid,
            "membership": f"m-{gid[:8]}",
            "guardian_number": number,
            "status": "ACTIVE",
            "first_name": first,
            "last_name": last,
            "email": f"{first.lower()}@ecole.test",
            "phone": "",
            "account_status": status,
            "activated": activated,
            "scans_today": 0,
            "last_scan_at": None,
        }
        # The account itself lives in AccountsFake (activation code, disable / enable).
        self.accounts[self.guardians[gid]["membership"]] = {
            "state": "ACTIVE" if activated else ("DISABLED" if status == "SUSPENDED" else "NOT_ACTIVATED"),
            "login": f"{first.lower()}@ecole.test",
            "name": f"{first} {last}",
            "codes": [],
        }
        return gid

    def _guardian_out(self, guardian):
        state = self.accounts[guardian["membership"]]["state"]
        return {
            **guardian,
            "account_status": "SUSPENDED" if state == "DISABLED" else "ACTIVE",
            "activated": state == "ACTIVE",
            "scans_today": sum(1 for s in self.scan_rows if s["guardian"] == guardian["id"]),
            "last_scan_at": max(
                (s["scanned_at"] for s in self.scan_rows if s["guardian"] == guardian["id"]), default=None
            ),
        }

    @staticmethod
    def _at_ok(data, status=200):
        return httpx.Response(status, json={"success": True, "data": data, "message": None, "meta": None})

    @staticmethod
    def _at_fail(status, code, rule=None, details=None):
        details = details or ({"rule": rule} if rule else None)
        return httpx.Response(
            status, json={"success": False, "error": {"code": code, "message": code, "details": details}}
        )

    def _attendance(self, request, path, body, admin):
        if not admin:
            return self._at_fail(403, "PERMISSION_DENIED")
        params = request.url.params
        self.attendance_queries.append((path, dict(params)))
        if path == "admin/attendance/daily/":
            if not params.get("date"):
                return self._at_fail(400, "VALIDATION_ERROR", details={"date": ["This query parameter is required."]})
            rows = [r for r in self.daily_rows if r["date"] == params["date"]]
            if params.get("school_class"):
                rows = [r for r in rows if r["school_class"] == params["school_class"]]
            return self._page(rows, request)
        parts = path.strip("/").split("/")
        if parts[:2] == ["admin", "attendance"] and parts[-1] == "correct":
            return self._correct(parts[2], body)
        if parts[:2] == ["admin", "qr-codes"]:
            return self._qr(request, parts, body)
        if path == "admin/scans/":
            rows = [r for r in self.scan_rows if not params.get("date") or r["scanned_at"].startswith(params["date"])]
            if params.get("guardian"):
                rows = [r for r in rows if r["guardian"] == params["guardian"]]
            if params.get("result"):
                rows = [r for r in rows if r["result"] == params["result"]]
            return self._page(sorted(rows, key=lambda r: r["scanned_at"], reverse=True), request)
        if path == "admin/guardians/":
            if request.method == "POST":
                if any(g["guardian_number"] == body.get("guardian_number") for g in self.guardians.values()):
                    return self._at_fail(409, "CONFLICT", "duplicate_guardian_number")
                gid = self.add_guardian(body["first_name"], body["last_name"], body["guardian_number"])
                self.guardians[gid]["email"] = body["email"]
                return self._at_ok(self._guardian_out(self.guardians[gid]), 201)
            rows = [self._guardian_out(g) for g in self.guardians.values()]
            if params.get("status"):
                rows = [g for g in rows if g["account_status"] == params["status"]]
            search = (params.get("search") or "").lower()
            rows = [
                g
                for g in rows
                if not search or search in f"{g['first_name']} {g['last_name']} {g['guardian_number']}".lower()
            ]
            return self._page(rows, request)
        return None

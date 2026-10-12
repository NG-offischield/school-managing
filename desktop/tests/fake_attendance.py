"""Fake of the attendance / guardian administration endpoints (backend
attendance/api.py: admin/attendance/daily/, admin/scans/; people/
guardian_admin_api.py) for the desktop tests: the CONTRACT — read-only
attendance computed by the server, scans filtered by guardian, guardians
created without password (activation and suspension: admin/accounts/)."""

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

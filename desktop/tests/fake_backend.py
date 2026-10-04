"""In-memory fake of the Django API used by the unit tests (httpx.MockTransport).

It reproduces the CONTRACT the desktop relies on — envelope, pagination
meta, error body, token rotation, catalogue rules the client must surface —
not the backend's business logic. The real backend is exercised by the
opt-in live test (test_live.py).
"""

import json
import uuid

import httpx

PASSWORD = "correct-horse-test"


def ok(data, status=200, meta=None):
    return httpx.Response(status, json={"success": True, "data": data, "message": None, "meta": meta})


def fail(status, code, message, details=None):
    error = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return httpx.Response(status, json={"success": False, "error": error})


class FakeBackend:
    def __init__(self, *, roles=("SUPER_ADMIN",)):
        self.roles = list(roles)
        self.sessions = {}  # access token -> refresh token
        self.refresh_tokens = set()
        self.revoked = set()
        self.categories = {}
        self.subjects = {}
        self.calls = []
        self.forced = {}  # (method, path) -> response, to inject errors
        self.offline = False
        self.login_bodies = []
        self.photo_uploads = []  # raw multipart bodies received (privacy checks)
        # Academic structure: years (current, closed, planned), levels, rooms, classes.
        self.years = [
            {
                "id": "y1",
                "name": "2025-2026",
                "start_date": "2025-09-01",
                "end_date": "2026-07-31",
                "status": "ACTIVE",
                "is_current": True,
            },
            {
                "id": "y0",
                "name": "2024-2025",
                "start_date": "2024-09-01",
                "end_date": "2025-07-31",
                "status": "CLOSED",
                "is_current": False,
            },
            {
                "id": "y2",
                "name": "2026-2027",
                "start_date": "2026-09-01",
                "end_date": "2027-07-31",
                "status": "PLANNED",
                "is_current": False,
            },
        ]
        self.levels = {}
        for lid, code, name, order, active in (
            ("l6", "6E", "Sixième", 1, True),
            ("l5", "5E", "Cinquième", 2, True),
            ("lx", "OLD", "Ancien niveau", 9, False),
        ):
            self.add_level(code, name, order, active=active, lid=lid)
        self.rooms = {
            "r1": {"id": "r1", "code": "R12", "name": "Salle 12", "capacity": 40, "active": True},
            "r2": {"id": "r2", "code": "LAB", "name": "Laboratoire", "capacity": 30, "active": True},
            "rx": {"id": "rx", "code": "OLD", "name": "Salle fermée", "capacity": 20, "active": False},
        }
        self.classes = {}
        self.classes_in_use = set()
        for name, level in (("6e A", "l6"), ("6e B", "l6"), ("5e A", "l5"), ("5e B", "l5")):
            self.add_class(name, level)
        self.classes_in_use.add(next(c["id"] for c in self.classes.values() if c["name"] == "6e A"))
        self.years_with_pupils = {"y1"}  # active enrollments: the year cannot be closed
        self.activity = []  # administrative audit trail (newest first)
        # Dashboard aggregates (what core/dashboard_api.py would compute).
        self.attendance_days = [
            {"date": "2026-03-02", "PRESENT": 100, "LATE": 8, "ABSENT": 10, "EXCUSED": 2, "PENDING": 0, "total": 120},
            {"date": "2026-03-03", "PRESENT": 104, "LATE": 6, "ABSENT": 8, "EXCUSED": 2, "PENDING": 0, "total": 120},
            {"date": "2026-03-04", "PRESENT": 0, "LATE": 0, "ABSENT": 0, "EXCUSED": 0, "PENDING": 120, "total": 120},
        ]
        self.enrollments = {
            "academic_year": "y1",
            "academic_year_name": "2025-2026",
            "total": 120,
            "by_level": [
                {"level": "l6", "code": "6E", "name": "Sixième", "count": 70},
                {"level": "l5", "code": "5E", "name": "Cinquième", "count": 50},
            ],
            "by_class": [
                {"class": "c1", "name": "6e A", "level_code": "6E", "count": 38, "capacity": 40},
                {"class": "c2", "name": "6e B", "level_code": "6E", "count": 32, "capacity": None},
                {"class": "c3", "name": "5e A", "level_code": "5E", "count": 50, "capacity": 50},
            ],
            "by_month": [
                {"month": "2025-09", "enrolled": 112},
                {"month": "2025-10", "enrolled": 118},
                {"month": "2025-11", "enrolled": 120},
            ],
        }
        # Students (people/student_api.py): two enrolled this year, one not
        # enrolled, one archived.
        self.students = {}
        self.student_enrollments = {}
        self.student_history = {}
        self.photos = {}
        six_a = next(c["id"] for c in self.classes.values() if c["name"] == "6e A")
        five_a = next(c["id"] for c in self.classes.values() if c["name"] == "5e A")
        self.awa = self.add_student("MAT-001", "Ndiaye", "Awa", "F", class_id=six_a)
        self.bruno = self.add_student("MAT-002", "Ekane", "Bruno", "M", class_id=five_a)
        self.chloe = self.add_student("MAT-003", "Fotso", "Chloé", "F")
        self.dan = self.add_student("MAT-004", "Mbia", "Dan", "M", status="ARCHIVED")
        # Teachers (people/teacher_api.py). None by default: seed_teachers() builds a staff room.
        self.teachers = {}
        self.qualifications = {}
        self.overrides = []
        self.rules = {}  # (category_id, subject_id) -> COMPATIBLE | REQUIRES_REVIEW | INCOMPATIBLE
        self.teachers_in_use = set()
        self.rates = {}
        # Courses (gradebook/course_api.py): course = subject + teacher + class + year.
        self.courses = {}
        self.courses_scheduled = set()
        self.finance = {
            "currency": "XAF",
            "net_collected": "1250000.00",
            "outstanding": "300000.00",
            "overdue_invoices": 2,
        }

    # --- helpers ----------------------------------------------------------------

    def _issue(self):
        access, refresh = f"acc-{uuid.uuid4().hex}", f"ref-{uuid.uuid4().hex}"
        self.sessions[access] = refresh
        self.refresh_tokens.add(refresh)
        return {"access_token": access, "refresh_token": refresh, "access_expires_in": 900}

    def expire_access_tokens(self):
        self.sessions = {}

    def add_category(self, code, name, active=True):
        cid = str(uuid.uuid4())
        self.categories[cid] = {
            "id": cid,
            "code": code,
            "name": name,
            "description": None,
            "active": active,
            "active_subject_count": 0,
        }
        return cid

    def add_level(self, code, name, order_index=0, *, active=True, cycle="", lid=None):
        lid = lid or str(uuid.uuid4())
        self.levels[lid] = {
            "id": lid,
            "code": code,
            "name": name,
            "cycle": cycle,
            "order_index": order_index,
            "first_character": None,
            "public_visible": False,
            "active": active,
        }
        return lid

    def add_student(self, number, last, first, sex, *, class_id=None, status="ACTIVE", year="y1"):
        sid = str(uuid.uuid4())
        self.students[sid] = {
            "id": sid,
            "student_number": number,
            "registration_number": f"INS-{number}",
            "first_name": first,
            "last_name": last,
            "date_of_birth": "2013-02-01",
            "sex": sex,
            "birth_place": "Douala",
            "address": None,
            "height_cm": None,
            "status": status,
            "archived_at": "2026-01-10T09:00:00+00:00" if status == "ARCHIVED" else None,
        }
        self.student_history[sid] = [self._event("STUDENT_CREATED", "")]
        if class_id:
            self.add_enrollment(sid, class_id)
        return sid

    def add_enrollment(self, student_id, class_id, status="ACTIVE"):
        eid = str(uuid.uuid4())
        school_class = self.classes[class_id]
        self.student_enrollments[eid] = {
            "id": eid,
            "student": student_id,
            "academic_year": school_class["academic_year"],
            "school_class": class_id,
            "enrollment_date": "2025-09-02",
            "end_date": None,
            "status": status,
            "promotion_status": "PENDING",
            "decision_date": None,
        }
        return eid

    @staticmethod
    def _event(action, summary):
        return {
            "id": str(uuid.uuid4()),
            "at": "2026-03-04T08:30:00+00:00",
            "action": action,
            "summary": summary,
            "actor": "Ada Admin",
        }

    def _enrollment_out(self, row):
        school_class = self.classes[row["school_class"]]
        level = self.levels[school_class["level"]]
        return {
            **row,
            "academic_year_name": self.year(row["academic_year"])["name"],
            "class_name": school_class["name"],
            "level": level["id"],
            "level_code": level["code"],
            "level_name": level["name"],
        }

    def _student_out(self, row, year_id=None):
        year_id = year_id or next((y["id"] for y in self.years if y["is_current"]), None)
        enrollment = next(
            (
                e
                for e in self.student_enrollments.values()
                if e["student"] == row["id"] and e["academic_year"] == year_id
            ),
            None,
        )
        out = {**row, "has_photo": row["id"] in self.photos}
        out["enrollment"] = self._enrollment_out(enrollment) if enrollment else None
        return out

    def _students(self, request, path, body, admin):
        method, params = request.method, request.url.params
        parts = path.strip("/").split("/")
        if path == "students/" and method == "GET":
            year = params.get("academic_year")
            rows = [self._student_out(r, year) for r in self.students.values()]
            search = (params.get("search") or "").lower()
            if search:
                rows = [
                    r
                    for r in rows
                    if any(search in (r[f] or "").lower() for f in ("last_name", "first_name", "student_number"))
                ]
            if params.get("status"):
                rows = [r for r in rows if r["status"] == params["status"]]
            if params.get("level"):
                rows = [r for r in rows if r["enrollment"] and r["enrollment"]["level"] == params["level"]]
            if params.get("school_class"):
                rows = [
                    r for r in rows if r["enrollment"] and r["enrollment"]["school_class"] == params["school_class"]
                ]
            wanted = params.get("enrollment_status")
            if wanted == "NONE":
                rows = [r for r in rows if r["enrollment"] is None]
            elif wanted:
                rows = [r for r in rows if r["enrollment"] and r["enrollment"]["status"] == wanted]
            elif year:
                rows = [r for r in rows if r["enrollment"]]
            return self._page(sorted(rows, key=lambda r: (r["last_name"], r["first_name"])), request)
        if method != "GET" and not admin:
            return fail(403, "PERMISSION_DENIED", "Permission refusée.")
        if path == "students/" and method == "POST":
            return self._student_write(None, body)
        if parts[0] == "enrollments":
            enrollment = self.student_enrollments.get(parts[1])
            if enrollment is None:
                return fail(404, "NOT_FOUND", "Inscription introuvable.")
            return self._enrollment_action(enrollment, parts[2], body)
        student = self.students.get(parts[1])
        if student is None:
            return fail(404, "NOT_FOUND", "Élève introuvable.")
        action = parts[2] if len(parts) > 2 else ""
        history = self.student_history[student["id"]]
        if action == "" and method == "GET":
            return ok(self._student_out(student))
        if action == "" and method == "PATCH":
            return self._student_write(student, body)
        if action == "archive":
            if any(
                e["student"] == student["id"] and e["status"] == "ACTIVE" for e in self.student_enrollments.values()
            ):
                return fail(409, "CONFLICT", "Inscription active.", {"rule": "active_enrollment"})
            student.update(status="ARCHIVED", archived_at="2026-03-04T08:30:00+00:00")
            history.insert(0, self._event("STUDENT_ARCHIVED", ""))
            return ok(self._student_out(student))
        if action == "reactivate":
            student.update(status="ACTIVE", archived_at=None)
            history.insert(0, self._event("STUDENT_REACTIVATED", ""))
            return ok(self._student_out(student))
        if action == "history":
            return ok(history)
        if action == "enrollments" and method == "GET":
            rows = [self._enrollment_out(e) for e in self.student_enrollments.values() if e["student"] == student["id"]]
            return self._page(rows, request)
        if action == "enrollments" and method == "POST":
            if student["status"] != "ACTIVE":
                return fail(400, "BUSINESS_RULE_VIOLATION", "Élève inactif.", {"rule": "student_not_active"})
            school_class = self.classes.get(body.get("school_class"))
            if school_class is None:
                return fail(404, "NOT_FOUND", "Classe introuvable.")
            if any(
                e["student"] == student["id"] and e["academic_year"] == school_class["academic_year"]
                for e in self.student_enrollments.values()
            ):
                return fail(409, "CONFLICT", "Déjà inscrit.", {"rule": "already_enrolled"})
            if self._full(school_class):
                return fail(409, "CONFLICT", "Classe pleine.", {"rule": "class_full"})
            eid = self.add_enrollment(student["id"], school_class["id"])
            history.insert(0, self._event("STUDENT_ENROLLED", school_class["name"]))
            return ok(self._enrollment_out(self.student_enrollments[eid]), status=201)
        if action == "photo":
            if method == "GET":
                if student["id"] not in self.photos:
                    return fail(404, "NOT_FOUND", "Pas de photo.")
                return httpx.Response(200, content=self.photos[student["id"]], headers={"Content-Type": "image/jpeg"})
            if method == "DELETE":
                self.photos.pop(student["id"], None)
                return ok(self._student_out(student))
            content = self._uploaded(request)
            if not (content.startswith(b"\x89PNG") or content.startswith(b"\xff\xd8")):
                return fail(400, "BUSINESS_RULE_VIOLATION", "Image illisible.", {"rule": "photo_invalid"})
            self.photo_uploads.append(request.content)
            self.photos[student["id"]] = content
            history.insert(0, self._event("STUDENT_PHOTO_SET", ""))
            return ok(self._student_out(student))
        return None

    @staticmethod
    def _uploaded(request):
        """Bytes of the single file of a multipart body."""
        raw = request.content
        start = raw.index(b"\r\n\r\n") + 4
        end = raw.rindex(b"\r\n--")
        return raw[start:end]

    def _full(self, school_class, moving=None):
        if not school_class.get("capacity"):
            return False
        taken = [
            e
            for e in self.student_enrollments.values()
            if e["school_class"] == school_class["id"] and e["status"] != "WITHDRAWN" and e is not moving
        ]
        return len(taken) >= school_class["capacity"]

    def _student_write(self, student, body):
        fields = ("student_number", "registration_number", "first_name", "last_name", "date_of_birth", "sex")
        if student is None:
            missing = {f: ["Ce champ est obligatoire."] for f in fields if not body.get(f)}
            if missing:
                return fail(400, "VALIDATION_ERROR", "Données invalides.", missing)
        elif student["status"] == "ARCHIVED":
            return fail(400, "BUSINESS_RULE_VIOLATION", "Élève archivé.", {"rule": "student_archived"})
        for name, rule in (
            ("student_number", "duplicate_student_number"),
            ("registration_number", "duplicate_registration_number"),
        ):
            value = (body.get(name) or "").lower()
            if value and any(s[name].lower() == value and s is not student for s in self.students.values()):
                return fail(409, "CONFLICT", "Numéro déjà utilisé.", {"rule": rule})
        editable = (*fields, "birth_place", "address", "height_cm")
        if student is None:
            enrollment = body.get("enrollment")
            school_class = self.classes.get(enrollment["school_class"]) if enrollment else None
            if enrollment and school_class is None:
                return fail(404, "NOT_FOUND", "Classe introuvable.")
            if school_class is not None and self._full(school_class):
                return fail(409, "CONFLICT", "Classe pleine.", {"rule": "class_full"})
            sid = self.add_student(body["student_number"], body["last_name"], body["first_name"], body["sex"])
            student = self.students[sid]
            student.update({k: v for k, v in body.items() if k in editable})
            if school_class is not None:
                self.add_enrollment(sid, school_class["id"])
                self.student_history[sid].insert(0, self._event("STUDENT_ENROLLED", school_class["name"]))
            return ok(self._student_out(student), status=201)
        student.update({k: v for k, v in body.items() if k in editable})
        self.student_history[student["id"]].insert(0, self._event("STUDENT_UPDATED", ", ".join(sorted(body))))
        return ok(self._student_out(student))

    def _enrollment_action(self, enrollment, action, body):
        if enrollment["status"] != "ACTIVE":
            return fail(409, "CONFLICT", "Inscription close.", {"rule": "enrollment_closed"})
        history = self.student_history[enrollment["student"]]
        if action == "withdraw":
            enrollment.update(status="WITHDRAWN", end_date=body.get("end_date") or "2026-03-04")
            history.insert(0, self._event("STUDENT_WITHDRAWN", self.classes[enrollment["school_class"]]["name"]))
            return ok(self._enrollment_out(enrollment))
        school_class = self.classes.get(body.get("school_class"))
        if school_class is None:
            return fail(404, "NOT_FOUND", "Classe introuvable.")
        if school_class["academic_year"] != enrollment["academic_year"]:
            return fail(400, "BUSINESS_RULE_VIOLATION", "Autre année.", {"rule": "class_other_year"})
        if school_class["id"] == enrollment["school_class"]:
            return fail(409, "CONFLICT", "Même classe.", {"rule": "same_class"})
        if self._full(school_class, moving=enrollment):
            return fail(409, "CONFLICT", "Classe pleine.", {"rule": "class_full"})
        old = self.classes[enrollment["school_class"]]["name"]
        enrollment["school_class"] = school_class["id"]
        history.insert(0, self._event("STUDENT_CLASS_CHANGED", f"{old} → {school_class['name']}"))
        return ok(self._enrollment_out(enrollment))

    # --- teachers -----------------------------------------------------------------
    def add_subject(self, code, name, category_id, active=True):
        sid = str(uuid.uuid4())
        category = self.categories[category_id]
        self.subjects[sid] = {
            "id": sid,
            "code": code,
            "name": name,
            "category": {k: category[k] for k in ("id", "code", "name", "active")},
            "subject_type": "THEORETICAL",
            "public_visible": False,
            "default_grading_scale": None,
            "active": active,
        }
        return sid

    def seed_teachers(self):
        """Two categories, four subjects, two teachers (one per category)."""
        self.sci = self.add_category("SCI", "Scientifique")
        self.lit = self.add_category("LIT", "Littéraire")
        self.math = self.add_subject("MATH", "Mathématiques", self.sci)
        self.phy = self.add_subject("PHY", "Physique", self.sci)
        self.fr = self.add_subject("FR", "Français", self.lit)
        self.mus = self.add_subject("MUS", "Musique", self.lit)
        self.tm = self.add_teacher("ENS-001", "Mbarga", "Jean", self.sci, self.math)
        self.tf = self.add_teacher("ENS-002", "Ngo", "Marie", self.lit, self.fr)

    def add_teacher(self, number, last, first, category_id, subject_id, email=None):
        tid = str(uuid.uuid4())
        self.teachers[tid] = {
            "id": tid,
            "teacher_number": number,
            "first_name": first,
            "last_name": last,
            "email": email or f"{first.lower()}.{last.lower()}@ecole.test",
            "phone": None,
            "pedagogical_category": category_id,
            "primary_subject": subject_id,
            "professional_status": "ACTIVE",
            "employment_status": "ACTIVE",
            "hire_date": None,
            "address": None,
            "qualification_summary": None,
            "bio": None,
        }
        self._qualify(tid, subject_id)
        return tid

    def _verdict(self, teacher, subject_id):
        if any(o["teacher"] == teacher["id"] and o["subject"]["id"] == subject_id for o in self.overrides):
            return "OVERRIDDEN", "override"
        rule = self.rules.get((teacher["pedagogical_category"], subject_id))
        if rule:
            return rule, {"COMPATIBLE": "rule_compatible", "REQUIRES_REVIEW": "rule_review"}.get(
                rule, "rule_incompatible"
            )
        if subject_id == teacher["primary_subject"]:
            return "COMPATIBLE", "primary_subject"
        if self.subjects[subject_id]["category"]["id"] == teacher["pedagogical_category"]:
            return "COMPATIBLE", "same_category"
        return "REQUIRES_REVIEW", "no_rule"

    def _qualify(self, teacher_id, subject_id):
        result, _ = self._verdict(self.teachers[teacher_id], subject_id)
        qid = str(uuid.uuid4())
        self.qualifications[qid] = {
            "id": qid,
            "teacher": teacher_id,
            "subject": subject_id,
            "status": "PENDING" if result == "REQUIRES_REVIEW" else "DECLARED",
            "source": "OVERRIDE" if result == "OVERRIDDEN" else "ADMIN",
            "computed_compatibility": result,
            "notes": None,
        }
        return qid

    def _ref(self, table, rid):
        row = table.get(rid)
        return {"id": row["id"], "code": row["code"], "name": row["name"]} if row else None

    def _qualification_out(self, row):
        subject = self.subjects[row["subject"]]
        teacher = self.teachers[row["teacher"]]
        return {
            **row,
            "subject": {**self._ref(self.subjects, row["subject"]), "category": subject["category"]["code"]},
            "verified": row["status"] == "VERIFIED",
            "current_compatibility": self._verdict(teacher, row["subject"])[0],
        }

    def _teacher_out(self, row):
        live = [q for q in self.qualifications.values() if q["teacher"] == row["id"] and q["status"] != "REJECTED"]
        return {
            **row,
            "pedagogical_category": self._ref(self.categories, row["pedagogical_category"]),
            "primary_subject": self._ref(self.subjects, row["primary_subject"]),
            "subjects": sorted(self.subjects[q["subject"]]["code"] for q in live),
            "active": row["professional_status"] == "ACTIVE" and row["employment_status"] == "ACTIVE",
            "account_activated": False,
            "active_course_count": 2 if row["id"] in self.teachers_in_use else 0,
            "upcoming_session_count": 0,
        }

    def _teachers(self, request, path, body, admin):
        method, params = request.method, request.url.params
        parts = path.strip("/").split("/")
        if path == "teachers/" and method == "GET":
            rows = [self._teacher_out(t) for t in self.teachers.values()]
            search = (params.get("search") or "").lower()
            if search:
                rows = [
                    r
                    for r in rows
                    if any(
                        search in (r[f] or "").lower() for f in ("last_name", "first_name", "email", "teacher_number")
                    )
                ]
            if params.get("status") in ("active", "inactive"):
                rows = [r for r in rows if r["active"] == (params["status"] == "active")]
            if params.get("category"):
                rows = [r for r in rows if r["pedagogical_category"]["id"] == params["category"]]
            if params.get("subject"):
                code = self.subjects[params["subject"]]["code"]
                rows = [r for r in rows if code in r["subjects"]]
            return self._page(sorted(rows, key=lambda r: (r["last_name"], r["first_name"])), request)
        if path == "admin/dashboard/teachers/":
            if not admin:
                return fail(403, "PERMISSION_DENIED", "Permission refusée.")
            active = [self._teacher_out(t) for t in self.teachers.values()]
            active = [t for t in active if t["active"]]
            codes = sorted({t["pedagogical_category"]["code"] for t in active})
            return ok(
                {
                    "active": len(active),
                    "by_category": [
                        {"code": c, "name": c, "count": sum(t["pedagogical_category"]["code"] == c for t in active)}
                        for c in codes
                    ],
                }
            )
        if path == "admin/payroll/teacher-rates/":
            return self._page(self.rates.get(params.get("teacher"), []), request)
        if not admin:
            return fail(403, "PERMISSION_DENIED", "Permission refusée.")
        if parts[0] == "teacher-qualifications":
            row = self.qualifications.get(parts[1])
            if row is None:
                return fail(404, "NOT_FOUND", "Qualification introuvable.")
            if parts[2] == "verify":
                row["status"] = "VERIFIED"
            else:
                if row["subject"] == self.teachers[row["teacher"]]["primary_subject"]:
                    return fail(409, "CONFLICT", "Matière principale.", {"rule": "primary_subject_qualification"})
                row.update(status="REJECTED", notes=body.get("reason"))
            return ok(self._qualification_out(row))
        if path == "teachers/" and method == "POST":
            return self._teacher_write(None, body)
        teacher = self.teachers.get(parts[1])
        if teacher is None:
            return fail(404, "NOT_FOUND", "Enseignant introuvable.")
        action = parts[2] if len(parts) > 2 else ""
        if action == "" and method == "GET":
            return ok(self._teacher_out(teacher))
        if action == "" and method == "PATCH":
            return self._teacher_write(teacher, body)
        if action == "deactivate":
            if teacher["id"] in self.teachers_in_use:
                return fail(
                    409, "CONFLICT", "Enseignant utilisé.", {"rule": "teacher_in_use", "context": {"courses": 2}}
                )
            teacher["professional_status"] = "INACTIVE"
            return ok(self._teacher_out(teacher))
        if action == "reactivate":
            teacher["professional_status"] = "ACTIVE"
            return ok(self._teacher_out(teacher))
        if action == "qualifications" and method == "GET":
            rows = [self._qualification_out(q) for q in self.qualifications.values() if q["teacher"] == teacher["id"]]
            return self._page(rows, request)
        if action == "qualifications":
            subject_id = body.get("subject")
            if subject_id not in self.subjects:
                return fail(404, "NOT_FOUND", "Matière introuvable.")
            if any(
                q["teacher"] == teacher["id"] and q["subject"] == subject_id and q["status"] != "REJECTED"
                for q in self.qualifications.values()
            ):
                return fail(409, "CONFLICT", "Déjà qualifié.", {"rule": "already_qualified"})
            if self._verdict(teacher, subject_id)[0] == "INCOMPATIBLE":
                return fail(400, "BUSINESS_RULE_VIOLATION", "Incompatible.", {"rule": "incompatible_subject"})
            return ok(self._qualification_out(self.qualifications[self._qualify(teacher["id"], subject_id)]), 201)
        if action == "compatibility":
            subject_id = params.get("subject")
            result, reason = self._verdict(teacher, subject_id)
            rule = self.rules.get((teacher["pedagogical_category"], subject_id))
            override = next(
                (o for o in self.overrides if o["teacher"] == teacher["id"] and o["subject"]["id"] == subject_id), None
            )
            existing = next(
                (
                    q
                    for q in self.qualifications.values()
                    if q["teacher"] == teacher["id"] and q["subject"] == subject_id
                ),
                None,
            )
            return ok(
                {
                    "subject": self._ref(self.subjects, subject_id),
                    "level": None,
                    "result": result,
                    "reason": reason,
                    "rule": {
                        "category": self.categories[teacher["pedagogical_category"]]["code"],
                        "subject": self._ref(self.subjects, subject_id),
                        "level": None,
                        "compatible": rule == "COMPATIBLE",
                        "requires_admin_review": rule == "REQUIRES_REVIEW",
                        "priority": 0,
                    }
                    if rule
                    else None,
                    "override": override,
                    "qualification_status": existing["status"] if existing else None,
                }
            )
        if action == "compatibility-rules":
            return ok(
                [
                    {
                        "category": self.categories[c]["code"],
                        "subject": self._ref(self.subjects, sid),
                        "level": None,
                        "compatible": verdict == "COMPATIBLE",
                        "requires_admin_review": verdict == "REQUIRES_REVIEW",
                        "priority": 0,
                    }
                    for (c, sid), verdict in self.rules.items()
                    if c == teacher["pedagogical_category"]
                ]
            )
        if action == "overrides" and method == "GET":
            return ok([o for o in self.overrides if o["teacher"] == teacher["id"]])
        if action == "overrides":
            if not (body.get("reason") or "").strip():
                return fail(400, "BUSINESS_RULE_VIOLATION", "Motif requis.", {"rule": "reason_required"})
            override = {
                "id": str(uuid.uuid4()),
                "teacher": teacher["id"],
                "subject": self._ref(self.subjects, body["subject"]),
                "level": None,
                "reason": body["reason"],
                "approved_by": "Ada Admin",
                "created_at": "2026-03-04T08:30:00+00:00",
                "expires_at": body.get("expires_at"),
                "active": True,
            }
            self.overrides.append(override)
            return ok(override, 201)
        return None

    # --- courses ------------------------------------------------------------------
    def _refusal(self, teacher, subject_id):
        """What the server's teacher_refusal would answer (fake engine)."""
        if teacher["professional_status"] != "ACTIVE" or teacher["employment_status"] != "ACTIVE":
            return "teacher_inactive"
        qualification = next(
            (q for q in self.qualifications.values() if q["teacher"] == teacher["id"] and q["subject"] == subject_id),
            None,
        )
        if qualification is None or qualification["status"] in ("PENDING", "REJECTED"):
            return "teacher_not_qualified"
        if self._verdict(teacher, subject_id)[0] == "INCOMPATIBLE":
            return "incompatible_subject"
        return None

    def add_course(self, class_id, subject_id, teacher_id, coefficient="1.00"):
        cid = str(uuid.uuid4())
        self.courses[cid] = {
            "id": cid,
            "school_class": class_id,
            "subject": subject_id,
            "teacher": teacher_id,
            "academic_year": self.classes[class_id]["academic_year"],
            "coefficient": coefficient,
            "weekly_hours": "0.00",
            "grading_scale": None,
            "active": True,
        }
        return cid

    def _course_out(self, row):
        klass, subject, teacher = (
            self.classes[row["school_class"]],
            self.subjects[row["subject"]],
            self.teachers[row["teacher"]],
        )
        level = self.levels[klass["level"]]
        return {
            **row,
            "class_name": klass["name"],
            "subject_code": subject["code"],
            "teacher_name": f"{teacher['first_name']} {teacher['last_name']}",
            "class_ref": {"id": klass["id"], "name": klass["name"], "active": klass["active"]},
            "level": {"id": level["id"], "code": level["code"], "name": level["name"]},
            "subject_ref": {"id": subject["id"], "code": subject["code"], "name": subject["name"], "active": True},
            "teacher_ref": {
                "id": teacher["id"],
                "number": teacher["teacher_number"],
                "name": f"{teacher['last_name']} {teacher['first_name']}",
                "category": self.categories[teacher["pedagogical_category"]]["code"],
            },
            "year": {"id": row["academic_year"], "name": self.year(row["academic_year"])["name"], "status": "ACTIVE"},
            "scale": {"id": "sc20", "code": "SUR20", "label": "/20"} if row["grading_scale"] == "sc20" else None,
            "published_slot_count": 1 if row["id"] in self.courses_scheduled else 0,
            "upcoming_session_count": 0,
        }

    def _courses(self, request, path, body, admin):
        method, params = request.method, request.url.params
        parts = path.strip("/").split("/")
        if path == "grading-scales/":
            return self._page([{"id": "sc20", "code": "SUR20", "label": "/20", "active": True}], request)
        if path == "courses/" and method == "GET":
            rows = [self._course_out(c) for c in self.courses.values()]
            for name in ("academic_year", "school_class", "subject"):
                if params.get(name):
                    rows = [r for r in rows if r[name] == params[name]]
            if params.get("status") in ("active", "inactive"):
                rows = [r for r in rows if r["active"] == (params["status"] == "active")]
            search = (params.get("search") or "").lower()
            if search:
                rows = [
                    r
                    for r in rows
                    if any(search in v.lower() for v in (r["subject_code"], r["class_name"], r["teacher_name"]))
                ]
            return self._page(sorted(rows, key=lambda r: (r["class_name"], r["subject_code"])), request)
        if not admin:
            return fail(403, "PERMISSION_DENIED", "Permission refusée.")
        if path == "courses/eligible-teachers/":
            subject_id = params.get("subject")
            eligible, excluded = [], []
            for teacher in self.teachers.values():
                if not any(
                    q["teacher"] == teacher["id"] and q["subject"] == subject_id and q["status"] != "REJECTED"
                    for q in self.qualifications.values()
                ):
                    continue
                ref = self._teacher_out(teacher)
                row = {
                    "id": teacher["id"],
                    "number": teacher["teacher_number"],
                    "name": f"{teacher['last_name']} {teacher['first_name']}",
                    "category": ref["pedagogical_category"]["code"],
                }
                refusal = self._refusal(teacher, subject_id)
                (excluded if refusal else eligible).append({**row, "reason": refusal} if refusal else row)
            return ok({"eligible": eligible, "excluded": excluded})
        if path == "courses/" and method == "POST":
            for name, table in (("school_class", self.classes), ("subject", self.subjects), ("teacher", self.teachers)):
                if body.get(name) not in table:
                    return fail(404, "NOT_FOUND", "Introuvable.")
            refusal = self._refusal(self.teachers[body["teacher"]], body["subject"])
            if refusal:
                return fail(400, "BUSINESS_RULE_VIOLATION", "Refusé.", {"rule": refusal})
            same = [
                c
                for c in self.courses.values()
                if c["school_class"] == body["school_class"] and c["subject"] == body["subject"]
            ]
            if any(c["teacher"] == body["teacher"] for c in same):
                return fail(409, "CONFLICT", "Doublon.", {"rule": "duplicate_course"})
            coefficient = body.get("coefficient") or "1.00"
            if any(c["active"] and float(c["coefficient"]) != float(coefficient) for c in same):
                return fail(409, "CONFLICT", "Coefficient.", {"rule": "course_coefficient_conflict"})
            cid = self.add_course(body["school_class"], body["subject"], body["teacher"], coefficient)
            self.courses[cid].update(
                weekly_hours=body.get("weekly_hours") or "0.00", grading_scale=body.get("grading_scale")
            )
            return ok(self._course_out(self.courses[cid]), 201)
        course = self.courses.get(parts[1])
        if course is None:
            return fail(404, "NOT_FOUND", "Cours introuvable.")
        action = parts[2] if len(parts) > 2 else ""
        if action == "" and method == "GET":
            return ok(self._course_out(course))
        if action == "deactivate":
            if course["id"] in self.courses_scheduled:
                return fail(409, "CONFLICT", "Planifié.", {"rule": "course_scheduled"})
            course["active"] = False
            return ok(self._course_out(course))
        if action == "reactivate":
            refusal = self._refusal(self.teachers[course["teacher"]], course["subject"])
            if refusal:
                return fail(400, "BUSINESS_RULE_VIOLATION", "Refusé.", {"rule": refusal})
            course["active"] = True
            return ok(self._course_out(course))
        if any(name in body and body[name] != course[name] for name in ("school_class", "subject")):
            return fail(409, "CONFLICT", "Identité.", {"rule": "course_identity_immutable"})
        if body.get("teacher") and body["teacher"] != course["teacher"]:
            if course["id"] in self.courses_scheduled:
                return fail(409, "CONFLICT", "Planifié.", {"rule": "course_scheduled"})
            refusal = self._refusal(self.teachers[body["teacher"]], course["subject"])
            if refusal:
                return fail(400, "BUSINESS_RULE_VIOLATION", "Refusé.", {"rule": refusal})
            course["teacher"] = body["teacher"]
        for name in ("coefficient", "weekly_hours", "grading_scale"):
            if name in body:
                course[name] = body[name] if body[name] is not None or name == "grading_scale" else course[name]
        return ok(self._course_out(course))

    def _teacher_write(self, teacher, body):
        fields = ("first_name", "last_name", "email", "employee_number", "pedagogical_category", "primary_subject")
        if teacher is None:
            missing = {f: ["Ce champ est obligatoire."] for f in fields if not body.get(f)}
            if missing:
                return fail(400, "VALIDATION_ERROR", "Données invalides.", missing)
        number = (body.get("employee_number") or "").lower()
        if number and any(t["teacher_number"].lower() == number and t is not teacher for t in self.teachers.values()):
            return fail(409, "CONFLICT", "Matricule utilisé.", {"rule": "duplicate_employee_number"})
        email = (body.get("email") or "").lower()
        if email and (
            email == "admin@school.local"
            or any(t["email"].lower() == email and t is not teacher for t in self.teachers.values())
        ):
            return fail(409, "CONFLICT", "E-mail utilisé.", {"rule": "email_in_use"})
        for name, table in (("pedagogical_category", self.categories), ("primary_subject", self.subjects)):
            if body.get(name) and body[name] not in table:
                return fail(404, "NOT_FOUND", "Introuvable.")
        if teacher is None:
            if self.rules.get((body["pedagogical_category"], body["primary_subject"])) == "INCOMPATIBLE":
                return fail(400, "BUSINESS_RULE_VIOLATION", "Incompatible.", {"rule": "incompatible_subject"})
            tid = self.add_teacher(
                body["employee_number"],
                body["last_name"],
                body["first_name"],
                body["pedagogical_category"],
                body["primary_subject"],
                email=body["email"],
            )
            teacher = self.teachers[tid]
            status = 201
        else:
            status = 200
            stops = (
                body.get("professional_status", "ACTIVE") != "ACTIVE"
                or body.get("employment_status", "ACTIVE") != "ACTIVE"
            )
            if stops and teacher["id"] in self.teachers_in_use:
                return fail(409, "CONFLICT", "Enseignant utilisé.", {"rule": "teacher_in_use"})
        renames = {"employee_number": "teacher_number"}
        for name, value in body.items():
            if name in teacher or name in renames:
                teacher[renames.get(name, name)] = value
        return ok(self._teacher_out(teacher), status=status)

    def log(self, action, label):
        self.activity.insert(
            0,
            {
                "id": str(uuid.uuid4()),
                "at": "2026-03-04T08:30:00+00:00",
                "action": action,
                "entity_type": "",
                "label": label,
                "actor": "Ada Admin",
            },
        )

    def year(self, year_id):
        return next((y for y in self.years if y["id"] == year_id), None)

    def _year_out(self, year):
        count = sum(1 for c in self.classes.values() if c["academic_year"] == year["id"] and c["active"])
        return {**year, "class_count": count}

    def _level_out(self, level):
        open_years = {y["id"] for y in self.years if y["status"] in ("PLANNED", "ACTIVE")}
        count = sum(
            1
            for c in self.classes.values()
            if c["level"] == level["id"] and c["active"] and c["academic_year"] in open_years
        )
        return {**level, "class_count": count}

    def _years(self, request, path, body, admin):
        method = request.method
        if path == "academic-years/" and method == "GET":
            return self._page([self._year_out(y) for y in self.years], request)
        if method != "GET" and not admin:
            return fail(403, "PERMISSION_DENIED", "Permission refusée.")
        parts = path.split("/")
        year = self.year(parts[1]) if len(parts) > 2 and parts[1] else None
        if len(parts) > 2 and parts[1] and year is None:
            return fail(404, "NOT_FOUND", "Année introuvable.")
        if method == "GET":
            return ok(self._year_out(year))
        if year is not None and year["status"] not in ("PLANNED", "ACTIVE"):
            return fail(400, "BUSINESS_RULE_VIOLATION", "Année clôturée.", {"rule": "year_closed"})
        action = parts[2] if len(parts) > 3 else ""
        if action == "set-current":
            for other in self.years:
                other["is_current"] = False
            year.update(is_current=True, status="ACTIVE")
            self.log("ACADEMIC_YEAR_SET_CURRENT", year["name"])
            return ok(self._year_out(year))
        if action == "close":
            if year["is_current"]:
                return fail(409, "CONFLICT", "Année courante.", {"rule": "year_is_current"})
            if year["id"] in self.years_with_pupils:
                return fail(409, "CONFLICT", "Élèves inscrits.", {"rule": "year_has_active_enrollments"})
            year["status"] = "CLOSED"
            self.log("ACADEMIC_YEAR_CLOSED", year["name"])
            return ok(self._year_out(year))
        merged = {**(year or {}), **body}
        missing = {f: ["Ce champ est obligatoire."] for f in ("name", "start_date", "end_date") if not merged.get(f)}
        if missing:
            return fail(400, "VALIDATION_ERROR", "Données invalides.", missing)
        if merged["end_date"] <= merged["start_date"]:
            return fail(400, "BUSINESS_RULE_VIOLATION", "Dates invalides.", {"rule": "invalid_dates"})
        others = [y for y in self.years if y is not year]
        if any(y["name"].lower() == merged["name"].strip().lower() for y in others):
            return fail(409, "CONFLICT", "Nom déjà utilisé.", {"rule": "duplicate_year_name"})
        if any(y["start_date"] <= merged["end_date"] and y["end_date"] >= merged["start_date"] for y in others):
            return fail(409, "CONFLICT", "Chevauchement.", {"rule": "year_overlap"})
        if year is None:
            year = {"id": str(uuid.uuid4()), "status": "PLANNED", "is_current": False}
            self.years.append(year)
            self.log("ACADEMIC_YEAR_CREATED", merged["name"].strip())
            status = 201
        else:
            status = 200
            self.log("ACADEMIC_YEAR_UPDATED", merged["name"].strip())
        year.update(name=merged["name"].strip(), start_date=merged["start_date"], end_date=merged["end_date"])
        return ok(self._year_out(year), status=status)

    def _levels(self, request, path, body, admin):
        method = request.method
        if path == "levels/" and method == "GET":
            rows = self._filter(list(self.levels.values()), request, fields=("code", "name", "cycle"))
            return self._page([self._level_out(lv) for lv in rows], request)
        if method != "GET" and not admin:
            return fail(403, "PERMISSION_DENIED", "Permission refusée.")
        parts = path.split("/")
        level = self.levels.get(parts[1]) if len(parts) > 2 and parts[1] else None
        if len(parts) > 2 and parts[1] and level is None:
            return fail(404, "NOT_FOUND", "Niveau introuvable.")
        if method == "GET":
            return ok(self._level_out(level))
        action = parts[2] if len(parts) > 3 else ""
        if action in ("deactivate", "reactivate"):
            if action == "deactivate" and self._level_out(level)["class_count"]:
                return fail(409, "CONFLICT", "Niveau utilisé.", {"rule": "level_in_use"})
            level["active"] = action == "reactivate"
            self.log("LEVEL_ACTIVATED" if level["active"] else "LEVEL_DEACTIVATED", level["name"])
            return ok(self._level_out(level))
        fields = ("name", "cycle", "order_index", "first_character", "public_visible")
        if level is None:
            if not body.get("code") or not body.get("name"):
                return fail(400, "VALIDATION_ERROR", "Données invalides.", {"code": ["Ce champ est obligatoire."]})
            code = body["code"].strip().upper()
            if any(lv["code"] == code for lv in self.levels.values()):
                return fail(409, "CONFLICT", "Ce code existe déjà.", {"rule": "duplicate_code"})
            lid = self.add_level(code, body["name"].strip(), body.get("order_index", 0))
            self.levels[lid].update({k: v for k, v in body.items() if k in fields})
            self.log("LEVEL_CREATED", self.levels[lid]["name"])
            return ok(self._level_out(self.levels[lid]), status=201)
        if "code" in body and body["code"].strip().upper() != level["code"]:
            return fail(400, "BUSINESS_RULE_VIOLATION", "Code non modifiable.", {"rule": "code_immutable"})
        level.update({k: v for k, v in body.items() if k in fields})
        self.log("LEVEL_UPDATED", level["name"])
        return ok(self._level_out(level))

    def _dashboard(self, request, path, admin):
        if not admin:
            return fail(403, "PERMISSION_DENIED", "Permission refusée.")
        if path == "admin/dashboard/attendance-trend/":
            return ok({"date_from": "2026-02-20", "date_to": "2026-03-05", "days": self.attendance_days})
        if path == "admin/dashboard/enrollments/":
            return ok(self.enrollments)
        if path == "admin/dashboard/activity/":
            return ok(self.activity[: int(request.url.params.get("limit", 10))])
        if path == "admin/finance/dashboard/":
            return ok(self.finance)
        return None

    def add_class(self, name, level="l6", year="y1", room=None, active=True):
        cid = str(uuid.uuid4())
        self.classes[cid] = {
            "id": cid,
            "name": name,
            "level": level,
            "academic_year": year,
            "capacity": None,
            "main_room": room,
            "public_visible": False,
            "active": active,
        }
        return cid

    def _class_out(self, row):
        level, year = self.levels[row["level"]], next(y for y in self.years if y["id"] == row["academic_year"])
        room = self.rooms.get(row["main_room"]) if row["main_room"] else None
        return {
            **row,
            "level_code": level["code"],
            "level_name": level["name"],
            "academic_year_name": year["name"],
            "main_room_name": f"{room['code']} — {room['name']}" if room else None,
        }

    def _classes(self, request, path, body, admin):
        method = request.method
        if path == "classes/" and method == "GET":
            params = request.url.params
            rows = [self._class_out(c) for c in self.classes.values()]
            search = (params.get("search") or "").lower()
            if search:
                rows = [r for r in rows if search in r["name"].lower() or search in r["level_name"].lower()]
            if params.get("active") in ("true", "false"):
                rows = [r for r in rows if r["active"] == (params["active"] == "true")]
            for param in ("academic_year", "level"):
                if params.get(param):
                    rows = [r for r in rows if r[param] == params[param]]
            return self._page(sorted(rows, key=lambda r: r["name"]), request)
        if not admin and method != "GET":
            return fail(403, "PERMISSION_DENIED", "Permission refusée.")
        parts = path.split("/")
        current = self.classes.get(parts[1]) if len(parts) > 2 and parts[1] else None
        if len(parts) > 2 and parts[1] and current is None:
            return fail(404, "NOT_FOUND", "Classe introuvable.")
        if method == "POST" and len(parts) > 3 and parts[2] in ("deactivate", "reactivate"):
            if parts[2] == "deactivate" and current["id"] in self.classes_in_use:
                return fail(409, "CONFLICT", "Classe utilisée.", {"rule": "class_in_use"})
            current["active"] = parts[2] == "reactivate"
            return ok(self._class_out(current))
        if method == "GET":
            return ok(self._class_out(current))
        merged = {**(current or {}), **body}
        missing = {f: ["Ce champ est obligatoire."] for f in ("name", "level", "academic_year") if not merged.get(f)}
        if missing:
            return fail(400, "VALIDATION_ERROR", "Données invalides.", missing)
        if merged["level"] not in self.levels or merged["academic_year"] not in {y["id"] for y in self.years}:
            return fail(404, "NOT_FOUND", "Introuvable.")
        if merged.get("main_room") and merged["main_room"] not in self.rooms:
            return fail(404, "NOT_FOUND", "Salle introuvable.")
        if current is not None and body.get("academic_year", current["academic_year"]) != current["academic_year"]:
            return fail(409, "CONFLICT", "Année non modifiable.", {"rule": "class_year_immutable"})
        year = next(y for y in self.years if y["id"] == merged["academic_year"])
        if year["status"] not in ("PLANNED", "ACTIVE"):
            return fail(400, "BUSINESS_RULE_VIOLATION", "Année clôturée.", {"rule": "year_closed"})
        if any(
            c["academic_year"] == merged["academic_year"]
            and c["name"].lower() == merged["name"].lower()
            and c is not current
            for c in self.classes.values()
        ):
            return fail(409, "CONFLICT", "Nom déjà utilisé.", {"rule": "duplicate_class_name"})
        if current is None:
            self.log("CLASS_CREATED", merged["name"])
            cid = self.add_class(merged["name"], merged["level"], merged["academic_year"], merged.get("main_room"))
            self.classes[cid].update(
                capacity=merged.get("capacity"), public_visible=merged.get("public_visible", False)
            )
            return ok(self._class_out(self.classes[cid]), status=201)
        current.update(
            {k: v for k, v in body.items() if k in ("name", "level", "capacity", "main_room", "public_visible")}
        )
        return ok(self._class_out(current))

    def _page(self, rows, request):
        page = int(request.url.params.get("page", 1))
        size = int(request.url.params.get("page_size", 25))
        chunk = rows[(page - 1) * size : page * size]
        more = page * size < len(rows)
        return ok(chunk, meta={"count": len(rows), "next": "next" if more else None, "previous": None})

    @staticmethod
    def _filter(rows, request, fields=("code", "name")):
        search = (request.url.params.get("search") or "").lower()
        active = request.url.params.get("active")
        if search:
            rows = [r for r in rows if any(search in r[f].lower() for f in fields)]
        if active in ("true", "false"):
            rows = [r for r in rows if r["active"] == (active == "true")]
        return rows

    # --- transport ------------------------------------------------------------------

    def __call__(self, request):
        path = request.url.path.removeprefix("/api/v1/")
        self.calls.append((request.method, path))
        if self.offline:
            raise httpx.ConnectError("offline", request=request)
        if (request.method, path) in self.forced:
            return self.forced[(request.method, path)]
        is_json = request.headers.get("content-type", "").startswith("application/json")
        body = json.loads(request.content) if request.content and is_json else {}
        if path == "auth/login/":
            self.login_bodies.append(body)
            if body.get("identifier") == "admin" and body.get("password") == PASSWORD:
                return ok(self._issue())
            return fail(401, "INVALID_CREDENTIALS", "Identifiants invalides.")
        if path == "auth/refresh/":
            token = body.get("refresh_token")
            if token in self.refresh_tokens and token not in self.revoked:
                self.refresh_tokens.discard(token)  # rotation
                return ok(self._issue())
            return fail(401, "INVALID_REFRESH_TOKEN", "Session expirée.")
        auth = request.headers.get("Authorization", "")
        access = auth.removeprefix("Bearer ")
        if access not in self.sessions:
            return fail(401, "NOT_AUTHENTICATED", "Authentification requise.")
        if path == "auth/logout/":
            self.revoked.add(self.sessions.pop(access))
            return ok(None)
        if path == "auth/me/":
            return ok(
                {
                    "id": "u1",
                    "username": "admin",
                    "email": "admin@school.local",
                    "first_name": "Ada",
                    "last_name": "Admin",
                    "memberships": [
                        {
                            "id": "m1",
                            "school_code": "TEST01",
                            "school_name": "École Test",
                            "status": "ACTIVE",
                            "is_primary_school": True,
                            "roles": self.roles,
                        }
                    ],
                }
            )
        admin = bool({"SUPER_ADMIN", "ADMIN"} & set(self.roles))
        return self._catalogue(request, path, body, admin) or fail(404, "NOT_FOUND", "Introuvable.")

    def _catalogue(self, request, path, body, admin):
        method = request.method
        if path == "school/":
            return ok({"id": "s1", "code": "TEST01", "name": "École Test", "city": "Douala"})
        if path.startswith("levels/"):
            return self._levels(request, path, body, admin)
        if path.startswith("courses/") or path == "grading-scales/":
            return self._courses(request, path, body, admin)
        if (
            path.startswith("teachers/")
            or path.startswith("teacher-qualifications/")
            or path in ("admin/dashboard/teachers/", "admin/payroll/teacher-rates/")
        ):
            return self._teachers(request, path, body, admin)
        if path.startswith("admin/dashboard/") or path == "admin/finance/dashboard/":
            return self._dashboard(request, path, admin)
        if path == "rooms/":
            rows = list(self.rooms.values())
            if request.url.params.get("active") == "true":
                rows = [r for r in rows if r["active"]]
            return self._page(rows, request)
        if path.startswith("classes/"):
            return self._classes(request, path, body, admin)
        if path.startswith("academic-years/"):
            return self._years(request, path, body, admin)
        if path.startswith("students/") or path.startswith("enrollments/"):
            return self._students(request, path, body, admin)
        if path == "sessions/":
            sizes = {"sessions/": 37}
            return self._page([{"id": str(i)} for i in range(sizes[path])], request)
        if path == "admin/attendance/dashboard/":
            return fail(400, "BUSINESS_RULE_VIOLATION", "Aucune politique de présence.", {"rule": "no_policy"})
        if path == "pedagogical-categories/":
            if method == "GET":
                return self._page(
                    self._filter(sorted(self.categories.values(), key=lambda c: c["code"]), request), request
                )
            if not admin:
                return fail(403, "PERMISSION_DENIED", "Permission refusée.")
            code = body.get("code", "").upper()
            if any(c["code"] == code for c in self.categories.values()):
                return fail(409, "CONFLICT", "Ce code existe déjà.", {"rule": "duplicate_code"})
            cid = self.add_category(code, body["name"])
            self.categories[cid]["description"] = body.get("description")
            return ok(self.categories[cid], status=201)
        if path.startswith("pedagogical-categories/"):
            parts = path.split("/")
            category = self.categories.get(parts[1])
            if category is None:
                return fail(404, "NOT_FOUND", "Catégorie introuvable.")
            if not admin and method != "GET":
                return fail(403, "PERMISSION_DENIED", "Permission refusée.")
            if method == "PATCH":
                category.update({k: v for k, v in body.items() if k in ("name", "description")})
            elif parts[2] in ("deactivate", "reactivate"):
                in_use = any(s["category"]["id"] == category["id"] and s["active"] for s in self.subjects.values())
                if parts[2] == "deactivate" and in_use:
                    return fail(
                        409, "CONFLICT", "Catégorie utilisée par des matières actives.", {"rule": "category_in_use"}
                    )
                category["active"] = parts[2] == "reactivate"
            return ok(category)
        if path == "subjects/":
            if method == "GET":
                rows = self._filter(sorted(self.subjects.values(), key=lambda s: s["code"]), request)
                category = request.url.params.get("category")
                if category:
                    rows = [r for r in rows if r["category"]["id"] == category]
                return self._page(rows, request)
            if not admin:
                return fail(403, "PERMISSION_DENIED", "Permission refusée.")
            if not body.get("category"):
                return fail(400, "VALIDATION_ERROR", "Données invalides.", {"category": ["Ce champ est obligatoire."]})
            category = self.categories.get(body["category"])
            if category is None:
                return fail(404, "NOT_FOUND", "Catégorie introuvable.")
            sid = str(uuid.uuid4())
            self.subjects[sid] = {
                "id": sid,
                "code": body["code"].upper(),
                "name": body["name"],
                "category": {k: category[k] for k in ("id", "code", "name", "active")},
                "subject_type": body.get("subject_type", "THEORETICAL"),
                "public_visible": body.get("public_visible", False),
                "default_grading_scale": None,
                "active": True,
            }
            return ok(self.subjects[sid], status=201)
        if path.startswith("subjects/"):
            parts = path.split("/")
            subject = self.subjects.get(parts[1])
            if subject is None:
                return fail(404, "NOT_FOUND", "Matière introuvable.")
            if method == "PATCH":
                subject.update({k: v for k, v in body.items() if k in ("name", "subject_type", "public_visible")})
                if body.get("category"):
                    category = self.categories[body["category"]]
                    subject["category"] = {k: category[k] for k in ("id", "code", "name", "active")}
            elif parts[2] in ("deactivate", "reactivate"):
                subject["active"] = parts[2] == "reactivate"
            return ok(subject)
        return None

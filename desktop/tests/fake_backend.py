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
        body = json.loads(request.content) if request.content else {}
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
        if path in ("students/", "teachers/", "sessions/"):
            sizes = {"students/": 120, "teachers/": 9, "sessions/": 37}
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

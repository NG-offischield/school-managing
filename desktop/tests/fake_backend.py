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
        if path == "academic-years/":
            return self._page(
                [
                    {
                        "id": "y1",
                        "name": "2025-2026",
                        "start_date": "2025-09-01",
                        "end_date": "2026-07-31",
                        "status": "ACTIVE",
                        "is_current": True,
                    }
                ],
                request,
            )
        if path in ("classes/", "students/", "teachers/", "sessions/"):
            sizes = {"classes/": 4, "students/": 120, "teachers/": 9, "sessions/": 37}
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

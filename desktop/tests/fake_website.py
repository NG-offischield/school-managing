"""Fake of backend apps/website/admin_api.py and apps/admissions/admin_api.py for
the desktop tests: the CONTRACT the desktop relies on — server-decided
transitions, reason required for a refusal, invitation link shown once for an
ACCEPTED request only, contents never deleted, release APKs refused when
unsigned / debug, readiness codes — not the backend's logic."""

import uuid

import httpx

from .fake_comm import multipart

NOW = "2026-10-14T10:00:00+01:00"
TRANSITIONS = {
    "RECEIVED": ["INFO_REQUESTED", "REJECTED", "UNDER_REVIEW"],
    "UNDER_REVIEW": ["ACCEPTED", "INFO_REQUESTED", "REJECTED"],
    "INFO_REQUESTED": ["REJECTED", "UNDER_REVIEW"],
    "ACCEPTED": [],
    "REJECTED": [],
}
LABELS = {
    "RECEIVED": "Reçue",
    "UNDER_REVIEW": "En examen",
    "INFO_REQUESTED": "Informations demandées",
    "ACCEPTED": "Acceptée",
    "REJECTED": "Refusée",
}


class WebsiteFake:
    def init_website(self):
        self.requests = {}
        self.request_events = {}
        self.invitations = {}  # request id -> number issued
        self.contents = {kind: {} for kind in ("pages", "faq", "news", "locations", "resources", "images")}
        self.releases = {}
        self.site_profile = {
            "tagline": "Apprendre et grandir",
            "presentation": "",
            "values": "",
            "pedagogy": "",
            "location_details": "Etoug-Ebe, Yaoundé",
            "office_hours": "",
            "address_confirmed": False,
            "to_validate": True,
        }
        self.website_uploads = []  # raw multipart bodies (privacy checks: no local path sent)

    @staticmethod
    def _w_ok(data, status=200, meta=None):
        return httpx.Response(status, json={"success": True, "data": data, "message": None, "meta": meta})

    @staticmethod
    def _w_fail(status, code, rule=None, message="Refusé.", details=None):
        details = {"rule": rule} if rule else details
        return httpx.Response(
            status, json={"success": False, "error": {"code": code, "message": message, "details": details}}
        )

    # --- data ---------------------------------------------------------------------------
    def add_request(self, last="Atangana", first="Mireille", child="Paul", status="RECEIVED", reference=None):
        rid = str(uuid.uuid4())
        number = len(self.requests) + 1
        self.requests[rid] = {
            "id": rid,
            "reference": reference or f"PRE-2026-{number:04d}",
            "guardian_first_name": first,
            "guardian_last_name": last,
            "guardian_phone": "+237 690 00 00 00",
            "guardian_email": f"{first.lower()}.{last.lower()}@famille.test",
            "relationship": "MOTHER",
            "relationship_label": "Mère",
            "child_first_name": child,
            "child_last_name": last,
            "child_birth_date": "2015-03-02",
            "requested_level": "Sixième",
            "requested_year": "2026-2027",
            "previous_school": "",
            "comment": "",
            "consent_at": NOW,
            "consent_version": "2026-10-provisoire",
            "status": status,
            "status_label": LABELS[status],
            "submitted_at": NOW,
            "decided_at": None,
            "message_to_family": "",
            "has_account": False,
        }
        self.request_events[rid] = [
            {
                "action": "SUBMITTED",
                "from_status": "",
                "to_status": "RECEIVED",
                "note": "",
                "actor": None,
                "created_at": NOW,
            }
        ]
        return rid

    def add_content(self, table, /, **values):
        cid = str(uuid.uuid4())
        row = {
            "id": cid,
            "status": "DRAFT",
            "to_validate": False,
            "is_demo": False,
            "order": 0,
            "audiences": ["PUBLIC"] if table != "resources" else ["PARENT"],
            "updated_at": NOW,
            **values,
        }
        self.contents[table][cid] = row
        return cid

    def add_release(self, app="PARENT", version_name="1.0.0", version_code=1, status="DRAFT"):
        rel = str(uuid.uuid4())
        self.releases[rel] = {
            "id": rel,
            "app": app,
            "version_name": version_name,
            "version_code": version_code,
            "release_notes": "",
            "min_android": "8.0",
            "file_name": "app-release.apk",
            "size": 25 * 1024 * 1024,
            "sha256": "a" * 64,
            "status": status,
            "published_at": NOW if status == "PUBLISHED" else None,
            "created_at": NOW,
        }
        return rel

    # --- routes -------------------------------------------------------------------------
    def _website(self, request, path, body, admin):
        if not admin:
            return self._w_fail(403, "PERMISSION_DENIED")
        if path.startswith("admin/pre-enrollments/"):
            return self._pre_enrollments(request, path, body)
        method = request.method
        parts = [p for p in path.removeprefix("admin/website/").split("/") if p]
        head = parts[0] if parts else ""
        if head == "profile":
            if method == "PATCH":
                self.site_profile.update({k: v for k, v in body.items() if k in self.site_profile})
            return self._w_ok(self.site_profile)
        if head == "readiness":
            items = []
            if not self.site_profile["address_confirmed"]:
                items.append(
                    {
                        "code": "address_unconfirmed",
                        "severity": "blocking",
                        "message": "Adresse exacte de l'établissement non confirmée.",
                        "count": None,
                    }
                )
            if not any(r["status"] == "PUBLISHED" and r["app"] == "PARENT" for r in self.releases.values()):
                items.append({"code": "app_parent", "severity": "warning", "message": "…", "count": None})
            return self._w_ok({"ready": not any(i["severity"] == "blocking" for i in items), "items": items})
        if head == "releases":
            return self._releases(request, parts, body)
        if head == "images" and len(parts) > 1 and parts[1] == "upload":
            fields, files = multipart(request)
            self.website_uploads.append(request.content)
            if not files:
                return self._w_fail(400, "VALIDATION_ERROR", details={"file": ["A file is required."]})
            cid = self.add_content(
                "images",
                alt_text=fields.get("alt_text", [""])[0],
                caption=fields.get("caption", [""])[0],
                credit=fields.get("credit", [""])[0],
                category=fields.get("category", ["OTHER"])[0],
                in_gallery=fields.get("in_gallery", ["false"])[0] == "true",
                is_illustration=fields.get("is_illustration", ["false"])[0] == "true",
                audiences=fields.get("audiences", ["PUBLIC"]),
                status=fields.get("status", ["DRAFT"])[0],
            )
            return self._w_ok(self.contents["images"][cid], 201)
        if head == "resources" and len(parts) > 2 and parts[2] == "document":
            row = self.contents["resources"].get(parts[1])
            if row is None:
                return self._w_fail(404, "NOT_FOUND")
            _, files = multipart(request)
            self.website_uploads.append(request.content)
            if not files[0][2].startswith(b"%PDF"):
                return self._w_fail(400, "BUSINESS_RULE_VIOLATION", "document_invalid", "Not a PDF document.")
            row.update(document_name=files[0][1], document_size=len(files[0][2]))
            return self._w_ok(row)
        table = self.contents.get(head)
        if table is None:
            return self._w_fail(404, "NOT_FOUND")
        if len(parts) == 1:
            if method == "GET":
                rows = list(table.values())
                wanted = request.url.params.get("status")
                return self._w_ok([r for r in rows if not wanted or r["status"] == wanted])
            if method == "POST":
                if head == "images":
                    return self._w_fail(404, "NOT_FOUND")
                cid = self.add_content(head, **body)
                return self._w_ok(table[cid], 201)
        row = table.get(parts[1])
        if row is None:
            return self._w_fail(404, "NOT_FOUND")
        if method == "PATCH":
            row.update(body)
        if method == "DELETE":
            return self._w_fail(405, "METHOD_NOT_ALLOWED")  # nothing is deleted
        return self._w_ok(row)

    def _pre_enrollments(self, request, path, body):
        parts = [p for p in path.removeprefix("admin/pre-enrollments/").split("/") if p]
        if not parts:
            rows = list(self.requests.values())
            status = request.url.params.get("status")
            search = (request.url.params.get("search") or "").lower()
            rows = [
                r
                for r in rows
                if (not status or r["status"] == status)
                and (
                    not search or search in f"{r['reference']} {r['guardian_last_name']} {r['guardian_email']}".lower()
                )
            ]
            return self._page(rows, request)
        row = self.requests.get(parts[0])
        if row is None:
            return self._w_fail(404, "NOT_FOUND")
        action = parts[1] if len(parts) > 1 else None
        if action is None:
            count = self.invitations.get(row["id"], 0)
            return self._w_ok(
                {
                    **row,
                    "events": self.request_events[row["id"]],
                    "invitation": {"state": "PENDING" if count else "NONE", "expires_at": None, "count": count},
                    "allowed": TRANSITIONS[row["status"]],
                }
            )
        if action == "status":
            target = body.get("status")
            if target not in TRANSITIONS[row["status"]]:
                return self._w_fail(
                    400, "BUSINESS_RULE_VIOLATION", "invalid_transition", "This status change is not allowed."
                )
            if target in ("REJECTED", "INFO_REQUESTED") and not (body.get("note") or "").strip():
                return self._w_fail(400, "BUSINESS_RULE_VIOLATION", "reason_required", "A reason is required.")
            self.request_events[row["id"]].append(
                {
                    "action": "STATUS_CHANGED",
                    "from_status": row["status"],
                    "to_status": target,
                    "note": body.get("note", ""),
                    "actor": "Ada Admin",
                    "created_at": NOW,
                }
            )
            row.update(status=target, status_label=LABELS[target])
            if body.get("message_to_family") is not None:
                row["message_to_family"] = body["message_to_family"]
            if target in ("ACCEPTED", "REJECTED"):
                row["decided_at"] = NOW
            return self._w_ok(row)
        if action == "invite":
            if row["status"] != "ACCEPTED":
                return self._w_fail(
                    400, "BUSINESS_RULE_VIOLATION", "not_accepted", "Only an accepted request can be invited."
                )
            self.invitations[row["id"]] = self.invitations.get(row["id"], 0) + 1
            row["has_account"] = True
            code = uuid.uuid4().hex
            return self._w_ok(
                {
                    "code": code,
                    "link": f"http://localhost:3001/activation#code={code}",
                    "expires_at": "2026-10-16T10:00:00+01:00",
                },
                201,
            )
        return self._w_fail(404, "NOT_FOUND")

    def _releases(self, request, parts, body):
        if len(parts) == 1:
            if request.method == "GET":
                return self._w_ok(list(self.releases.values()))
            fields, files = multipart(request)
            self.website_uploads.append(request.content)
            content = files[0][2] if files else b""
            if b"Android Debug" in content:
                return self._w_fail(400, "BUSINESS_RULE_VIOLATION", "apk_debug_build", "A debug-signed APK is refused.")
            if not content.startswith(b"PK"):
                return self._w_fail(400, "BUSINESS_RULE_VIOLATION", "apk_invalid", "Not an Android package.")
            code = int(fields["version_code"][0])
            if any(r["app"] == fields["app"][0] and r["version_code"] == code for r in self.releases.values()):
                return self._w_fail(400, "BUSINESS_RULE_VIOLATION", "version_code_exists", "This version code exists.")
            rel = self.add_release(fields["app"][0], fields["version_name"][0], code)
            self.releases[rel].update(
                file_name=files[0][1], size=len(content), min_android=fields.get("min_android", [""])[0]
            )
            return self._w_ok(self.releases[rel], 201)
        release = self.releases.get(parts[1])
        if release is None:
            return self._w_fail(404, "NOT_FOUND")
        release["status"] = body["status"]
        release["published_at"] = NOW if body["status"] == "PUBLISHED" else release["published_at"]
        return self._w_ok(release)

    def seed_website(self):
        self.add_request("Atangana", "Mireille", "Paul")
        self.add_request("Mbarga", "Jean", "Lucie", status="UNDER_REVIEW")
        self.add_request("Ngono", "Alice", "Eric", status="ACCEPTED")
        self.add_content("pages", kind="ABOUT", slug="a-propos", title="Qui sommes-nous", summary="", body="Texte")
        self.add_content(
            "faq", category="ADMISSIONS", question="Comment s'inscrire", answer="Ainsi.", status="PUBLISHED"
        )
        self.add_content(
            "news", slug="rentree", title="Rentrée 2026", summary="Bientôt.", category="NEWS", body="", event_date=None
        )
        self.add_content(
            "locations", name="Campus Horizon", description="", address_text="", is_main=False, is_demo=True
        )
        self.add_content(
            "resources",
            kind="SUPPLIES",
            title="Fournitures 6e",
            body="",
            level=None,
            school_class=None,
            academic_year=None,
            visible_from=None,
            visible_until=None,
            document_name="",
            document_size=None,
        )
        self.add_content(
            "images",
            alt_text="Une salle de classe",
            caption="",
            credit="",
            category="CLASSROOMS",
            in_gallery=True,
            is_illustration=True,
            width=400,
            height=300,
            size=1000,
        )
        self.add_release("PARENT", "1.0.0", 1, "PUBLISHED")

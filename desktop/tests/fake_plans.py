"""Fake of backend documents/plans_api.py (school plans) for the desktop tests:
the CONTRACT the desktop relies on — content-decided type (magic bytes),
DRAFT versions until published, one published version, MANUAL needs an
audience, 409 rules, raw bytes for previews — not the backend's logic."""

import uuid

import httpx

from .fake_comm import multipart

PLAN_MAGIC = ((b"%PDF-", "application/pdf"), (b"\x89PNG\r\n\x1a\n", "image/png"), (b"\xff\xd8\xff", "image/jpeg"))
NOW = "2026-03-04T10:00:00+01:00"


class PlansFake:
    def init_plans(self):
        self.plans = {}
        self.plan_files = {}  # version id -> bytes
        self.plan_uploads = []  # raw multipart bodies (privacy checks: no local path sent)

    @staticmethod
    def _p_ok(data, status=200, meta=None):
        return httpx.Response(status, json={"success": True, "data": data, "message": None, "meta": meta})

    @staticmethod
    def _p_fail(status, code, rule=None, message="Refusé."):
        details = {"rule": rule} if rule else None
        return httpx.Response(
            status, json={"success": False, "error": {"code": code, "message": message, "details": details}}
        )

    def add_plan(self, title, *, building="", floor="", distribution="AUTO", status="DRAFT"):
        pid = str(uuid.uuid4())
        self.plans[pid] = {
            "id": pid,
            "title": title,
            "description": "",
            "building": building,
            "floor": floor,
            "display_order": 0,
            "status": status,
            "distribution": distribution,
            "versions": [],
            "current": None,
            "published_at": None,
            "audience": [],
        }
        return pid

    def add_plan_version(self, pid, content=b"%PDF-1.7 fake", mime="application/pdf", name="plan.pdf"):
        plan = self.plans[pid]
        vid = str(uuid.uuid4())
        plan["versions"].append(
            {
                "id": vid,
                "number": len(plan["versions"]) + 1,
                "status": "DRAFT",
                "original_name": name,
                "mime_type": mime,
                "size_bytes": len(content),
                "sha256": "0" * 64,
                "width": 1600 if mime.startswith("image/") else None,
                "height": 1200 if mime.startswith("image/") else None,
                "page_count": 1 if mime == "application/pdf" else None,
                "uploaded_by_name": "Admin Test",
                "uploaded_at": NOW,
                "published_at": None,
            }
        )
        self.plan_files[vid] = content
        return vid

    def _version_out(self, plan, version):
        return {**version, "is_current": plan["current"] == version["id"]}

    def _plan_out(self, plan):
        current = next((v for v in plan["versions"] if v["id"] == plan["current"]), None)
        return {
            **{k: v for k, v in plan.items() if k not in ("versions", "current")},
            "current_version": self._version_out(plan, current) if current else None,
            "published_by_name": "Admin Test" if plan["published_at"] else None,
            "versions_count": len(plan["versions"]),
            "created_at": NOW,
        }

    def _plans(self, request, path, body, admin):
        if not admin:
            return self._p_fail(403, "PERMISSION_DENIED")
        method = request.method
        parts = [p for p in path.removeprefix("admin/plans/").split("/") if p]
        if not parts:
            if method == "GET":
                rows = list(self.plans.values())
                if request.url.params.get("status"):
                    rows = [r for r in rows if r["status"] == request.url.params["status"]]
                return self._page([self._plan_out(r) for r in rows], request)
            if not (body.get("title") or "").strip():
                return self._p_fail(400, "VALIDATION_ERROR", message="Titre obligatoire.")
            pid = self.add_plan(
                body["title"],
                building=body.get("building", ""),
                floor=body.get("floor", ""),
                distribution=body.get("distribution", "AUTO"),
            )
            self.plans[pid].update(description=body.get("description", ""), display_order=body.get("display_order", 0))
            return self._p_ok(self._plan_out(self.plans[pid]), 201)
        plan = self.plans.get(parts[0])
        if plan is None:
            return self._p_fail(404, "NOT_FOUND")
        action = parts[1] if len(parts) > 1 else None
        if action is None:
            if method == "PATCH":
                if body.get("distribution") == "MANUAL" and plan["status"] == "PUBLISHED" and not plan["audience"]:
                    return self._p_fail(409, "CONFLICT", "plan_audience_empty")
                plan.update(
                    {
                        k: v
                        for k, v in body.items()
                        if k in ("title", "description", "building", "floor", "display_order", "distribution")
                    }
                )
            return self._p_ok(self._plan_out(plan))
        if action == "versions":
            if len(parts) == 4 and parts[3] == "file":
                content = self.plan_files.get(parts[2])
                version = next((v for v in plan["versions"] if v["id"] == parts[2]), None)
                if content is None or version is None:
                    return self._p_fail(404, "NOT_FOUND")
                return httpx.Response(200, content=content, headers={"content-type": version["mime_type"]})
            if method == "GET":
                rows = sorted(plan["versions"], key=lambda v: -v["number"])
                return self._p_ok([self._version_out(plan, v) for v in rows])
            self.plan_uploads.append(request.content)
            _, files = multipart(request)
            name, content = files[0][1], files[0][2]
            mime = next((m for magic, m in PLAN_MAGIC if content.startswith(magic)), None)
            if mime is None:
                return self._p_fail(400, "BUSINESS_RULE_VIOLATION", "plan_format_not_supported")
            vid = self.add_plan_version(plan["id"], content, mime, name)
            return self._p_ok(self._version_out(plan, plan["versions"][-1]), 201) if vid else None
        if action == "publish":
            version = next((v for v in plan["versions"] if v["id"] == body.get("version")), None)
            if version is None:
                return self._p_fail(404, "NOT_FOUND")
            if plan["distribution"] == "MANUAL" and not plan["audience"]:
                return self._p_fail(409, "CONFLICT", "plan_audience_empty")
            for other in plan["versions"]:
                if other["status"] == "PUBLISHED" and other is not version:
                    other["status"] = "SUPERSEDED"
            version.update(status="PUBLISHED", published_at=version["published_at"] or NOW)
            plan.update(status="PUBLISHED", current=version["id"], published_at=NOW)
            return self._p_ok(self._plan_out(plan))
        if action == "withdraw":
            if plan["status"] != "PUBLISHED":
                return self._p_fail(409, "CONFLICT", "plan_not_published")
            plan["status"] = "WITHDRAWN"
            plan["withdraw_reason"] = body.get("reason")
            return self._p_ok(self._plan_out(plan))
        if action == "audience":
            if method == "PUT":
                entries = body.get("entries") or []
                if not entries and plan["status"] == "PUBLISHED" and plan["distribution"] == "MANUAL":
                    return self._p_fail(409, "CONFLICT", "plan_audience_empty")
                plan["audience"] = [
                    {"target": e["target"], "school_class": e.get("school_class"), "school_class_name": None}
                    for e in entries
                ]
            return self._p_ok(plan["audience"])
        if action == "access":
            readers = [{"id": "p1", "name": "Awa Parent", "roles": ["PARENT"]}] if plan["status"] == "PUBLISHED" else []
            return self._p_ok(
                {
                    "published": plan["status"] == "PUBLISHED",
                    "distribution": plan["distribution"],
                    "count": len(readers),
                    "readers": readers,
                }
            )
        return self._p_fail(404, "NOT_FOUND")

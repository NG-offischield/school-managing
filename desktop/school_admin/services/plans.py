"""School plans (backend documents/plans_api.py). Thin client: the server
checks the file content (PDF / PNG / JPEG only), publishes, withdraws,
resolves who may see a plan and notifies them. The desktop only sends the
chosen file's NAME and BYTES (never a local path) and shows the answers.

    GET/POST  admin/plans/                    GET/PATCH admin/plans/{id}/
    GET/POST  admin/plans/{id}/versions/      (multipart `file`)
    GET       admin/plans/{id}/versions/{v}/file/   preview / history (bytes)
    POST      admin/plans/{id}/publish/ {version}   POST admin/plans/{id}/withdraw/ {reason}
    GET/PUT   admin/plans/{id}/audience/      GET admin/plans/{id}/access/
"""

from pathlib import Path

from ..api.errors import ValidationFailed
from ..models import PlanVersion, SchoolPlan

FILE_TYPES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
FILE_FILTER = "Plans (*.pdf *.png *.jpg *.jpeg)"


def read_plan_file(path):
    """(bare name, bytes, declared type) of the chosen file. The server decides
    the real type from the content (a renamed file is refused there)."""
    local = Path(path)
    return local.name, local.read_bytes(), FILE_TYPES.get(local.suffix.lower(), "application/octet-stream")


class PlanService:
    PATH = "admin/plans/"

    def __init__(self, api):
        self.api = api

    def list(self, *, status=None, building=None):
        rows = self.api.list_all(self.PATH, status=status or None, building=building or None)
        return [SchoolPlan.from_api(row) for row in rows]

    def get(self, plan_id):
        return SchoolPlan.from_api(self.api.get(f"{self.PATH}{plan_id}/"))

    @staticmethod
    def _meta(title, description, building, floor, display_order):
        if not (title or "").strip():
            raise ValidationFailed("Formulaire incomplet.", details={"title": ["Obligatoire."]})
        return {
            "title": title.strip(),
            "description": (description or "").strip(),
            "building": (building or "").strip(),
            "floor": (floor or "").strip(),
            "display_order": int(display_order or 0),
        }

    def create(self, *, title, description="", building="", floor="", display_order=0, distribution="AUTO"):
        payload = {**self._meta(title, description, building, floor, display_order), "distribution": distribution}
        return SchoolPlan.from_api(self.api.post(self.PATH, payload))

    def update(self, plan_id, *, title, description="", building="", floor="", display_order=0):
        payload = self._meta(title, description, building, floor, display_order)
        return SchoolPlan.from_api(self.api.patch(f"{self.PATH}{plan_id}/", payload))

    def set_distribution(self, plan_id, distribution):
        return SchoolPlan.from_api(self.api.patch(f"{self.PATH}{plan_id}/", {"distribution": distribution}))

    def versions(self, plan_id):
        return [PlanVersion.from_api(row) for row in self.api.get(f"{self.PATH}{plan_id}/versions/") or []]

    def upload(self, plan_id, path):
        """Runs in the worker thread: reading a 20 MB file never freezes the window."""
        name, content, content_type = read_plan_file(path)
        row = self.api.post_multipart(f"{self.PATH}{plan_id}/versions/", {}, [("file", (name, content, content_type))])
        return PlanVersion.from_api(row)

    def version_file(self, plan_id, version_id):
        return self.api.get_bytes(f"{self.PATH}{plan_id}/versions/{version_id}/file/")

    def publish(self, plan_id, version_id):
        return SchoolPlan.from_api(self.api.post(f"{self.PATH}{plan_id}/publish/", {"version": version_id}))

    def withdraw(self, plan_id, reason=""):
        return SchoolPlan.from_api(self.api.post(f"{self.PATH}{plan_id}/withdraw/", {"reason": reason or ""}))

    def audience(self, plan_id):
        return list(self.api.get(f"{self.PATH}{plan_id}/audience/") or [])

    def set_audience(self, plan_id, entries):
        """`entries`: [(target, class_id or None)]."""
        body = {"entries": [{"target": target, "school_class": class_id} for target, class_id in entries]}
        return self.api.request("PUT", f"{self.PATH}{plan_id}/audience/", json=body)[0]

    def access(self, plan_id):
        return self.api.get(f"{self.PATH}{plan_id}/access/")

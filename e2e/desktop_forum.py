"""Admin desktop x forum, against the REAL backend (TEST only), over the LAN.

Runs the desktop's OWN client code — ApiClient, CommunicationService and the
Qt RealtimeClient used by its screens — not a re-implementation: the
administration publishes a discussion, a DEMO parent answers through the API
(as the phone does), the desktop is notified live (FORUM, labelled "Forum"),
reads the reply, moderates it with a reason and locks the discussion; the
parent's next reply is refused (409 thread_locked).

    E2E_API_URL=http://<LAN IP>:8001  DEMO_PASSWORD=...  (environment only)
    desktop/.venv/Scripts/python e2e/desktop_forum.py

Same TEST backend and DEMO data as e2e/cross_app.mjs (see e2e/README.md).
Prints PASS / FAIL lines; exit 1 on any FAIL.
"""

import os
import sys
import time
import uuid
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "desktop"))

from PySide6.QtCore import QCoreApplication  # noqa: E402
from school_admin.api import ApiClient  # noqa: E402
from school_admin.api.errors import ApiError  # noqa: E402
from school_admin.models import Notification  # noqa: E402
from school_admin.realtime import RealtimeClient, socket_url  # noqa: E402
from school_admin.services.communication import CommunicationService  # noqa: E402

ROOT = os.environ["E2E_API_URL"].rstrip("/").removesuffix("/api/v1")
API = f"{ROOT}/api/v1/"
PASSWORD = os.environ["DEMO_PASSWORD"]
results = []


def check(label, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'} DESKTOP {label}{f' — {detail}' if detail else ''}")


def session(identifier, kind):
    api = ApiClient(API)
    device = {"identifier": f"e2e-{kind}", "device_name": f"E2E {kind}", "device_type": kind, "platform": "WINDOWS"}
    tokens = api.request(
        "POST", "auth/login/", json={"identifier": identifier, "password": PASSWORD, "device": device}, auth=False
    )[0]
    api.access_token = tokens["access_token"]
    return api


def wait(predicate, seconds=10):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.05)
    return False


app = QCoreApplication([])
admin_api = session(os.environ.get("E2E_ADMIN", "demo.admin"), "DESKTOP")
parent_api = session("parent.a@demo-ecole.test", "PHONE")
desk = CommunicationService(admin_api)

live, states = [], []
realtime = RealtimeClient(admin_api, socket_url(API))
realtime.notification.connect(live.append)
realtime.state_changed.connect(states.append)
realtime.start()
check("live connection of the desktop (QWebSocket, LAN)", wait(lambda: "online" in states), " ".join(states))

space = desk.create_space(name=f"Parents et école {uuid.uuid4().hex[:5]}", audience="SCHOOL", roles=["PARENT"])
thread = desk.publish(space_id=space.id, title="Fête de fin d'année", body="Vos idées ?")
check("the desktop publishes a discussion", bool(thread.id) and thread.kind == "GENERAL")

reply = parent_api.post(f"forum/threads/{thread.id}/posts/", {"body": "Un spectacle des élèves !"})
pushed = wait(lambda: any(n.get("payload", {}).get("post") == reply["id"] for n in live))
note = next((Notification.from_api(n) for n in live if n.get("payload", {}).get("post") == reply["id"]), None)
check("the desktop is notified live of the parent's reply", pushed)
check('the notification is labelled "Forum" in the desktop', note is not None and note.kind_label == "Forum")
rows, _ = desk.notifications(kind="FORUM")
found = note is not None and any(r.id == note.id for r in rows)
check("the desktop finds it again in its notification list (GET)", found)

threads = [t.id for t in desk.threads(space_id=space.id)]
posts = desk.posts(thread.id)
read = thread.id in threads and any(p.id == reply["id"] for p in posts)
check("the desktop lists the discussion and reads the reply", read)

moderated = desk.moderate_post(reply["id"], "Merci de passer par le bureau des parents")
seen_by_parent = next(p for p in parent_api.list_all(f"forum/threads/{thread.id}/posts/") if p["id"] == reply["id"])
check("the desktop moderates the reply with a reason", moderated.deleted and seen_by_parent["body"] is None)

locked = desk.set_thread_status(thread.id, "LOCKED", "Discussion close")
try:
    parent_api.post(f"forum/threads/{thread.id}/posts/", {"body": "Encore une idée"})
    refused = None
except ApiError as error:
    refused = error
check(
    "the desktop locks the discussion; the parent's next reply is refused (409 thread_locked)",
    locked.status == "LOCKED" and refused is not None and getattr(refused, "status", None) == 409,
    f"{getattr(refused, 'status', None)}",
)

realtime.stop()
fails = results.count(False)
print(f"\n{len(results)} checks: {len(results) - fails} PASS, {fails} FAIL")
sys.exit(1 if fails else 0)

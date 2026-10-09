"""Admin desktop x parent payment, against the REAL backend (TEST only), over the LAN.

Runs the desktop's OWN client code (ApiClient, CommunicationService, the Qt
RealtimeClient, headless): a DEMO parent pays an invoice through the API, as
the parent app does; the desktop must be notified live (« Paiement », title
« Paiement confirmé — facture … — … XAF »), see its unread counter go up,
find the notification again with GET, and see the PAID invoice in Finance.
A refused attempt (insufficient funds) must notify nothing.

    E2E_API_URL=http://<LAN IP>:8001  DEMO_PASSWORD=...  (environment only)
    desktop/.venv/Scripts/python e2e/desktop_payment.py

Same TEST backend and DEMO data as e2e/cross_app.mjs (see e2e/README.md);
uses parent D (parent A is cross_app.mjs's payer). Exit 1 on any FAIL.
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
parent_api = session("parent.d@demo-ecole.test", "PHONE")
desk = CommunicationService(admin_api)

live, states, unread = [], [], []
realtime = RealtimeClient(admin_api, socket_url(API))
realtime.notification.connect(live.append)
realtime.state_changed.connect(states.append)
realtime.unread_changed.connect(unread.append)
realtime.start()
check("live connection of the desktop (QWebSocket, LAN)", wait(lambda: "online" in states), " ".join(states))
wait(lambda: bool(unread), 3)
start_unread = unread[-1] if unread else admin_api.get("notifications/unread-count/")["unread"]


def pay(api, *, key, amount=None):
    child = api.get("parents/children/")[0]["student"]["id"]
    due = api.get(f"finance/students/{child}/obligations/")["open_invoices"][0]
    wallet = api.get("finance/wallets/")[0]
    payload = {
        "student": child,
        "amount": amount or due["balance_due"],
        "payment_method": "WALLET",
        "wallet": wallet["id"],
        "invoices": [due["id"]],
        "idempotency_key": key,
    }
    return api.post("finance/payments/", payload), due


# A refused attempt first: parent B's DEMO wallet holds 1 000 XAF (insufficient funds).
poor_api = session("parent.b@demo-ecole.test", "PHONE")
refused, _ = pay(poor_api, key=f"e2e-poor-{uuid.uuid4().hex[:8]}")
wait(lambda: False, 1.5)  # leave time for a (wrong) notification to arrive
check(
    "insufficient funds: recorded as such, no notification to the desktop",
    refused["status"] == "INSUFFICIENT_FUNDS" and not any(n.get("notification_type") == "PAYMENT" for n in live),
    refused["status"],
)

key = f"e2e-pay-{uuid.uuid4().hex[:8]}"
payment, invoice = pay(parent_api, key=key)
check("the parent's payment is confirmed by Finance", payment["status"] == "SUCCEEDED", payment["status"])
got = wait(lambda: any(n.get("payload", {}).get("payment") == payment["id"] for n in live))
check("the desktop is notified live of the confirmed payment", got)
note = next((Notification.from_api(n) for n in live if n.get("payload", {}).get("payment") == payment["id"]), None)
number = admin_api.get(f"finance/invoices/{invoice['id']}/")["invoice_number"]
check("type shown as « Paiement »", note is not None and note.kind_label == "Paiement")
title_ok = (
    note is not None and note.title.startswith(f"Paiement confirmé — facture {number} — ") and "XAF" in note.title
)
check(
    "title « Paiement confirmé — facture <n°> — <montant> XAF » from the recorded data",
    title_ok,
    note.title if note else "",
)
check("the unread counter goes up", admin_api.get("notifications/unread-count/")["unread"] >= start_unread + 1)
rows, _ = desk.notifications(kind="PAYMENT")
check("found again in the desktop's notification list (GET)", note is not None and any(r.id == note.id for r in rows))
check("Finance shows the invoice PAID", admin_api.get(f"finance/invoices/{invoice['id']}/")["status"] == "PAID")

# Lost response: the phone resends the SAME intent (same idempotency key) -> same payment, no second notification.
again = parent_api.post(
    "finance/payments/",
    {
        "student": payment["student"] if isinstance(payment["student"], str) else payment["student"]["id"],
        "amount": invoice["balance_due"],
        "payment_method": "WALLET",
        "wallet": parent_api.get("finance/wallets/")[0]["id"],
        "invoices": [invoice["id"]],
        "idempotency_key": key,
    },
)
wait(lambda: False, 1.5)
mine = [n for n in desk.notifications(kind="PAYMENT")[0] if n.message and payment["payment_reference"] in n.message]
check(
    "a replay returns the same payment and adds no notification",
    again["id"] == payment["id"] and len(mine) == 1,
    f"{len(mine)}",
)

realtime.stop()
fails = results.count(False)
print(f"\n{len(results)} checks: {len(results) - fails} PASS, {fails} FAIL")
sys.exit(1 if fails else 0)

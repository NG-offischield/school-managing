"""Gestion → Communication and → Documents (ADR 0023): thin clients of the
EXISTING communication domain, Channels endpoint and Document registry.
Visibility, transitions, moderation, attachment checks and PDF building are
the server's; nothing is deleted; documents carry the SCHOOL's branding."""

import inspect
import json
import uuid
from datetime import date

import pytest
from PySide6.QtCore import QObject, QSize, Signal
from PySide6.QtTest import QTest

from school_admin import realtime as realtime_module
from school_admin.api.errors import Conflict, Forbidden, NotFound, ValidationFailed
from school_admin.config import AppConfig
from school_admin.messages import explain
from school_admin.realtime import RealtimeClient, socket_url
from school_admin.services.communication import CommunicationService
from school_admin.services.documents import DocumentService
from school_admin.services.finance import FinanceService, new_idempotency_key
from school_admin.ui.app import AppController
from school_admin.ui.tasks import ImmediateRunner

from .fake_backend import PASSWORD


@pytest.fixture
def comm(logged_in, api, backend):
    backend.seed_comm()
    return CommunicationService(api)


@pytest.fixture
def docs(logged_in, api, backend):
    backend.seed_documents()
    return DocumentService(api)


def pdf_file(tmp_path, name="note.pdf", content=b"%PDF-1.4 test"):
    path = tmp_path / name
    path.write_bytes(content)
    return str(path)


# =============================================================================
# Services
# =============================================================================


def test_notifications(comm, backend):
    rows, total = comm.notifications()
    assert total == 3 and rows[0].title == "Paiement reçu" and rows[0].kind_label == "Paiement"
    assert [n.title for n in comm.notifications(is_read=False)[0]] == [
        "Paiement reçu",
        "Nouvelle réclamation : cantine",
    ]
    assert comm.notifications(is_read=True)[1] == 1 and comm.notifications(kind="COMPLAINT")[1] == 1
    assert comm.unread_notifications() == 2
    assert comm.mark_read(rows[0].id).is_read and comm.unread_notifications() == 1
    assert comm.mark_all_read() == 1 and comm.unread_notifications() == 0


def test_messaging_attachments_and_history(comm, backend, tmp_path):
    from school_admin.services.communication import read_attachment

    conversation = comm.conversations()[0]
    assert (conversation.label, conversation.unread) == ("Réunion parents-profs", 1)
    messages = comm.messages(conversation.id)
    attachment = messages[0].attachments[0]
    assert (attachment.name, attachment.kind) == ("ordre-du-jour.pdf", "message")
    assert comm.download(attachment).startswith(b"%PDF")
    started = comm.start_conversation(
        participant_ids=["m-par"], title="Absence", body="Bonjour", files=[read_attachment(pdf_file(tmp_path))]
    )
    assert started.label == "Absence"
    upload = backend.uploads[-1]
    assert b'filename="note.pdf"' in upload and str(tmp_path).encode() not in upload  # never a local path
    fake_pdf = pdf_file(tmp_path, "facture.pdf", b"MZ\x90\x00 executable")
    with pytest.raises(ValidationFailed) as exc:
        comm.send(conversation.id, "Voir pièce", files=[read_attachment(fake_pdf)])
    assert exc.value.rule == "attachment_type_not_allowed"  # the content decides, not the name
    assert explain(exc.value).startswith("Type de fichier refusé")
    first = comm.send(conversation.id, "Merci", client_id="intent-1")
    again = comm.send(conversation.id, "Merci", client_id="intent-1")
    assert first.id == again.id  # resend after a network failure: no duplicate
    hidden = comm.hide_message(first.id)
    assert hidden.deleted and hidden.body == "Merci"  # hidden, kept for the administration
    with pytest.raises(Conflict) as exc:
        comm.hide_message(first.id)
    assert exc.value.rule == "message_already_deleted"
    with pytest.raises(Forbidden):
        comm.add_participant(conversation.id, "m-tm")  # only administrators join
    assert [n for _, n, _ in comm.add_participant(conversation.id, "m-adm2").participants][-1] == "Bea Admin"
    with pytest.raises(NotFound):
        comm.messages("another-school")


def test_forum_publication_and_moderation(comm, backend):
    with pytest.raises(ValidationFailed) as exc:
        comm.create_space(name="Profs", audience="SCHOOL", roles=[])
    assert exc.value.rule == "roles_required"
    space = comm.create_space(name="Profs", audience="SCHOOL", roles=["TEACHER"])
    thread = comm.publish(space_id=space.id, title="Conseil de classe", body="Le 12 mars.", announcement=True)
    assert thread.kind == "ANNOUNCEMENT" and [t.title for t in comm.threads(space_id=space.id)] == ["Conseil de classe"]
    reply = comm.reply(thread.id, "Bien noté")
    moderated = comm.moderate_post(reply.id, "Hors sujet")
    assert moderated.deleted and moderated.deletion_reason == "Hors sujet"
    assert len(comm.posts(thread.id)) == 2  # kept
    assert comm.set_thread_status(thread.id, "LOCKED", "Clos").status == "LOCKED"
    with pytest.raises(Conflict) as exc:
        comm.reply(thread.id, "Encore")
    assert exc.value.rule == "thread_locked"


def test_complaint_workflow(comm, backend, tmp_path):
    from school_admin.services.communication import read_attachment

    rows = comm.complaints(status="OPEN")
    assert [c.subject for c in rows] == ["Cantine froide"]
    with pytest.raises(ValidationFailed) as exc:
        comm.change_status(backend.cpl, status="RESOLVED")
    assert exc.value.rule == "reason_required"
    comm.change_status(backend.cpl, status="IN_PROGRESS", assigned_to="m-adm2")
    with pytest.raises(Conflict) as exc:
        comm.change_status(backend.cpl, status="CLOSED", reason="x")
    assert exc.value.rule == "invalid_transition"
    resolved = comm.change_status(backend.cpl, status="RESOLVED", reason="Repas chauds rétablis")
    assert [h[1] for h in resolved.history] == ["OPEN", "IN_PROGRESS", "RESOLVED"] and resolved.assigned_to == "m-adm2"
    assert (
        comm.attach_to_complaint(
            backend.cpl, [read_attachment(pdf_file(tmp_path, "photo.png", b"\x89PNG\r\n\x1a\nxx"))]
        )
        == 1
    )
    attachment = comm.complaint(backend.cpl).attachments[0]
    assert comm.download(attachment).startswith(b"\x89PNG")
    with pytest.raises(Conflict) as exc:
        comm.cancel_complaint(backend.cpl_done, "Trop tard")
    assert exc.value.rule == "complaint_final"
    with pytest.raises(NotFound):
        comm.complaint("another-school")


def test_member_directory_and_permissions(comm, backend):
    assert {m.name for m in comm.members(role="ADMIN")} == {"Bea Admin"}
    backend.roles = ["TEACHER"]
    with pytest.raises(Forbidden):
        comm.members()
    with pytest.raises(Forbidden):
        comm.change_status(backend.cpl, status="IN_PROGRESS")


def test_documents_registry(docs, backend, api):
    finance = FinanceService(api)
    payment = finance.initiate(
        student_id=backend.sa,
        amount="60000",
        method="CASH",
        idempotency_key=new_idempotency_key(),
        invoice_ids=[backend.inv1],
    )
    receipt = docs.generate("PAYMENT_RECEIPT", payment=payment.id)
    assert (receipt.kind_label, receipt.status) == ("Reçu de paiement", "OFFICIAL")
    assert docs.generate("PAYMENT_RECEIPT", payment=payment.id).id == receipt.id  # the current one, not a copy
    backend.wallets[backend.w_decline]["simulation_behavior"] = "DECLINE"
    refused = finance.initiate(
        student_id=backend.sa,
        amount="100",
        method="WALLET",
        idempotency_key=new_idempotency_key(),
        invoice_ids=[backend.inv2],
        wallet_id=backend.w_decline,
    )
    with pytest.raises(Conflict) as exc:
        docs.generate("PAYMENT_RECEIPT", payment=refused.id)
    assert exc.value.rule == "document_source_not_final"
    with pytest.raises(ValidationFailed):
        docs.generate("STUDENT_ATTENDANCE", student=backend.sa)  # dates required
    with pytest.raises(ValidationFailed):
        docs.generate("TIMETABLE", date=date(2026, 3, 2))  # a class or a teacher
    card = docs.generate("STUDENT_CARD", student=backend.sa)
    assert card.title == "Carte — Awa Ndiaye"
    assert docs.documents(kind="STUDENT_CARD")[1] == 2
    assert {d.title for d in docs.documents(search="awa")[0]} == {"Carte — Awa Ndiaye", "Carte d'élève — Awa Ndiaye"}
    with pytest.raises(Conflict) as exc:
        docs.regenerate(receipt.id)
    assert exc.value.rule == "document_official"
    newer = docs.regenerate(backend.doc_tt)
    assert newer.version == 2 and docs.document(backend.doc_tt).status == "SUPERSEDED"  # history kept
    assert docs.verify(receipt.verification_code.lower())["status"] == "OFFICIAL"
    with pytest.raises(NotFound):
        docs.verify("INCONNU")
    assert docs.download(receipt.id).startswith(b"%PDF")
    assert [c["period_name"] for c in docs.report_cards(backend.sa)] == ["Trimestre 1"]
    backend.roles = ["TEACHER"]
    assert docs.documents() == ([], 0)
    with pytest.raises(NotFound):
        docs.document(receipt.id)


# =============================================================================
# Real time (existing ws/v1/realtime/ endpoint) with a fake socket
# =============================================================================


class FakeSocket(QObject):
    connected = Signal()
    disconnected = Signal()
    textMessageReceived = Signal(str)

    def __init__(self):
        super().__init__()
        self.sent, self.headers, self.code, self.closed = [], {}, 1000, False

    def open(self, request):
        self.headers = {b"Authorization": bytes(request.rawHeader("Authorization"))}
        self.url = request.url().toString()

    def sendTextMessage(self, text):
        self.sent.append(json.loads(text))

    def close(self):
        self.closed = True

    def closeCode(self):
        return self.code

    def push(self, frame):
        self.textMessageReceived.emit(json.dumps(frame))


class StubApi:
    def __init__(self, refresh=True):
        self.access_token, self.refresh_ok, self.refreshes = "acc-1", refresh, 0

    def _try_refresh(self):
        self.refreshes += 1
        if self.refresh_ok:
            self.access_token = "acc-2"
        return self.refresh_ok


def client(api=None):
    sockets = []

    def factory():
        sockets.append(FakeSocket())
        return sockets[-1]

    rt = RealtimeClient(api or StubApi(), "ws://h/ws/v1/realtime/", socket_factory=factory)
    return rt, sockets


def test_socket_url():
    assert socket_url("http://127.0.0.1:8000/api/v1/") == "ws://127.0.0.1:8000/ws/v1/realtime/"
    assert socket_url("https://ecole.example/api/v1/") == "wss://ecole.example/ws/v1/realtime/"


def test_realtime_connect_sync_and_pushes(qapp):
    rt, sockets = client()
    seen = {"notifications": [], "unread": [], "messages": [], "states": []}
    rt.notification.connect(seen["notifications"].append)
    rt.unread_changed.connect(seen["unread"].append)
    rt.message_created.connect(seen["messages"].append)
    rt.state_changed.connect(seen["states"].append)
    rt.watch("c1")
    rt.start()
    socket = sockets[0]
    assert socket.headers[b"Authorization"] == b"Bearer acc-1"  # same token as REST, never in the URL
    socket.push({"type": "auth.ok", "unread_notifications": 3})
    assert rt.state == "online" and seen["unread"] == [3]
    assert socket.sent[:2] == [{"type": "sync"}, {"type": "subscribe", "conversation": "c1"}]
    socket.push(
        {"type": "notification", "data": {"id": "n1", "title": "Paiement", "created_at": "2026-03-04T10:00:00"}}
    )
    socket.push(
        {"type": "message.created", "data": {"id": "x", "conversation": "c1", "created_at": "2026-03-04T10:05:00"}}
    )
    assert seen["notifications"][0]["id"] == "n1" and seen["messages"][0]["id"] == "x"
    rt.ping_timer.timeout.emit()
    assert socket.sent[-1] == {"type": "ping"}
    # A network drop: offline, automatic retry; the resync asks only for what was missed.
    socket.disconnected.emit()
    assert rt.state == "offline" and rt.retry_timer.isActive()
    rt.retry_timer.stop()
    rt.start()
    sockets[1].push({"type": "auth.ok", "unread_notifications": 4})
    assert sockets[1].sent[:2] == [
        {"type": "sync", "since": "2026-03-04T10:00:00"},
        {"type": "subscribe", "conversation": "c1", "since": "2026-03-04T10:05:00"},
    ]
    assert seen["states"] == ["connecting", "online", "offline", "connecting", "online"]
    rt.stop()


def test_realtime_revocation_refreshes_then_expires(qapp):
    api = StubApi(refresh=True)
    rt, sockets = client(api)
    expired = []
    rt.session_expired.connect(lambda: expired.append(True))
    rt.start()
    sockets[0].code = realtime_module.UNAUTHORIZED
    sockets[0].disconnected.emit()  # expired access token: one refresh, then reconnection
    QTest.qWait(5)
    assert api.refreshes == 1 and len(sockets) == 2 and sockets[1].headers[b"Authorization"] == b"Bearer acc-2"
    api.refresh_ok = False
    sockets[1].code = realtime_module.UNAUTHORIZED
    sockets[1].disconnected.emit()  # revoked session: the refresh fails -> back to the login
    assert expired == [True] and rt.state == "expired"


# =============================================================================
# Screens
# =============================================================================


@pytest.fixture
def controller(qapp, api, auth, backend):
    backend.seed_comm()
    backend.seed_documents()
    backend.seed_website()
    ctrl = AppController(api, auth, ImmediateRunner(), AppConfig(api_url="http://testserver/api/v1/"))
    yield ctrl
    if ctrl.main_window is not None:
        ctrl.main_window.close()
    ctrl.login_window.close()


def open_module(ctrl, key):
    window = ctrl.login_window
    window.identifier.setText("admin")
    window.password.setText(PASSWORD)
    window.attempt()
    return ctrl.main_window, ctrl.main_window.open(key)


def column(table, index):
    return [table.item(r, index).text() for r in range(table.rowCount())]


def test_communication_tabs_and_notifications(controller, backend):
    shell, page = open_module(controller, "communication")
    labels = [shell.nav.item(i).text() for i in range(shell.nav.count())]
    assert "Communication" in labels and "Documents" in labels
    assert [page.tabs.tabText(i) for i in range(page.tabs.count())] == [
        "Notifications",
        "Messagerie",
        "Forum",
        "Réclamations",
    ]
    assert page.live.text() == "Temps réel désactivé : utilisez « Actualiser »."
    notes = page.notifications
    assert column(notes.table, 2) == ["Paiement reçu", "Nouvelle réclamation : cantine", "Nouveau message"]
    assert column(notes.table, 5)[0] == "●  Non lue"
    notes.status.setCurrentIndex(notes.status.findData(False))
    assert notes.count_label.text() == "2 notifications"
    shown = []
    notes.ask = shown.append
    notes.table.selectRow(0)
    notes.open_row()
    assert shown[0].title == "Paiement reçu" and notes.banner.plain_text() == "Notification marquée comme lue."
    notes.mark_all()
    assert notes.banner.plain_text() == "1 notification(s) marquée(s) comme lue(s)."


def test_messaging_screen(controller, backend, tmp_path):
    _, page = open_module(controller, "communication")
    messaging = page.open_tab("messaging")
    assert messaging.list.count() == 1 and "●1" in messaging.list.item(0).text()
    messaging.list.setCurrentRow(0)
    assert messaging.thread.count() == 1 and "📎 ordre-du-jour.pdf" in messaging.thread.item(0).text()
    messaging.thread.setCurrentRow(0)
    target = tmp_path / "copie.pdf"
    messaging.save_path = lambda parent, name: str(target)
    messaging.download()
    assert target.read_bytes().startswith(b"%PDF") and messaging.banner.plain_text() == "Pièce jointe enregistrée."
    messaging.compose.setPlainText("Merci, à jeudi.")
    messaging.choose_files = lambda parent: [pdf_file(tmp_path)]
    messaging.attachments.pick()
    messaging.send()
    assert messaging.thread.count() == 2 and "📎 note.pdf" in messaging.thread.item(1).text()
    assert messaging.compose.toPlainText() == "" and messaging.attachments.paths == []
    backend.offline = True
    messaging.compose.setPlainText("Message en panne")
    messaging.send()
    backend.offline = False
    pending = messaging.pending
    assert pending and pending[1] == "Message en panne"
    messaging.send()  # same text -> same client_id
    assert messaging.pending is None and backend.chat[messaging.messages[-1].id]["client_id"] == pending[2]
    messaging.pushed(
        {
            "id": "live-1",
            "conversation": messaging.current.id,
            "sender": "m-tm",
            "sender_name": "Jean Mbarga",
            "body": "Reçu !",
            "created_at": "2026-03-04T11:00:00+01:00",
            "attachments": [],
        }
    )
    assert "Reçu !" in messaging.thread.item(messaging.thread.count() - 1).text()
    messaging.ask = lambda kind, **c: {"participant_ids": ["m-par"], "title": "Sortie", "body": "Bonjour", "files": []}
    messaging.new_conversation()
    assert messaging.banner.plain_text() == "Conversation « Sortie » créée." and messaging.current.label == "Sortie"


def test_forum_screen(controller, backend):
    _, page = open_module(controller, "communication")
    forum = page.open_tab("forum")
    assert column(forum.table, 0) == ["Rentrée"] and column(forum.table, 1) == ["Annonces"]
    forum.ask = lambda kind, **c: {
        "space_id": backend.space,
        "title": "Kermesse",
        "body": "Samedi.",
        "announcement": True,
    }
    forum.add()
    assert forum.banner.plain_text() == "Sujet « Kermesse » publié."
    forum.select_id(backend.thread)
    forum.ask = lambda kind, **c: {"action": "LOCKED", "post_id": None, "text": ""}
    forum.open_row()
    assert forum.banner.plain_text() == "Sujet « Rentrée » verrouillé."
    forum.select_id(backend.thread)
    forum.ask = lambda kind, **c: {"action": "reply", "post_id": None, "text": "Encore une question"}
    forum.open_row()
    assert "verrouillé ou archivé" in forum.banner.plain_text()  # 409 thread_locked explained


def test_complaints_screen(controller, backend, tmp_path):
    _, page = open_module(controller, "communication")
    complaints = page.open_tab("complaints")
    assert sorted(column(complaints.table, 0)) == ["Bulletin erroné", "Cantine froide"]
    assert set(column(complaints.table, 3)) == {"Parent Ndiaye"}
    complaints.select_id(backend.cpl_done)
    assert not complaints.status_button.isEnabled()  # final: consultation only
    complaints.select_id(backend.cpl)
    complaints.ask = lambda kind, **c: {"status": "CLOSED", "assigned_to": None, "reason": "x"}
    complaints.complaint_action("status")
    assert "n'est pas permis depuis l'état actuel" in complaints.banner.plain_text()
    complaints.select_id(backend.cpl)  # the refused change reloaded the list
    complaints.ask = lambda kind, **c: {"status": "IN_PROGRESS", "assigned_to": "m-adm2", "reason": ""}
    complaints.complaint_action("status")
    assert complaints.banner.plain_text() == "Réclamation « Cantine froide » : en traitement."
    complaints.choose_files = lambda parent: [pdf_file(tmp_path)]
    complaints.complaint_action("attach")
    assert complaints.banner.plain_text() == "1 pièce(s) jointe(s) ajoutée(s)."
    target = tmp_path / "pj.pdf"
    complaints.save_path = lambda parent, name: str(target)
    complaints.ask = lambda kind, **c: {"action": "download", "attachment": c["complaint"].attachments[0]}
    complaints.open_row()
    assert target.read_bytes().startswith(b"%PDF")


def test_documents_screen(controller, backend, tmp_path):
    shell, page = open_module(controller, "documents")
    assert [page.tabs.tabText(i) for i in range(page.tabs.count())] == [
        "Bulletins",
        "Cartes élèves",
        "Emplois du temps",
        "Reçus",
        "Bulletins de paie",
        "Relevés de présence",
        "Plans",  # the school's 2D plans (not the generated-document registry)
    ]
    cards = page.open_tab("cards")
    assert column(cards.table, 0) == ["Carte d'élève — Awa Ndiaye"] and column(cards.table, 5) == ["Officiel"]
    cards.ask = lambda kind, **c: {"student": backend.sb}
    cards.add()
    assert cards.banner.plain_text() == "Carte d'élève prêt : « Carte — Paul Kamga » (provisoire)."
    target = tmp_path / "carte.pdf"
    cards.save_path = lambda parent, name: str(target)
    cards.download(cards.selected())
    assert target.read_bytes().startswith(b"%PDF") and b"SchoolBranding" in target.read_bytes()
    cards.ask = lambda kind, **c: {"code": backend.documents_store[backend.doc_card]["verification_code"]}
    cards.verify()
    assert cards.banner.plain_text().startswith("Document authentique")
    cards.ask = lambda kind, **c: {"code": "FAUX"}
    cards.verify()
    assert cards.banner.property("kind") == "warning"
    timetables = page.open_tab("timetables")
    timetables.select_id(backend.doc_tt)
    assert timetables.regenerate_button.isEnabled()
    timetables.regenerate(timetables.selected())
    assert timetables.banner.plain_text() == "Document regénéré (version 2) ; l'ancien est conservé."
    reports = page.open_tab("report_cards")
    reports.ask = lambda kind, **c: (
        {"class_id": "c", "period_id": "per1"} if kind == "compute" else {"report_card": "rc1"}
    )
    reports.compute_report_cards()
    assert reports.banner.plain_text() == "1 bulletin(s) calculé(s) : générez maintenant leur PDF."
    reports.add()
    assert reports.banner.plain_text().startswith("Bulletin scolaire prêt")
    attendance = page.open_tab("attendance")
    assert [attendance.kind_filter.itemData(i) for i in range(2)] == ["STUDENT_ATTENDANCE", "CLASS_ATTENDANCE"]


def test_documents_never_use_the_software_brand():
    """Official documents are built by the server with SchoolBranding; the
    desktop's document screens never touch the software's identity."""
    from school_admin.ui.dialogs import document_dialogs
    from school_admin.ui.pages import documents_page

    for module in (documents_page, document_dialogs):
        source = inspect.getsource(module)
        for software_identity in ("from ..branding", "brand_mark", "software_icon", "SOFTWARE_NAME", "School Managing"):
            assert software_identity not in source


def test_live_state_and_expiry_through_the_controller(qapp, api, auth, backend):
    backend.seed_comm()
    sockets = []
    ctrl = AppController(
        api,
        auth,
        ImmediateRunner(),
        AppConfig(api_url="http://testserver/api/v1/"),
        realtime_factory=lambda client, url: RealtimeClient(
            client, url, socket_factory=lambda: sockets.append(FakeSocket()) or sockets[-1]
        ),
    )
    shell, page = open_module(ctrl, "communication")
    assert sockets and sockets[0].url == "ws://testserver/ws/v1/realtime/"
    sockets[0].push({"type": "auth.ok", "unread_notifications": 2})
    assert page.live.text() == "● Temps réel connecté" and page.tabs.tabText(0) == "Notifications (2)"
    sockets[0].push(
        {
            "type": "notification",
            "data": {
                "id": str(uuid.uuid4()),
                "notification_type": "PAYMENT",
                "title": "Paiement reçu",
                "message": "60 000 XAF",
                "created_at": "2026-03-04T12:00:00+01:00",
            },
        }
    )
    assert page.tabs.tabText(0) == "Notifications (3)" and page.notifications.banner.plain_text().endswith("60 000 XAF")
    api.refresh_handler = lambda: False
    sockets[0].code = realtime_module.UNAUTHORIZED
    sockets[0].disconnected.emit()  # session revoked: back to the login
    assert ctrl.main_window is None and "session a expiré" in ctrl.login_window.banner.text()
    ctrl.login_window.close()


def test_dashboard_communication_and_documents(controller, backend):
    shell, _ = open_module(controller, "dashboard")
    values = {m.label: (m.value, m.hint) for m in shell.pages["dashboard"].data.metrics}
    assert values["Communication"] == ("2 non lue(s)", "1 message non lu(s) · 1 réclamation ouverte(s)")
    assert values["Documents"] == ("2", "dernier : Carte d'élève — Awa Ndiaye")


@pytest.mark.parametrize("size", [QSize(1366, 768), QSize(1280, 720), QSize(1024, 768)])
def test_communication_and_documents_fit(controller, size):
    shell, page = open_module(controller, "communication")
    shell.resize(size)
    shell.show()
    QTest.qWaitForWindowExposed(shell)
    for tab in ("notifications", "forum", "complaints"):
        _fits(page.open_tab(tab), tab)
    messaging = page.open_tab("messaging")
    QTest.qWait(5)
    for widget in (messaging.list, messaging.thread, messaging.compose, messaging.send_button, messaging.new_button):
        assert widget.isVisible() and messaging.rect().contains(widget.mapTo(messaging, widget.rect().bottomRight()))
    documents = shell.open("documents")
    for tab in ("report_cards", "cards", "attendance", "plans"):
        _fits(documents.open_tab(tab), tab)
    shell.close()


def _fits(page, name):
    QTest.qWait(5)
    buttons = [b for b in page.findChildren(type(page.refresh_button)) if b.isVisible() and b.parent() is page]
    row = sorted(
        (b for b in buttons if abs(b.geometry().top() - page.refresh_button.geometry().top()) < 4), key=lambda b: b.x()
    )
    for left, right in zip(row, row[1:], strict=False):
        assert left.geometry().right() < right.geometry().left(), name
    for widget in [*row, page.search, page.table]:
        assert page.rect().contains(widget.geometry()), (name, widget.objectName() or widget)

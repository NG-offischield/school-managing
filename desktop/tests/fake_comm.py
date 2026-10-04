"""Communication + documents part of the fake API (mixin of FakeBackend).

Reproduces the CONTRACT the desktop relies on: visibility (404 for what is
not visible), complaint transitions (409 invalid_transition), moderation
that hides without deleting, attachment checks by CONTENT (PDF / PNG / JPEG
magic bytes), downloads as raw bytes, the document registry (provisional /
official, regeneration, verification code). Not the backend's logic."""

import uuid
from email.parser import BytesParser
from email.policy import HTTP

import httpx

ADMIN = "m1"
NOW = "2026-03-04T10:00:00+01:00"
MAGIC = (b"%PDF", b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")


def multipart(request):
    """(fields {name: [values]}, files [(field, filename, bytes, type)]) of a multipart body."""
    head = f"Content-Type: {request.headers['content-type']}\r\n\r\n".encode()
    message = BytesParser(policy=HTTP).parsebytes(head + request.content)
    fields, files = {}, []
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename()
        payload = part.get_payload(decode=True)
        if filename:
            files.append((name, filename, payload, part.get_content_type()))
        else:
            fields.setdefault(name, []).append(payload.decode())
    return fields, files


class CommunicationFake:
    @staticmethod
    def _c_ok(data, status=200, meta=None):
        return httpx.Response(status, json={"success": True, "data": data, "message": None, "meta": meta})

    @staticmethod
    def _c_fail(status, code, message, details=None):
        error = {"code": code, "message": message}
        if details is not None:
            error["details"] = details
        return httpx.Response(status, json={"success": False, "error": error})

    def init_comm(self):
        self.members = {
            ADMIN: {"id": ADMIN, "name": "Ada Admin", "roles": ["SUPER_ADMIN"]},
            "m-adm2": {"id": "m-adm2", "name": "Bea Admin", "roles": ["ADMIN"]},
            "m-tm": {"id": "m-tm", "name": "Jean Mbarga", "roles": ["TEACHER"]},
            "m-par": {"id": "m-par", "name": "Parent Ndiaye", "roles": ["PARENT"]},
        }
        self.notifications, self.conversations, self.chat = [], {}, {}
        self.files = {}  # attachment id -> (kind, owner id, name, type, bytes)
        self.spaces, self.threads, self.posts = {}, {}, {}
        self.complaints, self.documents_store = {}, {}
        self.report_cards = []
        self.uploads = []  # raw multipart bodies (privacy checks)

    # --- seeds ------------------------------------------------------------------------
    def seed_comm(self):
        for index, (kind, title, read) in enumerate(
            (
                ("PAYMENT", "Paiement reçu", False),
                ("COMPLAINT", "Nouvelle réclamation : cantine", False),
                ("MESSAGE", "Nouveau message", True),
            )
        ):
            self.add_notification(kind, title, read, at=f"2026-03-0{4 - index}T09:00:00+01:00")
        self.conv = self.add_conversation(["m-tm"], "Réunion parents-profs")
        self.add_message(self.conv, "m-tm", "Bonjour, je serai présent.", attachment=b"%PDF-1.4 ordre du jour")
        self.space = self.add_space("Annonces", ["TEACHER", "PARENT"], announcements_only=True)
        self.thread = self.add_thread(self.space, "Rentrée", "La rentrée est fixée au 2 septembre.")
        self.cpl = self.add_complaint("Cantine froide", "m-par", "OPEN")
        self.cpl_done = self.add_complaint("Bulletin erroné", "m-par", "CLOSED")

    def seed_documents(self):
        self.seed_finance()
        self.report_cards = [{"id": "rc1", "student": self.sa, "period_name": "Trimestre 1", "status": "DRAFT"}]
        self.periods_list = [{"id": "per1", "name": "Trimestre 1"}]
        self.doc_card = self.add_document("STUDENT_CARD", "Carte d'élève — Awa Ndiaye", "OFFICIAL")
        self.doc_tt = self.add_document("TIMETABLE", "Emploi du temps — 6e A", "PROVISIONAL")

    # --- builders ---------------------------------------------------------------------
    def add_notification(self, kind, title, read=False, at=NOW):
        row = {
            "id": str(uuid.uuid4()),
            "notification_type": kind,
            "severity": "INFO",
            "title": title,
            "message": f"{title} — détail",
            "payload": {},
            "is_read": read,
            "read_at": NOW if read else None,
            "created_at": at,
        }
        self.notifications.insert(0, row)
        return row

    def add_conversation(self, others, title, kind="ADMINISTRATION"):
        cid = str(uuid.uuid4())
        self.conversations[cid] = {
            "id": cid,
            "conversation_type": kind,
            "title": title,
            "student": None,
            "active": True,
            "last_message_at": NOW,
            "members": [ADMIN, *others],
            "read": {},
        }
        return cid

    def _store_file(self, kind, owner, name, content, mime):
        fid = str(uuid.uuid4())
        self.files[fid] = (kind, owner, name, mime, content)
        return {
            "id": fid,
            "name": name,
            "mime_type": mime,
            "size_bytes": len(content),
            "download_url": f"/api/v1/attachments/{kind}/{fid}/download/",
        }

    def add_message(self, cid, sender, body, attachment=None):
        mid = str(uuid.uuid4())
        row = {
            "id": mid,
            "conversation": cid,
            "sender": sender,
            "sender_name": self.members[sender]["name"],
            "body": body,
            "client_id": None,
            "created_at": f"2026-03-04T10:{len(self.chat):02d}:00+01:00",
            "deleted_at": None,
            "attachments": [],
        }
        if attachment:
            row["attachments"].append(
                self._store_file("message", mid, "ordre-du-jour.pdf", attachment, "application/pdf")
            )
        self.chat[mid] = row
        return mid

    def add_space(self, name, roles, announcements_only=False):
        sid = str(uuid.uuid4())
        self.spaces[sid] = {
            "id": sid,
            "name": name,
            "description": "",
            "audience": "SCHOOL",
            "roles": roles,
            "school_class": None,
            "announcements_only": announcements_only,
            "active": True,
        }
        return sid

    def add_thread(self, space, title, body, kind="ANNOUNCEMENT"):
        tid = str(uuid.uuid4())
        self.threads[tid] = {
            "id": tid,
            "space": space,
            "title": title,
            "thread_type": kind,
            "status": "OPEN",
            "status_reason": None,
            "created_by": ADMIN,
            "author_name": "Ada Admin",
            "created_at": NOW,
            "last_post_at": NOW,
        }
        self._post(tid, ADMIN, body, "ANNOUNCEMENT" if kind == "ANNOUNCEMENT" else "MESSAGE")
        return tid

    def _post(self, tid, author, body, kind="MESSAGE"):
        pid = str(uuid.uuid4())
        self.posts[pid] = {
            "id": pid,
            "thread": tid,
            "author": author,
            "author_name": self.members[author]["name"],
            "post_type": kind,
            "body": body,
            "created_at": NOW,
            "deleted_at": None,
            "deletion_reason": None,
        }
        return pid

    def add_complaint(self, subject, author, status):
        cid = str(uuid.uuid4())
        self.complaints[cid] = {
            "id": cid,
            "author": author,
            "student": None,
            "concerned_member": None,
            "include_administration": True,
            "category": "ADMINISTRATIVE",
            "subject": subject,
            "description": f"{subject} : description détaillée.",
            "priority": "NORMAL",
            "status": status,
            "assigned_to": None,
            "conversation": None,
            "created_at": NOW,
            "submitted_at": NOW,
            "resolved_at": None,
            "closed_at": None,
            "cancelled_at": None,
            "history": [
                {"old_status": "DRAFT", "new_status": "OPEN", "changed_by": author, "comment": None, "at": NOW}
            ],
            "attachments": [],
        }
        return cid

    def add_document(self, kind, title, status, source=None):
        did = str(uuid.uuid4())
        self.documents_store[did] = {
            "id": did,
            "kind": kind,
            "status": status,
            "title": title,
            "version": 1,
            "params": {},
            "file_name": f"{kind.lower()}-{did[:6]}.pdf",
            "size_bytes": 2048,
            "sha256": "ab" * 32,
            "verification_code": f"V{len(self.documents_store) + 1:03d}-CODE",
            "generated_at": NOW,
            "_source": source,
        }
        return did

    # --- helpers ----------------------------------------------------------------------
    def _check_files(self, files):
        if len(files) > 5:
            return self._c_fail(400, "BUSINESS_RULE_VIOLATION", "Trop.", {"rule": "too_many_attachments"})
        for _, _, content, _ in files:
            if not content:
                return self._c_fail(400, "BUSINESS_RULE_VIOLATION", "Vide.", {"rule": "attachment_empty"})
            if not content.startswith(MAGIC):  # the CONTENT decides, not the name or the declared type
                return self._c_fail(400, "BUSINESS_RULE_VIOLATION", "Type.", {"rule": "attachment_type_not_allowed"})
        return None

    def _conversation_out(self, row):
        unread = sum(
            1
            for m in self.chat.values()
            if m["conversation"] == row["id"] and m["sender"] != ADMIN and m["created_at"] > row["read"].get(ADMIN, "")
        )
        return {
            **{k: v for k, v in row.items() if k not in ("members", "read")},
            "participants": [{"member": m, "name": self.members[m]["name"], "active": True} for m in row["members"]],
            "unread_count": unread,
            "is_participant": ADMIN in row["members"],
        }

    def _body(self, request, body):
        if request.headers.get("content-type", "").startswith("multipart/"):
            self.uploads.append(request.content)
            fields, files = multipart(request)
            flat = {k: (v if k == "participants" else v[0]) for k, v in fields.items()}
            return flat, files
        return body, []

    # --- routes -----------------------------------------------------------------------
    def _comm(self, request, path, body, admin):
        ok, fail = self._c_ok, self._c_fail
        method, params = request.method, request.url.params
        parts = path.split("/")
        not_found = fail(404, "NOT_FOUND", "Introuvable.")
        if path.startswith("admin/") and not admin:
            return fail(403, "PERMISSION_DENIED", "Permission refusée.")
        # notifications
        if path == "notifications/":
            rows = sorted(self.notifications, key=lambda n: n["created_at"], reverse=True)
            if params.get("is_read") in ("true", "false"):
                rows = [r for r in rows if r["is_read"] == (params["is_read"] == "true")]
            if params.get("type"):
                rows = [r for r in rows if r["notification_type"] == params["type"]]
            return self._page(rows, request)
        if path == "notifications/unread-count/":
            return ok({"unread": sum(1 for n in self.notifications if not n["is_read"])})
        if path == "notifications/read-all/":
            count = 0
            for n in self.notifications:
                if not n["is_read"]:
                    n.update(is_read=True, read_at=NOW)
                    count += 1
            return ok({"marked": count})
        if parts[0] == "notifications" and parts[2:3] == ["read"]:
            row = next((n for n in self.notifications if n["id"] == parts[1]), None)
            if row is None:
                return not_found
            row.update(is_read=True, read_at=NOW)
            return ok(row)
        if path == "admin/communication/members/":
            rows = list(self.members.values())
            if params.get("role"):
                rows = [m for m in rows if params["role"] in m["roles"]]
            if params.get("search"):
                rows = [m for m in rows if params["search"].lower() in m["name"].lower()]
            return self._page(rows, request)
        # conversations
        if path == "conversations/":
            if method == "POST":
                data, files = self._body(request, body)
                if files and (refused := self._check_files(files)):
                    return refused
                others = data.get("participants") or []
                if not others:
                    return fail(400, "BUSINESS_RULE_VIOLATION", "Participants.", {"rule": "participants_required"})
                if any(m not in self.members for m in others):
                    return not_found
                cid = self.add_conversation(others, data.get("title") or "")
                mid = self.add_message(cid, ADMIN, data.get("body") or "")
                for _, name, content, mime in files:
                    self.chat[mid]["attachments"].append(self._store_file("message", mid, name, content, mime))
                return ok(self._conversation_out(self.conversations[cid]), 201)
            rows = [c for c in self.conversations.values() if admin or ADMIN in c["members"]]
            if params.get("type"):
                rows = [c for c in rows if c["conversation_type"] == params["type"]]
            return self._page([self._conversation_out(c) for c in rows], request)
        if parts[0] == "conversations" and len(parts) >= 3:
            row = self.conversations.get(parts[1])
            if row is None:
                return not_found
            action = parts[2]
            if action == "":
                return ok(self._conversation_out(row))
            if action == "messages":
                if method == "POST":
                    data, files = self._body(request, body)
                    if files and (refused := self._check_files(files)):
                        return refused
                    if not row["active"]:
                        return fail(409, "CONFLICT", "Fermée.", {"rule": "conversation_closed"})
                    existing = next(
                        (
                            m
                            for m in self.chat.values()
                            if data.get("client_id") and m["client_id"] == data["client_id"]
                        ),
                        None,
                    )
                    if existing:
                        return ok(existing, 200)
                    mid = self.add_message(row["id"], ADMIN, data["body"])
                    self.chat[mid]["client_id"] = data.get("client_id")
                    for _, name, content, mime in files:
                        self.chat[mid]["attachments"].append(self._store_file("message", mid, name, content, mime))
                    return ok(self.chat[mid], 201)
                rows = [m for m in self.chat.values() if m["conversation"] == row["id"]]
                return self._page(sorted(rows, key=lambda m: m["created_at"], reverse=True), request)
            if action == "read":
                row["read"][ADMIN] = "9999"
                return ok({"last_read_at": NOW})
            if action == "participants":
                member = self.members.get(body.get("member"))
                if member is None:
                    return not_found
                if not {"ADMIN", "SUPER_ADMIN"} & set(member["roles"]):
                    return fail(403, "PERMISSION_DENIED", "Seuls les administrateurs.")
                if member["id"] not in row["members"]:
                    row["members"].append(member["id"])
                return ok(self._conversation_out(row), 201)
        if parts[0] == "messages" and method == "DELETE":
            message = self.chat.get(parts[1])
            if message is None:
                return not_found
            if message["deleted_at"]:
                return fail(409, "CONFLICT", "Déjà.", {"rule": "message_already_deleted"})
            message["deleted_at"] = NOW  # hidden, kept (admin still sees the body)
            return ok(message)
        if parts[0] == "attachments" and len(parts) >= 4 and parts[3] == "download":
            stored = self.files.get(parts[2])
            if stored is None or stored[0] != parts[1]:
                return not_found
            return httpx.Response(200, content=stored[4], headers={"content-type": stored[3]})
        # forum
        if path == "forum/spaces/":
            return ok(list(self.spaces.values()))
        if path == "admin/forum/spaces/":
            if body.get("audience") == "SCHOOL" and not body.get("roles"):
                return fail(400, "BUSINESS_RULE_VIOLATION", "Rôles.", {"rule": "roles_required"})
            sid = self.add_space(body["name"], body.get("roles") or [], body.get("announcements_only", False))
            return ok(self.spaces[sid], 201)
        if path == "forum/threads/":
            if method == "POST":
                if body.get("space") not in self.spaces:
                    return not_found
                tid = self.add_thread(body["space"], body["title"], body["body"], body.get("thread_type", "GENERAL"))
                return ok(self.threads[tid], 201)
            rows = list(self.threads.values())
            if params.get("space"):
                rows = [t for t in rows if t["space"] == params["space"]]
            return self._page(rows, request)
        if parts[:2] == ["forum", "threads"] and len(parts) >= 4:
            thread = self.threads.get(parts[2])
            if thread is None:
                return not_found
            if parts[3] == "posts":
                if method == "POST":
                    if thread["status"] != "OPEN":
                        return fail(409, "CONFLICT", "Verrouillé.", {"rule": "thread_locked"})
                    pid = self._post(thread["id"], ADMIN, body["body"])
                    return ok(self.posts[pid], 201)
                return self._page([p for p in self.posts.values() if p["thread"] == thread["id"]], request)
            return ok(thread)
        if parts[:2] == ["forum", "posts"] and method == "DELETE":
            post = self.posts.get(parts[2])
            if post is None:
                return not_found
            if post["deleted_at"]:
                return fail(409, "CONFLICT", "Déjà.", {"rule": "post_already_deleted"})
            post.update(deleted_at=NOW, deletion_reason=(body or {}).get("reason"))
            return ok(post)
        if parts[:3] == ["admin", "forum", "threads"] and parts[4:5] == ["status"]:
            thread = self.threads.get(parts[3])
            if thread is None:
                return not_found
            thread.update(status=body["status"], status_reason=body.get("reason"))
            return ok(thread)
        # complaints
        if path == "complaints/":
            rows = list(self.complaints.values())
            for key in ("status", "category"):
                if params.get(key):
                    rows = [c for c in rows if c[key] == params[key]]
            return self._page(
                [{k: v for k, v in c.items() if k not in ("history", "attachments")} for c in rows], request
            )
        if parts[0] == "complaints" and len(parts) >= 3:
            complaint = self.complaints.get(parts[1])
            if complaint is None:
                return not_found
            if parts[2] == "":
                return ok(complaint)
            if parts[2] == "cancel":
                if complaint["status"] in ("CANCELLED", "CLOSED"):
                    return fail(409, "CONFLICT", "Finale.", {"rule": "complaint_final"})
                self._history(complaint, "CANCELLED", body.get("reason"))
                return ok(complaint)
            if parts[2] == "attachments":
                _, files = self._body(request, body)
                if refused := self._check_files(files):
                    return refused
                created = [self._store_file("complaint", complaint["id"], n, c, t) for _, n, c, t in files]
                complaint["attachments"] += created
                return ok(created, 201)
        if parts[:2] == ["admin", "complaints"] and parts[3:4] == ["status"]:
            complaint = self.complaints.get(parts[2])
            if complaint is None:
                return not_found
            if complaint["status"] in ("CANCELLED", "CLOSED"):
                return fail(409, "CONFLICT", "Finale.", {"rule": "complaint_final"})
            if body.get("assigned_to"):
                if body["assigned_to"] not in self.members:
                    return not_found
                complaint["assigned_to"] = body["assigned_to"]
            status = body.get("status")
            if status:
                allowed = {
                    ("OPEN", "IN_PROGRESS"),
                    ("OPEN", "RESOLVED"),
                    ("IN_PROGRESS", "RESOLVED"),
                    ("RESOLVED", "CLOSED"),
                    ("RESOLVED", "IN_PROGRESS"),
                }
                if (complaint["status"], status) not in allowed:
                    return fail(409, "CONFLICT", "Transition.", {"rule": "invalid_transition"})
                if status in ("RESOLVED", "CLOSED") and not body.get("reason"):
                    return fail(400, "BUSINESS_RULE_VIOLATION", "Motif.", {"rule": "reason_required"})
                self._history(complaint, status, body.get("reason"))
            return ok(complaint)
        return None

    def _history(self, complaint, status, comment):
        complaint["history"].append(
            {
                "old_status": complaint["status"],
                "new_status": status,
                "changed_by": ADMIN,
                "comment": comment,
                "at": NOW,
            }
        )
        complaint["status"] = status

    # --- documents --------------------------------------------------------------------
    def _documents(self, request, path, body, admin):
        ok, fail = self._c_ok, self._c_fail
        method, params = request.method, request.url.params
        parts = path.split("/")
        not_found = fail(404, "NOT_FOUND", "Introuvable.")
        visible = lambda: [d for d in self.documents_store.values() if admin]  # noqa: E731
        if path == "documents/" and method == "GET":
            rows = sorted(visible(), key=lambda d: d["generated_at"], reverse=True)
            for key in ("kind", "status"):
                if params.get(key):
                    rows = [d for d in rows if d[key] == params[key]]
            search = (params.get("search") or "").lower()
            if search:
                rows = [d for d in rows if search in d["title"].lower() or search == d["verification_code"].lower()]
            return self._page([{k: v for k, v in d.items() if k != "_source"} for d in rows], request)
        if path == "documents/" and method == "POST":
            kind = body.get("kind")
            required = {
                "REPORT_CARD": ("report_card",),
                "PAYMENT_RECEIPT": ("payment",),
                "PAYSLIP": ("payroll",),
                "STUDENT_CARD": ("student",),
                "STUDENT_ATTENDANCE": ("student", "date_from", "date_to"),
                "CLASS_ATTENDANCE": ("school_class", "date"),
                "TIMETABLE": (),
            }[kind]
            missing = [f for f in required if not body.get(f)]
            if missing:
                return fail(
                    400, "VALIDATION_ERROR", "Données invalides.", {f: ["Required for this kind."] for f in missing}
                )
            source = next(
                (
                    body[f]
                    for f in ("report_card", "payment", "payroll", "student", "school_class", "teacher")
                    if body.get(f)
                ),
                None,
            )
            title = f"{kind} — {source}"
            if kind == "PAYMENT_RECEIPT":
                payment = self.payments.get(source)
                if payment is None:
                    return not_found
                if payment["status"] not in ("SUCCEEDED", "PARTIALLY_REFUNDED", "REFUNDED"):
                    return fail(409, "CONFLICT", "Source.", {"rule": "document_source_not_final"})
                title = f"Reçu {payment['payment_reference']}"
            elif kind in ("STUDENT_CARD", "STUDENT_ATTENDANCE"):
                if source not in self.students:
                    return not_found
                title = f"{'Carte' if kind == 'STUDENT_CARD' else 'Relevé'} — {self._student_name(source)}"
            elif kind == "REPORT_CARD" and source not in {c["id"] for c in self.report_cards}:
                return not_found
            existing = next(
                (
                    d
                    for d in self.documents_store.values()
                    if d["_source"] == (kind, source) and d["status"] != "SUPERSEDED"
                ),
                None,
            )
            if existing:
                return ok({k: v for k, v in existing.items() if k != "_source"}, 200)
            did = self.add_document(
                kind, title, "OFFICIAL" if kind == "PAYMENT_RECEIPT" else "PROVISIONAL", (kind, source)
            )
            return ok({k: v for k, v in self.documents_store[did].items() if k != "_source"}, 201)
        if path == "documents/verify/":
            document = next(
                (
                    d
                    for d in self.documents_store.values()
                    if d["verification_code"] == (params.get("code") or "").upper()
                ),
                None,
            )
            if document is None:
                return not_found
            return ok(
                {
                    "valid": True,
                    "kind": document["kind"],
                    "status": document["status"],
                    "title": document["title"],
                    "generated_at": document["generated_at"],
                    "sha256": document["sha256"],
                    "current": document["status"] != "SUPERSEDED",
                }
            )
        if parts[0] == "documents" and len(parts) >= 3:
            document = self.documents_store.get(parts[1])
            if document is None or not admin:
                return not_found
            if parts[2] == "":
                return ok({k: v for k, v in document.items() if k != "_source"})
            if parts[2] == "download":
                return httpx.Response(
                    200,
                    content=b"%PDF-1.4\n% Ecole Test (SchoolBranding)\n" + document["title"].encode(),
                    headers={"content-type": "application/pdf"},
                )
            if parts[2] == "regenerate":
                if document["status"] == "OFFICIAL":
                    return fail(409, "CONFLICT", "Officiel.", {"rule": "document_official"})
                document["status"] = "SUPERSEDED"
                did = self.add_document(document["kind"], document["title"], "PROVISIONAL", document["_source"])
                self.documents_store[did]["version"] = document["version"] + 1
                return ok({k: v for k, v in self.documents_store[did].items() if k != "_source"}, 201)
        if path == "report-cards/":
            rows = [c for c in self.report_cards if not params.get("student") or c["student"] == params["student"]]
            return self._page(rows, request)
        if path == "academic-periods/":
            return self._page(getattr(self, "periods_list", []), request)
        if path == "report-cards/generate/":
            if not admin:
                return fail(403, "PERMISSION_DENIED", "Permission refusée.")
            return ok(self.report_cards, 201)
        return None

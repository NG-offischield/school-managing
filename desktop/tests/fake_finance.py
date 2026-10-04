"""Finance + payroll part of the fake API (mixin of FakeBackend).

It reproduces the CONTRACT the desktop relies on (amounts as strings,
payment outcomes as results, idempotent replay, 403 / 404 / 409 rules the
screens must surface), not the backend's accounting. Amounts are handled
as Decimal here too."""

import uuid
from decimal import Decimal

import httpx

D = Decimal
ADMIN_MEMBERSHIP = "m1"  # the logged-in administrator (auth/me)


def s(value):
    return f"{D(value):.2f}"


class FinanceFake:
    @staticmethod
    def _ok(data, status=200, meta=None):
        return httpx.Response(status, json={"success": True, "data": data, "message": None, "meta": meta})

    @staticmethod
    def _fail(status, code, message, details=None):
        error = {"code": code, "message": message}
        if details is not None:
            error["details"] = details
        return httpx.Response(status, json={"success": False, "error": error})

    def init_finance(self):
        self.fee_types = {}
        self.invoices = {}
        self.payments = {}
        self.refunds = []
        self.wallets = {}
        self.treasury = {"balance": D("0"), "entries": []}
        self.periods = {}
        self.payrolls = {}
        self.adjustments = {}
        self.check_ins = []
        self.stale_payrolls = set()
        self.payment_bodies = []

    # --- seeds ------------------------------------------------------------------------
    def seed_finance(self):
        """Two students (6e A), fee type SCOL, three invoices, the admin's two
        simulated wallets (normal 50 000, always declined), a parent's wallet,
        treasury credited with 100 000."""
        cid = self._class("6e A")
        self.sa = self.add_student("MAT-001", "Ndiaye", "Awa", "F", class_id=cid)
        self.sb = self.add_student("MAT-002", "Kamga", "Paul", "M", class_id=cid)
        self.scol = self.add_fee_type("SCOL", "Scolarité")
        self.inv1 = self.add_invoice(self.sa, "60000", "2025-10-15", "F25-000001")
        self.inv2 = self.add_invoice(self.sa, "40000", "2026-01-15", "F25-000002")
        self.inv3 = self.add_invoice(self.sb, "50000", "2025-11-15", "F25-000003")
        self.w_admin = self.add_wallet(ADMIN_MEMBERSHIP, "Ada Admin", "FAKE_ORANGE", "690000001", "50000")
        self.w_decline = self.add_wallet(ADMIN_MEMBERSHIP, "Ada Admin", "FAKE_MTN", "670000002", "90000", "DECLINE")
        self.w_parent = self.add_wallet("m-parent", "Parent Ndiaye", "FAKE_ORANGE", "699999999", "10000")
        self._treasury("CREDIT", "FUNDING", "100000", "TRE-INIT")

    def seed_payroll(self):
        """Teachers (seed_teachers) + period Octobre 2025: Jean Mbarga prepared
        (programmed 20 000, earned 10 000, correction +5 000), Marie Ngo approved
        (8 000), a staff member paid (150 000). Jean Mbarga has a wallet."""
        if not getattr(self, "tm", None):
            self.seed_teachers()
        if not self.treasury["entries"]:
            self._treasury("CREDIT", "FUNDING", "1000000", "TRE-INIT")
        self.p_oct = self.add_period("Octobre 2025", "2025-10-01", "2025-10-31")
        self.e_tm, self.e_tf = f"emp-{self.tm}", f"emp-{self.tf}"
        self.pr_tm = self.add_payroll(self.e_tm, "Jean Mbarga", self.p_oct, "CALCULATED", "20000", "10000", "5000")
        self.pr_tf = self.add_payroll(self.e_tf, "Marie Ngo", self.p_oct, "APPROVED", "8000", "8000", "0")
        self.pr_staff = self.add_payroll(
            "emp-staff", "Luc Staff", self.p_oct, "PAID", None, None, "0", kind="STAFF", salary="150000"
        )
        self.adj = self.add_adjustment(self.e_tm, "5000", "Prime d'examen")
        self.w_tm = self.add_wallet("m-tm", "Jean Mbarga", "FAKE_ORANGE", "655000123", "0")
        self.check_ins = [
            {"id": "c1", "teacher": self.tm, "verified_status": "VALIDATED"},
            {"id": "c2", "teacher": self.tm, "verified_status": "VALIDATED"},
            {"id": "c3", "teacher": self.tf, "verified_status": "PENDING"},
        ]

    # --- builders ---------------------------------------------------------------------
    def add_fee_type(self, code, name, active=True):
        fid = str(uuid.uuid4())
        self.fee_types[fid] = {"id": fid, "code": code, "name": name, "description": "", "active": active}
        return fid

    def add_invoice(self, student, total, due, number=None):
        iid = str(uuid.uuid4())
        number = number or f"F25-{len(self.invoices) + 1:06d}"
        self.invoices[iid] = {
            "id": iid,
            "invoice_number": number,
            "student": student,
            "issue_date": "2025-09-15",
            "due_date": due,
            "status": "ISSUED",
            "total": D(total),
            "paid": D("0"),
            "currency": "XAF",
            "cancelled_reason": None,
            "lines": [{"description": "Scolarité", "fee_type_code": "SCOL", "total": s(total)}],
        }
        return iid

    def add_wallet(self, owner, owner_name, provider, identifier, balance, behavior="NORMAL"):
        wid = str(uuid.uuid4())
        self.wallets[wid] = {
            "id": wid,
            "owner": owner,
            "owner_name": owner_name,
            "wallet_type": "SIMULATED",
            "provider_code": provider,
            "wallet_identifier": identifier,
            "balance": D(balance),
            "currency": "XAF",
            "status": "ACTIVE",
            "simulation_behavior": behavior,
        }
        return wid

    def add_period(self, name, start, end, status="OPEN"):
        pid = str(uuid.uuid4())
        self.periods[pid] = {
            "id": pid,
            "academic_year": "y1",
            "name": name,
            "start_date": start,
            "end_date": end,
            "status": status,
            "closed_at": None,
        }
        return pid

    def add_payroll(self, employee, name, period, status, programmed, earned, adjustments, kind="TEACHER", salary=None):
        rid = str(uuid.uuid4())
        payable = D(earned or salary or "0") + D(adjustments)
        self.payrolls[rid] = {
            "id": rid,
            "kind": kind,
            "employee": employee,
            "employee_name": name,
            "period": period,
            "status": status,
            "version": 1,
            "programmed": programmed,
            "earned": earned,
            "salary": salary,
            "adjustments": D(adjustments),
            "payable": payable,
            "approved": payable if status in ("APPROVED", "PAID") else None,
            "paid_at": "2025-11-02T10:00:00+01:00" if status == "PAID" else None,
            "payment_reference": "PAYR-OLD" if status == "PAID" else None,
            "payout_method": "CASH" if status == "PAID" else None,
            "cancelled_reason": None,
        }
        return rid

    def add_adjustment(self, employee, amount, reason):
        aid = str(uuid.uuid4())
        self.adjustments[aid] = {
            "id": aid,
            "employee": employee,
            "amount": s(amount),
            "reason": reason,
            "effective_date": "2025-10-20",
            "source": "MANUAL",
            "settled_teacher_payroll": None,
            "settled_staff_payroll": None,
            "created_at": "2025-10-20T09:00:00+01:00",
        }
        return aid

    def _treasury(self, direction, kind, amount, reference):
        before = self.treasury["balance"]
        after = before + D(amount) if direction == "CREDIT" else before - D(amount)
        self.treasury["balance"] = after
        self.treasury["entries"].insert(
            0,
            {
                "id": str(uuid.uuid4()),
                "transaction_type": kind,
                "direction": direction,
                "amount": s(amount),
                "reference": reference,
                "balance_before": s(before),
                "balance_after": s(after),
                "created_at": "2026-03-04T10:00:00+01:00",
            },
        )

    # --- serializers ------------------------------------------------------------------
    def _student_name(self, sid):
        row = self.students.get(sid) or {}
        return f"{row.get('first_name', '')} {row.get('last_name', '')}".strip()

    def _invoice_out(self, row):
        return {
            **{k: v for k, v in row.items() if k not in ("total", "paid")},
            "student_name": self._student_name(row["student"]),
            "academic_year": "y1",
            "total_amount": s(row["total"]),
            "amount_paid": s(row["paid"]),
            "balance_due": s(row["total"] - row["paid"]),
        }

    def _payment_out(self, row):
        return {
            **{k: v for k, v in row.items() if not k.startswith("_")},
            "student_name": self._student_name(row["student"]),
            "amount": s(row["amount"]),
            "refunded_amount": s(row["refunded_amount"]),
            "refunds": [r for r in self.refunds if r["payment"] == row["id"]],
        }

    def _wallet_out(self, row):
        return {**row, "balance": s(row["balance"])}

    def _payroll_out(self, row, detail=False):
        period = self.periods[row["period"]]
        data = {
            "id": row["id"],
            "kind": row["kind"],
            "employee": row["employee"],
            "employee_name": row["employee_name"],
            "period": row["period"],
            "period_name": period["name"],
            "status": row["status"],
            "version": row["version"],
            "adjustments_amount": s(row["adjustments"]),
            "payable_amount": s(row["payable"]),
            "approved_amount": s(row["approved"]) if row["approved"] is not None else None,
            "approved_at": None,
            "paid_at": row["paid_at"],
            "payout_method": row["payout_method"],
            "payment_reference": row["payment_reference"],
            "currency": "XAF",
            "calculated_at": "2025-11-01T08:00:00+01:00",
            "cancelled_reason": row["cancelled_reason"],
        }
        if row["kind"] == "TEACHER":
            data.update(
                programmed_amount=s(row["programmed"]),
                earned_amount=s(row["earned"]),
                scheduled_sessions_count=4,
                completed_sessions_count=2,
                payable_sessions_count=2,
            )
        else:
            data.update(base_salary=s(row["salary"]), gross_amount=s(row["payable"]))
        if detail:
            lines = [
                {
                    "version": 1,
                    "kind": "PROGRAMMED",
                    "session_date": "2025-10-06",
                    "duration_minutes": 120,
                    "rate": "5000.00",
                    "amount": "5000.00",
                    "late": False,
                },
                {
                    "version": row["version"],
                    "kind": "EARNED",
                    "session_date": "2025-10-06",
                    "duration_minutes": 120,
                    "rate": "5000.00",
                    "amount": "5000.00",
                    "late": False,
                },
                {
                    "version": row["version"],
                    "kind": "ADJUSTMENT",
                    "session_date": None,
                    "duration_minutes": None,
                    "rate": None,
                    "amount": s(row["adjustments"]),
                    "late": False,
                },
            ]
            data["lines"] = lines if row["kind"] == "TEACHER" else []
            data["reconstructible"] = row["id"] not in self.stale_payrolls
        return data

    # --- finance routes ---------------------------------------------------------------
    def _finance(self, request, path, body, admin):
        method, params = request.method, request.url.params
        if path == "admin/finance/dashboard/":
            if not admin:
                return self._fail(403, "PERMISSION_DENIED", "Permission refusée.")
            counts = {}
            for p in self.payments.values():
                counts[p["status"]] = counts.get(p["status"], 0) + 1
            failed = sum(counts.get(k, 0) for k in ("DECLINED", "INSUFFICIENT_FUNDS", "TIMEOUT", "PROVIDER_ERROR"))
            refunded = sum((D(r["amount"]) for r in self.refunds), D("0"))
            return self._ok(
                {
                    **self.finance,
                    "refunded": s(refunded),
                    "treasury_balance": s(self.treasury["balance"]),
                    "payments_by_status": counts,
                    "failed_payments": failed,
                }
            )
        if path.startswith("admin/") and not admin:
            return self._fail(403, "PERMISSION_DENIED", "Permission refusée.")
        parts = path.split("/")
        if path == "finance/payments/" and method == "GET":
            rows = list(self.payments.values()) if admin else []  # no linked child in the fake
            if params.get("status"):
                rows = [r for r in rows if r["status"] == params["status"]]
            if params.get("payment_method"):
                rows = [r for r in rows if r["payment_method"] == params["payment_method"]]
            search = (params.get("search") or "").lower()
            if search:
                rows = [
                    r
                    for r in rows
                    if search in r["payment_reference"].lower() or search in self._student_name(r["student"]).lower()
                ]
            if params.get("date_from"):
                rows = [r for r in rows if r["initiated_at"][:10] >= params["date_from"]]
            if params.get("date_to"):
                rows = [r for r in rows if r["initiated_at"][:10] <= params["date_to"]]
            rows = sorted(rows, key=lambda r: r["_order"], reverse=True)
            return self._page([self._payment_out(r) for r in rows], request)
        if path == "finance/payments/" and method == "POST":
            return self._pay(body, admin)
        if len(parts) == 4 and parts[:2] == ["finance", "payments"]:
            row = self.payments.get(parts[2])
            return self._ok(self._payment_out(row)) if row and admin else self._fail(404, "NOT_FOUND", "Introuvable.")
        if parts[:3] == ["admin", "finance", "payments"] and parts[4:5] == ["refund"]:
            return self._refund(parts[3], body)
        if path == "admin/finance/refunds/":
            rows = []
            for refund in self.refunds:
                payment = self.payments[refund["payment"]]
                rows.append(
                    {
                        **refund,
                        "payment_reference": payment["payment_reference"],
                        "payment_amount": s(payment["amount"]),
                        "payment_method": payment["payment_method"],
                        "student_name": self._student_name(payment["student"]),
                        "currency": "XAF",
                    }
                )
            search = (params.get("search") or "").lower()
            if search:
                rows = [
                    r for r in rows if search in f"{r['payment_reference']} {r['student_name']} {r['reason']}".lower()
                ]
            return self._page(rows, request)
        if path == "finance/invoices/":
            rows = list(self.invoices.values()) if admin else []
            if params.get("status"):
                rows = [r for r in rows if r["status"] == params["status"]]
            search = (params.get("search") or "").lower()
            if search:
                rows = [
                    r
                    for r in rows
                    if search in r["invoice_number"].lower() or search in self._student_name(r["student"]).lower()
                ]
            if params.get("date_from"):
                rows = [r for r in rows if r["issue_date"] >= params["date_from"]]
            rows.sort(key=lambda r: (r["due_date"], r["invoice_number"]))
            return self._page([self._invoice_out(r) for r in rows], request)
        if len(parts) == 4 and parts[:2] == ["finance", "invoices"]:
            row = self.invoices.get(parts[2])
            return self._ok(self._invoice_out(row)) if row and admin else self._fail(404, "NOT_FOUND", "Introuvable.")
        if parts[:2] == ["finance", "students"] and parts[3:4] == ["obligations"]:
            if parts[2] not in self.students:
                return self._fail(404, "NOT_FOUND", "Introuvable.")
            open_rows = [
                self._invoice_out(r)
                for r in sorted(self.invoices.values(), key=lambda r: r["due_date"])
                if r["student"] == parts[2] and r["status"] in ("ISSUED", "PARTIALLY_PAID")
            ]
            return self._ok({"student": parts[2], "currency": "XAF", "open_invoices": open_rows})
        if path == "admin/finance/invoices/" and method == "POST":
            if body["student"] not in self.students:
                return self._fail(404, "NOT_FOUND", "Introuvable.")
            line = body["lines"][0]
            iid = self.add_invoice(body["student"], line["unit_price"], body["due_date"])
            self.invoices[iid]["lines"] = [
                {
                    "description": line.get("description") or "SCOL",
                    "fee_type_code": "SCOL",
                    "total": s(line["unit_price"]),
                }
            ]
            return self._ok(self._invoice_out(self.invoices[iid]), 201)
        if parts[:3] == ["admin", "finance", "invoices"] and parts[4:5] == ["cancel"]:
            row = self.invoices.get(parts[3])
            if row is None:
                return self._fail(404, "NOT_FOUND", "Introuvable.")
            if row["paid"] > 0:
                return self._fail(409, "CONFLICT", "Paiements.", {"rule": "invoice_has_payments"})
            row.update(status="CANCELLED", cancelled_reason=body.get("reason"))
            return self._ok(self._invoice_out(row))
        if path == "admin/finance/fee-types/":
            if method == "POST":
                if any(f["code"] == body["code"] for f in self.fee_types.values()):
                    return self._fail(409, "CONFLICT", "Code.", {"rule": "duplicate_code"})
                fid = self.add_fee_type(body["code"], body["name"])
                return self._ok(self.fee_types[fid], 201)
            return self._page(sorted(self.fee_types.values(), key=lambda f: f["code"]), request)
        if path == "admin/finance/wallets/":
            return self._page([self._wallet_out(w) for w in self.wallets.values()], request)
        if path == "finance/wallets/":
            mine = [self._wallet_out(w) for w in self.wallets.values() if w["owner"] == ADMIN_MEMBERSHIP]
            return self._page(mine, request)
        if path == "admin/finance/treasury/":
            return self._ok(
                {
                    "balance": s(self.treasury["balance"]),
                    "currency": "XAF",
                    "recent_transactions": self.treasury["entries"],
                }
            )
        return None

    def _pay(self, body, admin):
        self.payment_bodies.append(body)
        key = body.get("idempotency_key")
        fingerprint = (
            body["student"],
            s(body["amount"]),
            body["payment_method"],
            body.get("wallet"),
            tuple(sorted(body.get("invoices") or [])),
            body.get("fee_type"),
        )
        existing = next((p for p in self.payments.values() if p["_key"] == key), None)
        if existing is not None:
            if existing["_fingerprint"] != fingerprint:
                return self._fail(409, "CONFLICT", "Clé.", {"rule": "idempotency_conflict"})
            return self._ok({**self._payment_out(existing), "replayed": True}, 200)
        if body["student"] not in self.students:
            return self._fail(404, "NOT_FOUND", "Introuvable.")
        if body["payment_method"] == "CASH" and not admin:
            return self._fail(403, "PERMISSION_DENIED", "Espèces : administration uniquement.")
        amount = D(body["amount"])
        if amount <= 0:
            return self._fail(400, "BUSINESS_RULE_VIOLATION", "Montant.", {"rule": "invalid_amount"})
        invoices = [self.invoices.get(i) for i in body.get("invoices") or []]
        if any(i is None for i in invoices):
            return self._fail(404, "NOT_FOUND", "Introuvable.")
        if invoices:
            if amount > sum((i["total"] - i["paid"] for i in invoices), D("0")):
                return self._fail(409, "CONFLICT", "Trop.", {"rule": "amount_exceeds_balance"})
        elif not body.get("fee_type"):
            return self._fail(400, "BUSINESS_RULE_VIOLATION", "Motif.", {"rule": "payment_reason_required"})
        wallet = None
        status, reason = "SUCCEEDED", None
        if body["payment_method"] == "WALLET":
            wallet = self.wallets.get(body.get("wallet") or "")
            if wallet is None:
                return self._fail(400, "BUSINESS_RULE_VIOLATION", "Wallet.", {"rule": "wallet_required"})
            if wallet["owner"] != ADMIN_MEMBERSHIP:
                return self._fail(403, "PERMISSION_DENIED", "Seulement votre propre portefeuille.")
            behaviour = wallet["simulation_behavior"]
            if behaviour != "NORMAL":
                status = {"DECLINE": "DECLINED"}.get(behaviour, behaviour)
                reason = {"DECLINED": "Paiement refusé par le fournisseur."}.get(
                    status, "Le fournisseur n'a pas répondu."
                )
            elif wallet["balance"] < amount:
                status, reason = "INSUFFICIENT_FUNDS", "Solde du portefeuille insuffisant."
        pid = str(uuid.uuid4())
        reference = f"PAY-{len(self.payments) + 1:06d}"
        allocations = []
        if status == "SUCCEEDED":
            remaining = amount
            for invoice in sorted(invoices, key=lambda i: i["due_date"]):
                part = min(remaining, invoice["total"] - invoice["paid"])
                if part > 0:
                    invoice["paid"] += part
                    invoice["status"] = "PAID" if invoice["paid"] == invoice["total"] else "PARTIALLY_PAID"
                    allocations.append(
                        {
                            "id": str(uuid.uuid4()),
                            "invoice": invoice["id"],
                            "invoice_number": invoice["invoice_number"],
                            "amount": s(part),
                            "refund": None,
                            "allocated_at": "2026-03-04T10:00:00+01:00",
                        }
                    )
                    remaining -= part
            if wallet is not None:
                wallet["balance"] -= amount
            self._treasury("CREDIT", "PAYMENT", amount, reference)
        self.payments[pid] = {
            "id": pid,
            "payment_reference": reference,
            "student": body["student"],
            "payer": ADMIN_MEMBERSHIP,
            "initiated_by": ADMIN_MEMBERSHIP,
            "fee_type": body.get("fee_type"),
            "wallet": body.get("wallet"),
            "amount": amount,
            "refunded_amount": D("0"),
            "currency": "XAF",
            "payment_method": body["payment_method"],
            "provider": "SIMULATION_WALLET" if wallet else "CASH",
            "status": status,
            "initiated_at": "2026-03-04T10:00:00+01:00",
            "completed_at": "2026-03-04T10:00:01+01:00",
            "failure_reason": reason,
            "provider_reference": f"SIM-{pid[:8]}" if status == "SUCCEEDED" and wallet else None,
            "allocations": allocations,
            "_key": key,
            "_fingerprint": fingerprint,
            "_order": len(self.payments),
        }
        return self._ok({**self._payment_out(self.payments[pid]), "replayed": False}, 201)

    def _refund(self, payment_id, body):
        payment = self.payments.get(payment_id)
        if payment is None:
            return self._fail(404, "NOT_FOUND", "Introuvable.")
        if payment["status"] not in ("SUCCEEDED", "PARTIALLY_REFUNDED"):
            return self._fail(409, "CONFLICT", "Non remboursable.", {"rule": "payment_not_refundable"})
        amount = D(body["amount"])
        if amount > payment["amount"] - payment["refunded_amount"]:
            return self._fail(409, "CONFLICT", "Trop.", {"rule": "refund_exceeds_payment"})
        payment["refunded_amount"] += amount
        payment["status"] = "REFUNDED" if payment["refunded_amount"] == payment["amount"] else "PARTIALLY_REFUNDED"
        refund = {
            "id": str(uuid.uuid4()),
            "payment": payment_id,
            "amount": s(amount),
            "reason": body["reason"],
            "status": "COMPLETED",
            "completed_at": "2026-03-04T11:00:00+01:00",
            "inverse_transaction_reference": f"REF-{len(self.refunds) + 1:04d}",
        }
        self.refunds.append(refund)
        self._treasury("DEBIT", "REFUND", amount, refund["inverse_transaction_reference"])
        return self._ok(refund, 201)

    # --- payroll routes ---------------------------------------------------------------
    def _payroll(self, request, path, body, admin):
        if not admin:
            return self._fail(403, "PERMISSION_DENIED", "Permission refusée.")
        method, params = request.method, request.url.params
        parts = path.split("/")
        if path == "admin/payroll/periods/":
            if method == "POST":
                for p in self.periods.values():
                    if p["name"] == body["name"] or not (
                        body["end_date"] < p["start_date"] or body["start_date"] > p["end_date"]
                    ):
                        return self._fail(409, "CONFLICT", "Chevauchement.", {"rule": "period_overlap"})
                pid = self.add_period(body["name"], body["start_date"], body["end_date"])
                return self._ok(self.periods[pid], 201)
            return self._page(sorted(self.periods.values(), key=lambda p: p["start_date"]), request)
        if parts[:3] == ["admin", "payroll", "periods"] and parts[4:5] == ["close"]:
            period = self.periods.get(parts[3])
            if period is None:
                return self._fail(404, "NOT_FOUND", "Introuvable.")
            if any(
                r["period"] == period["id"] and r["status"] in ("CALCULATED", "APPROVED")
                for r in self.payrolls.values()
            ):
                return self._fail(409, "CONFLICT", "Non soldée.", {"rule": "period_not_settled"})
            period["status"] = "CLOSED"
            return self._ok(period)
        if path == "admin/payroll/calculate/":
            period = self.periods.get(body.get("period"))
            if period is None:
                return self._fail(404, "NOT_FOUND", "Introuvable.")
            if period["status"] == "CLOSED":
                return self._fail(409, "CONFLICT", "Clôturée.", {"rule": "period_closed"})
            summary = {"created": 0, "recalculated": 0, "unchanged": 0, "frozen": 0, "warnings": []}
            for row in self.payrolls.values():
                if row["period"] != period["id"] or row["status"] == "CANCELLED":
                    continue
                if row["status"] != "CALCULATED":
                    summary["frozen"] += 1
                elif row["id"] in self.stale_payrolls:
                    row["version"] += 1
                    self.stale_payrolls.discard(row["id"])
                    summary["recalculated"] += 1
                else:
                    summary["unchanged"] += 1
            if not any(r["period"] == period["id"] for r in self.payrolls.values()) and getattr(self, "tm", None):
                self.add_payroll(f"emp-{self.tm}", "Jean Mbarga", period["id"], "CALCULATED", "10000", "0", "0")
                summary["created"] += 1
                summary["warnings"].append({"code": "missing_rate", "session": "s1", "date": period["start_date"]})
            return self._ok(summary)
        if path == "admin/payroll/":
            rows = list(self.payrolls.values())
            for key, field in (("period", "period"), ("status", "status"), ("kind", "kind"), ("employee", "employee")):
                if params.get(key):
                    rows = [r for r in rows if r[field] == params[key]]
            return self._ok([self._payroll_out(r) for r in rows])
        if path == "admin/payroll/adjustments/":
            if method == "POST":
                aid = self.add_adjustment(body["employee"], body["amount"], body["reason"])
                return self._ok(self.adjustments[aid], 201)
            rows = list(self.adjustments.values())
            if params.get("employee"):
                rows = [r for r in rows if r["employee"] == params["employee"]]
            return self._page(rows, request)
        if path == "admin/payroll/remuneration/":
            if not params.get("date_from"):
                return self._fail(400, "VALIDATION_ERROR", "Dates.", {"date_from": ["Required."]})
            if params.get("employee") not in {r["employee"] for r in self.payrolls.values()}:
                return self._fail(404, "NOT_FOUND", "Introuvable.")
            return self._ok(
                {
                    "kind": "TEACHER",
                    "programmed_amount": "20000.00",
                    "earned_unpaid_amount": "10000.00",
                    "paid_amount": "0.00",
                    "sessions": {"scheduled": 4, "validated": 2, "paid": 0, "missing_rate": 0},
                }
            )
        if path == "admin/payroll/check-ins/":
            rows = [c for c in self.check_ins if not params.get("teacher") or c["teacher"] == params["teacher"]]
            rows = [c for c in rows if not params.get("status") or c["verified_status"] == params["status"]]
            return self._page(rows, request)
        if len(parts) >= 4 and parts[:2] == ["admin", "payroll"]:
            row = self.payrolls.get(parts[2])
            if row is None:
                return self._fail(404, "NOT_FOUND", "Introuvable.")
            action = parts[3]
            if not action:
                return self._ok(self._payroll_out(row, detail=True))
            codes = {
                "PAID": "payroll_already_paid",
                "CANCELLED": "payroll_cancelled",
                "APPROVED": "payroll_already_approved",
                "CALCULATED": "payroll_not_approved",
            }
            if action == "approve":
                if row["status"] != "CALCULATED":
                    return self._fail(409, "CONFLICT", "État.", {"rule": codes[row["status"]]})
                if row["id"] in self.stale_payrolls:
                    return self._fail(409, "CONFLICT", "Périmée.", {"rule": "payroll_stale"})
                row.update(status="APPROVED", approved=row["payable"])
            elif action == "pay":
                if row["status"] != "APPROVED":
                    return self._fail(409, "CONFLICT", "État.", {"rule": codes[row["status"]]})
                if body.get("payout_method") == "WALLET":
                    wallet = self.wallets.get(body.get("wallet") or "")
                    if wallet is None:
                        return self._fail(400, "BUSINESS_RULE_VIOLATION", "Wallet.", {"rule": "wallet_required"})
                    if wallet["owner_name"] != row["employee_name"]:
                        return self._fail(403, "PERMISSION_DENIED", "Le wallet de l'employé uniquement.")
                    wallet["balance"] += row["approved"]
                if self.treasury["balance"] < row["approved"]:
                    return self._fail(409, "CONFLICT", "Solde.", {"rule": "insufficient_balance"})
                reference = f"PAYR-{len(self.treasury['entries']):06d}"
                self._treasury("DEBIT", "PAYROLL", row["approved"], reference)
                row.update(
                    status="PAID",
                    paid_at="2026-03-04T12:00:00+01:00",
                    payment_reference=reference,
                    payout_method=body.get("payout_method"),
                )
            elif action == "cancel":
                if row["status"] not in ("CALCULATED", "APPROVED"):
                    return self._fail(409, "CONFLICT", "État.", {"rule": codes[row["status"]]})
                row.update(status="CANCELLED", cancelled_reason=body.get("reason"))
            return self._ok(self._payroll_out(row))
        return None

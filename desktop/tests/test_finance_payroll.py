"""Administration → Finance and → Paie (ADR 0022): thin clients of the
EXISTING finance and payroll domains. The outcome of a payment, refundable
amounts, approval checks and payments are the server's; the screens show
them. Amounts are Decimal (never float) and formatted."""

from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from PySide6.QtCore import QSize, Qt
from PySide6.QtTest import QTest

from school_admin.api.errors import Conflict, Forbidden, NotFound
from school_admin.config import AppConfig
from school_admin.money import format_money, parse_amount, to_decimal
from school_admin.services.finance import FinanceService, new_idempotency_key
from school_admin.services.payroll import PayrollService
from school_admin.ui.app import AppController
from school_admin.ui.dialogs.finance_dialogs import PaymentDetailDialog, PaymentDialog
from school_admin.ui.dialogs.payroll_dialogs import PayDialog, PayrollDetailDialog
from school_admin.ui.tasks import ImmediateRunner

from .fake_backend import PASSWORD

NB = " "  # thousands separator (narrow no-break space)


def xaf(text):
    return text.replace(" ", NB) + " XAF"


@pytest.fixture
def finance(logged_in, api, backend):
    backend.seed_finance()
    return FinanceService(api, today=lambda: date(2026, 3, 4))


@pytest.fixture
def payroll(logged_in, api, backend):
    backend.seed_payroll()
    return PayrollService(api)


def cash(backend, invoice, amount):
    return {
        "student_id": backend.sa,
        "amount": amount,
        "method": "CASH",
        "idempotency_key": new_idempotency_key(),
        "invoice_ids": [invoice],
        "fee_type_id": None,
        "wallet_id": None,
    }


# =============================================================================
# Money: Decimal, never float
# =============================================================================


def test_money_is_decimal_and_formatted():
    assert to_decimal("60000.00") == Decimal("60000.00")
    assert parse_amount("15 000,50") == Decimal("15000.50") and parse_amount("abc") is None
    with pytest.raises(TypeError):
        to_decimal(0.1)
    assert format_money("1250000.00", "XAF") == xaf("1 250 000")
    assert format_money(Decimal("15000.5"), "XAF") == xaf("15 000,50")


# =============================================================================
# Services
# =============================================================================


def test_payment_outcomes_are_results(finance, backend):
    ok = finance.initiate(**cash(backend, backend.inv1, "60000"))
    assert (ok.status, ok.amount, ok.allocations) == (
        "SUCCEEDED",
        Decimal("60000.00"),
        (("F25-000001", Decimal("60000.00"), False),),
    )
    assert isinstance(ok.amount, Decimal)
    poor = finance.initiate(
        **{**cash(backend, backend.inv2, "40000"), "method": "WALLET", "wallet_id": backend.w_admin, "amount": "40000"}
    )
    assert poor.status == "SUCCEEDED"
    insufficient = finance.initiate(
        **{
            **cash(backend, backend.inv3, "20000"),
            "student_id": backend.sb,
            "method": "WALLET",
            "wallet_id": backend.w_admin,
        }
    )
    assert (insufficient.status, insufficient.failed) == ("INSUFFICIENT_FUNDS", True)
    for behaviour, expected in (("DECLINE", "DECLINED"), ("TIMEOUT", "TIMEOUT"), ("PROVIDER_ERROR", "PROVIDER_ERROR")):
        backend.wallets[backend.w_decline]["simulation_behavior"] = behaviour
        result = finance.initiate(
            **{
                **cash(backend, backend.inv3, "1000"),
                "student_id": backend.sb,
                "method": "WALLET",
                "wallet_id": backend.w_decline,
            }
        )
        assert result.status == expected and result.failure_reason
    rows, total = finance.payments(status="SUCCEEDED")
    assert total == 2 and {r.reference for r in rows} == {ok.reference, poor.reference}
    assert finance.payments(method="CASH")[1] == 1
    assert finance.payments(search="awa")[1] == 2


def test_idempotent_replay_and_conflict(finance, backend):
    values = cash(backend, backend.inv1, "10000")
    first = finance.initiate(**values)
    again = finance.initiate(**values)
    assert (again.id, again.replayed) == (first.id, True)  # no second charge
    with pytest.raises(Conflict) as exc:
        finance.initiate(**{**values, "amount": "20000"})
    assert exc.value.rule == "idempotency_conflict"
    assert backend.invoices[backend.inv1]["paid"] == Decimal("10000")


def test_refund_rules_invoices_and_isolation(finance, backend):
    payment = finance.initiate(**cash(backend, backend.inv1, "60000"))
    refund = finance.refund(payment.id, amount="20000", reason="Trop perçu")
    assert refund.amount == Decimal("20000.00")
    with pytest.raises(Conflict) as exc:
        finance.refund(payment.id, amount="50000", reason="Encore")
    assert exc.value.rule == "refund_exceeds_payment"
    assert finance.payment(payment.id).status == "PARTIALLY_REFUNDED"  # history kept, never deleted
    rows, _ = finance.refunds()
    assert [(r.payment_reference, r.payment_amount) for r in rows] == [(payment.reference, Decimal("60000.00"))]
    with pytest.raises(Conflict) as exc:
        finance.cancel_invoice(backend.inv1, "Erreur")
    assert exc.value.rule == "invoice_has_payments"
    issued = finance.issue_invoice(
        student_id=backend.sb,
        due_date=date(2026, 4, 1),
        fee_type_id=backend.scol,
        amount="25000",
        description="Cantine",
    )
    assert (issued.total, issued.lines) == (Decimal("25000.00"), (("Cantine", Decimal("25000.00")),))
    assert [i.number for i in finance.obligations(backend.sb)] == ["F25-000003", issued.number]
    for call in (lambda: finance.payment("other-school"), lambda: finance.cancel_invoice("other-school", "x")):
        with pytest.raises(NotFound):
            call()


def test_finance_permissions(finance, backend):
    backend.roles = ["TEACHER"]
    with pytest.raises(Forbidden):
        finance.dashboard()
    with pytest.raises(Forbidden):
        finance.refund("x", amount="1", reason="x")
    assert finance.payments() == ([], 0)  # no financial right: nothing visible


def test_payroll_workflow_service(payroll, backend):
    summary = payroll.calculate(backend.p_oct)
    assert (summary["unchanged"], summary["frozen"]) == (1, 2)
    rows = payroll.payrolls(period_id=backend.p_oct, kind="TEACHER")
    assert {(r.employee_name, r.status) for r in rows} == {("Jean Mbarga", "CALCULATED"), ("Marie Ngo", "APPROVED")}
    detail = payroll.payroll(backend.pr_tm)
    assert detail.reconstructible and [line.kind for line in detail.lines] == ["PROGRAMMED", "EARNED", "ADJUSTMENT"]
    assert detail.payable == Decimal("15000.00")
    backend.stale_payrolls.add(backend.pr_tm)
    with pytest.raises(Conflict) as exc:
        payroll.approve(backend.pr_tm)
    assert exc.value.rule == "payroll_stale"
    assert payroll.calculate(backend.p_oct)["recalculated"] == 1
    assert payroll.approve(backend.pr_tm).status == "APPROVED"
    paid = payroll.pay(backend.pr_tm, method="CASH")
    assert paid.status == "PAID" and paid.payment_reference.startswith("PAYR-")
    with pytest.raises(Conflict) as exc:
        payroll.pay(backend.pr_tm, method="CASH")
    assert exc.value.rule == "payroll_already_paid"
    with pytest.raises(Conflict) as exc:
        payroll.close_period(backend.p_oct)
    assert exc.value.rule == "period_not_settled"  # Marie Ngo is approved, not paid
    with pytest.raises(Forbidden):
        payroll.pay(backend.pr_tf, method="WALLET", wallet_id=backend.w_tm)  # not her wallet
    with pytest.raises(NotFound):
        payroll.payroll("other-school")
    assert [a.amount for a in payroll.adjustments(employee_id=backend.e_tm)] == [Decimal("5000.00")]
    remuneration = payroll.remuneration(backend.e_tm, date(2025, 9, 1), date(2026, 7, 31))
    assert remuneration["programmed_amount"] == Decimal("20000.00")
    assert payroll.validated_sessions(backend.tm) == 2
    backend.roles = ["TEACHER"]
    with pytest.raises(Forbidden):
        payroll.periods()


# =============================================================================
# Screens
# =============================================================================


@pytest.fixture
def controller(qapp, api, auth, backend):
    backend.seed_finance()
    backend.seed_payroll()
    ctrl = AppController(api, auth, ImmediateRunner(), AppConfig(api_url="http://testserver/api/v1/"))
    ctrl.finance.today = lambda: date(2026, 3, 4)
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


def test_finance_overview_and_navigation(controller):
    shell, page = open_module(controller, "finance")
    labels = [shell.nav.item(i).text() for i in range(shell.nav.count())]
    assert "Finance" in labels and "Paie" in labels
    assert [page.tabs.tabText(i) for i in range(page.tabs.count())] == [
        "Vue d'ensemble",
        "Paiements",
        "Factures",
        "Remboursements",
        "Wallets",
        "Motifs",
    ]
    values = {m.label: m.value for m in page.overview.metrics}
    assert values["Trésorerie"] == xaf("100 000") and values["Encaissé net"] == xaf("1 250 000")
    assert column(page.overview.table, 3)[0] == "+ " + xaf("100 000")


def test_new_payment_shows_each_outcome(controller, backend):
    _, finance = open_module(controller, "finance")
    payments = finance.open_tab("payments")
    seen = {}

    def answer(kind, **context):
        seen.update(context)
        return values

    payments.ask = answer
    values = cash(backend, backend.inv1, "60000")
    payments.add()
    assert [w.code for w in seen["wallets"]] == ["FAKE_ORANGE •••• 0001", "FAKE_MTN •••• 0002"]  # own, masked
    assert payments.banner.plain_text() == f"Paiement réussi — PAY-000001 · {xaf('60 000')} · Awa Ndiaye."
    assert payments.selected().reference == "PAY-000001"
    values = {**cash(backend, backend.inv2, "40000"), "method": "WALLET", "wallet_id": backend.w_decline}
    payments.add()
    assert payments.banner.property("kind") == "warning"
    assert payments.banner.plain_text().startswith("Paiement refusé")
    assert "Le paiement est enregistré avec ce résultat." in payments.banner.plain_text()
    backend.wallets[backend.w_admin]["balance"] = Decimal("1000")
    values = {**cash(backend, backend.inv2, "40000"), "method": "WALLET", "wallet_id": backend.w_admin}
    payments.add()
    assert payments.banner.plain_text().startswith("Paiement fonds insuffisants")
    assert column(payments.table, 5)[0] == "Fonds insuffisants" and payments.count_label.text() == "3 paiements"
    payments.status.setCurrentIndex(payments.status.findData("SUCCEEDED"))
    assert column(payments.table, 0) == ["PAY-000001"]
    payments.method_filter.setCurrentIndex(payments.method_filter.findData("WALLET"))
    assert payments.table.rowCount() == 0 and "ne correspond" in payments.empty.text()


def test_unknown_outcome_is_retried_with_the_same_key(controller, backend):
    _, finance = open_module(controller, "finance")
    payments = finance.open_tab("payments")
    values = cash(backend, backend.inv1, "60000")
    received = []
    payments.ask = lambda kind, **context: received.append(context.get("retry")) or values
    payments.send_payment(values)  # direct: the fee types are already loaded
    assert payments.retry is None
    backend.offline = True
    payments.send_payment({**values, "idempotency_key": "intent-2", "invoice_ids": [backend.inv2], "amount": "40000"})
    backend.offline = False
    assert payments.retry["idempotency_key"] == "intent-2"  # outcome unknown: kept for the retry
    payments.add()
    assert received[-1]["idempotency_key"] == "intent-2"


def test_payment_dialog_suggests_and_requires(qapp, finance, backend):
    dialog = PaymentDialog(
        finance.fee_types(),
        finance.my_wallets(),
        lambda text, done: done(finance.find_students(text)),
        lambda sid, done: done(finance.obligations(sid)),
        student=(backend.sa, "Ndiaye Awa"),
        invoice=backend.inv2,
    )
    assert dialog.invoice_ids == [backend.inv2] and dialog.amount.text() == "40000.00"
    assert not dialog.fee_type.isEnabled() and dialog.save_enabled
    dialog.amount.setText("beaucoup")
    assert not dialog.save_enabled and "Montant" in dialog.status.text()
    dialog.amount.setText("100")
    dialog.method.setCurrentIndex(dialog.method.findData("WALLET"))
    assert dialog.wallet.isEnabled() and dialog.values()["wallet_id"] == backend.w_admin
    assert dialog.values()["idempotency_key"] == dialog.key


def test_refund_from_payments_and_refunds_tab(controller, backend):
    _, finance = open_module(controller, "finance")
    payments = finance.open_tab("payments")
    payments.ask = lambda kind, **c: cash(backend, backend.inv1, "60000")
    payments.add()
    assert payments.refund_button.isEnabled()
    payments.ask = lambda kind, **c: {"amount": "100000", "reason": "Erreur"}
    payments.refund_payment(payments.selected())
    assert payments.banner.property("kind") == "warning"
    assert "Le montant dépasse ce qui reste remboursable" in payments.banner.plain_text()
    payments.ask = lambda kind, **c: {"amount": "15000", "reason": "Trop perçu"}
    payments.refund_payment(payments.selected())
    assert payments.banner.plain_text().startswith(f"Remboursement de {xaf('15 000')} enregistré (paiement PAY-000001)")
    refunds = finance.open_tab("refunds")
    assert column(refunds.table, 1) == ["PAY-000001"] and column(refunds.table, 4) == [xaf("60 000")]
    refunds.table.selectRow(0)
    opened = []
    refunds.ask = lambda kind, **c: opened.append(c["payment"].status) or None
    refunds.open_row()
    assert opened == ["PARTIALLY_REFUNDED"]


def test_payment_detail_dialog(qapp, finance, backend):
    ok = finance.initiate(**cash(backend, backend.inv1, "60000"))
    dialog = PaymentDetailDialog(finance.payment(ok.id), can_refund=True)
    text = " ".join(label.text() for label in dialog.content.findChildren(type(dialog.status)))
    assert "Réussi" in text and "F25-000001" in text and xaf("60 000") in text
    assert any(b.text() == "Rembourser…" for b in dialog.content.findChildren(type(dialog.save_button)))
    backend.wallets[backend.w_decline]["simulation_behavior"] = "TIMEOUT"
    failed = finance.initiate(
        **{**cash(backend, backend.inv2, "1000"), "method": "WALLET", "wallet_id": backend.w_decline}
    )
    dialog = PaymentDetailDialog(failed, can_refund=True)
    text = " ".join(label.text() for label in dialog.content.findChildren(type(dialog.status)))
    assert "Délai dépassé" in text and "Motif de l'échec" in text
    assert not any(b.text() == "Rembourser…" for b in dialog.content.findChildren(type(dialog.save_button)))


def test_invoices_tab(controller, backend):
    _, finance = open_module(controller, "finance")
    invoices = finance.open_tab("invoices")
    assert column(invoices.table, 0) == ["F25-000001", "F25-000003", "F25-000002"]
    assert column(invoices.table, 7)[0] == "Émise · en retard"
    invoices.ask = lambda kind, **c: {
        "student_id": backend.sb,
        "fee_type_id": backend.scol,
        "description": "Cantine",
        "amount": "25000",
        "due_date": date(2026, 4, 1),
    }
    invoices.add()
    assert invoices.banner.plain_text() == f"Facture F25-000004 émise : {xaf('25 000')} pour Paul Kamga."
    invoices.search.setText("F25-000001")
    invoices.reload_first_page()
    invoices.table.selectRow(0)
    collected = []
    invoices.ask = lambda kind, **c: (
        collected.append((c.get("student"), c.get("invoice"))) or cash(backend, backend.inv1, "60000")
    )
    invoices.collect_selected()
    assert collected[0] == ((backend.sa, "Awa Ndiaye"), backend.inv1)
    assert column(invoices.table, 7) == ["Payée"]
    invoices.table.selectRow(0)
    assert not invoices.cancel_button.isEnabled()  # paid: refunded, never cancelled
    invoices.ask = lambda kind, **c: {"reason": "Erreur"}
    invoices.rows[0] = replace(invoices.rows[0], status="ISSUED")  # a stale screen: the server refuses
    invoices.cancel_invoice()
    assert "remboursez-les avant de l'annuler" in invoices.banner.plain_text()


def test_wallets_and_fee_types_tabs(controller, backend):
    _, finance = open_module(controller, "finance")
    wallets = finance.open_tab("wallets")
    assert "699999999" not in " ".join(column(wallets.table, 2)) and "•••• 9999" in column(wallets.table, 2)
    assert not wallets.add_button.isVisible() and not wallets.edit_button.isVisible()
    fees = finance.open_tab("fee_types")
    fees.ask = lambda: {"code": "SCOL", "name": "Doublon", "description": ""}
    fees.add()
    assert "Ce code est déjà utilisé" in fees.banner.plain_text()
    fees.ask = lambda: {"code": "CANT", "name": "Cantine", "description": ""}
    fees.add()
    assert column(fees.table, 0) == ["CANT", "SCOL"]


def test_finance_forbidden_is_shown(controller, backend):
    _, finance = open_module(controller, "finance")
    backend.roles = ["TEACHER"]
    finance.overview.reload()
    assert finance.overview.banner.property("kind") == "error"
    assert "Permission refusée" in finance.overview.banner.plain_text()


def test_payroll_screens_workflow(controller, backend):
    shell, page = open_module(controller, "payroll")
    assert page.workflow.text() == "Période → Calculer → Préparer → Vérifier → Approuver → Payer"
    periods = page.periods
    assert column(periods.table, 0) == ["Octobre 2025"]
    periods.table.selectRow(0)
    periods.calculate()
    assert periods.banner.plain_text().startswith("Calcul terminé : 0 créée(s), 0 recalculée(s), 1 inchangée(s)")
    payrolls = page.payrolls
    assert page.tabs.currentWidget() is payrolls and payrolls.period_filter.currentData() == backend.p_oct
    assert sorted(column(payrolls.table, 0)) == ["Jean Mbarga", "Luc Staff", "Marie Ngo"]
    payrolls.select_id(backend.pr_tm)
    assert payrolls.approve_button.isEnabled() and not payrolls.pay_button.isEnabled()
    backend.stale_payrolls.add(backend.pr_tm)
    payrolls.ask = lambda kind, **c: True
    payrolls.run_action("approve")
    assert "recalculez la période avant d'approuver" in payrolls.banner.plain_text()
    backend.stale_payrolls.clear()
    payrolls.run_action("approve")
    assert payrolls.banner.plain_text() == f"Jean Mbarga · Octobre 2025 — Paie approuvée : {xaf('15 000')}."
    offered = {}

    def pay(kind, **context):
        offered["wallets"] = [w.owner_name for w in context["wallets"]]
        return {"method": "WALLET", "wallet_id": context["wallets"][0].id}

    payrolls.ask = pay
    payrolls.run_action("pay")
    assert offered["wallets"] == ["Jean Mbarga"]  # only the employee's own wallet is proposed
    assert payrolls.banner.plain_text().startswith(f"Jean Mbarga · Octobre 2025 — Paie payée : {xaf('15 000')}")
    assert payrolls.selected().status == "PAID" and not payrolls.pay_button.isEnabled()
    assert backend.wallets[backend.w_tm]["balance"] == Decimal("15000")
    payrolls.status.setCurrentIndex(payrolls.status.findData("APPROVED"))
    assert column(payrolls.table, 0) == ["Marie Ngo"]
    payrolls.table.selectRow(0)
    payrolls.ask = lambda kind, **c: {"reason": "Erreur de période"}
    payrolls.run_action("cancel")
    assert payrolls.banner.plain_text().endswith("Paie annulée (historique conservé).")
    page.open_tab("periods")
    periods.table.selectRow(0)
    periods.ask = lambda kind, **c: True
    periods.close_period()
    assert periods.banner.plain_text() == "Période « Octobre 2025 » clôturée."


def test_payroll_detail_dialog_and_pay_dialog(qapp, payroll, backend):
    detail = payroll.payroll(backend.pr_tm)
    dialog = PayrollDetailDialog(detail)
    text = " ".join(label.text() for label in dialog.content.findChildren(type(dialog.status)))
    assert "Rémunération programmée" in text and "Rémunération acquise" in text and xaf("15 000") in text
    assert set(dialog.buttons) == {"approve", "cancel"}
    dialog.buttons["approve"].click()
    assert dialog.action == "approve"
    pay_dialog = PayDialog(payroll.payroll(backend.pr_tf), [])
    assert pay_dialog.values() == {"method": "CASH", "wallet_id": None}
    wallet_item = pay_dialog.method.model().item(pay_dialog.method.findData("WALLET"))
    assert not wallet_item.isEnabled()  # no wallet in her name


def test_adjustments_tab(controller, backend):
    _, page = open_module(controller, "payroll")
    adjustments = page.open_tab("adjustments")
    assert column(adjustments.table, 0) == ["Mbarga Jean (ENS-001)"] and column(adjustments.table, 4) == ["En attente"]
    asked = {}

    def answer(employees):
        asked["employees"] = dict(employees)
        return {"employee_id": backend.e_tf, "amount": "-2000", "reason": "Avance", "effective_date": date(2026, 3, 1)}

    adjustments.ask = answer
    adjustments.add()
    assert asked["employees"][backend.e_tf] == "Ngo Marie (ENS-002)" and asked["employees"]["emp-staff"] == "Luc Staff"
    assert adjustments.banner.plain_text() == f"Correction de {format_money('-2000')} enregistrée."


def test_teacher_record_gives_read_only_remuneration(controller, backend):
    _, teachers = open_module(controller, "teachers")
    seen = {}

    def ask(kind, **context):
        seen[kind] = context
        return "remuneration" if kind == "record" else None

    teachers.ask = ask
    teachers.select_id(backend.tm)
    teachers.open_record()
    context = seen["remuneration"]
    assert context["summary"]["programmed_amount"] == Decimal("20000.00")
    assert [p.period_name for p in context["payrolls"]] == ["Octobre 2025"] and context["validated"] == 2
    assert (context["date_from"], context["date_to"]) == (date(2025, 9, 1), date(2026, 7, 31))
    from school_admin.ui.dialogs.teacher_dialogs import TeacherRecordDialog

    record = TeacherRecordDialog(context["teacher"], [], [], with_remuneration=True)
    assert record.remuneration_button is not None  # read-only access, no payroll action there


def test_dashboard_finance_figures(controller, backend):
    shell, _ = open_module(controller, "dashboard")
    dashboard = shell.pages["dashboard"]
    values = {m.label: (m.value, m.hint) for m in dashboard.data.metrics}
    assert values["Paies versées"] == (xaf("150 000"), "1 paie payée(s) · 1 approuvée(s) à payer")
    payrolls = dashboard.charts.payrolls
    assert [(p.label, p.values) for p in payrolls.points] == [("Préparée", (1,)), ("Approuvée", (1,)), ("Payée", (1,))]
    assert dashboard.charts.payments.empty_text == "Aucun paiement." and dashboard.charts.payments.points == []


@pytest.mark.parametrize("size", [QSize(1366, 768), QSize(1280, 720), QSize(1024, 768)])
def test_finance_and_payroll_toolbars_fit(controller, size):
    shell, finance = open_module(controller, "finance")
    shell.resize(size)
    shell.show()
    QTest.qWaitForWindowExposed(shell)
    for tab in ("payments", "invoices", "refunds", "wallets", "fee_types"):
        page = finance.open_tab(tab)
        QTest.qWait(5)
        _fits(page, tab)
    invoices = finance.invoices
    assert invoices.table.isColumnHidden(2) == (invoices.width() < invoices.narrow_width)  # secondary column
    payroll = shell.open("payroll")
    for tab in ("periods", "payrolls", "adjustments"):
        page = payroll.open_tab(tab)
        QTest.qWait(5)
        _fits(page, tab)
    shell.close()


def _fits(page, name):
    buttons = [b for b in page.findChildren(type(page.refresh_button)) if b.isVisible() and b.parent() is page]
    row = sorted(
        (b for b in buttons if abs(b.geometry().top() - page.refresh_button.geometry().top()) < 4), key=lambda b: b.x()
    )
    for left, right in zip(row, row[1:], strict=False):
        assert left.geometry().right() < right.geometry().left(), name
    for widget in [*row, page.search, page.table]:
        assert page.rect().contains(widget.geometry()), (name, widget)
    header = page.table.horizontalHeader()
    assert header.sectionResizeMode(0) in (header.ResizeMode.Stretch, header.ResizeMode.ResizeToContents)
    assert page.table.horizontalScrollBarPolicy() != Qt.ScrollBarAlwaysOn

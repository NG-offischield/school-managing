"""Finance test world: gradebook world (year 2025-2026, class 3e A, students
s0..s2) + fee type TUITION, two invoices for s0 (60 000 then 40 000), a
verified parent of s0 with can_pay / can_view_financial_data and a funded
simulated wallet (150 000 XAF)."""

from datetime import date
from decimal import Decimal

from apps.finance import services as fin
from apps.people import services as people
from apps.people.models import VerificationMethod

from .factories import ParentFactory
from .gradebook_world import make_world


def verified_parent(w, student, *, can_pay=True, can_view=True):
    parent = ParentFactory(school=w.school)
    link = people.link_parent(parent, student, relationship_type="MOTHER")
    people.verify_parent_link(link, actor=w.admin, method=VerificationMethod.ADMIN_IN_PERSON)
    link.can_pay, link.can_view_financial_data = can_pay, can_view
    link.save()
    return parent.membership


def wallet_for(w, owner, *, balance="150000", behavior="NORMAL", identifier=None):
    wallet = fin.create_wallet(
        owner,
        actor=w.admin,
        provider_code="FAKE_ORANGE",
        wallet_identifier=identifier or f"6{owner.pk.int % 10**8:08d}",
        simulation_behavior=behavior,
    )
    if Decimal(balance) > 0:
        fin.fund_wallet(wallet, balance, actor=w.admin)
    wallet.refresh_from_db()
    return wallet


def make_finance_world(school):
    w = make_world(school)
    w.tuition = fin.create_fee_type(school, actor=w.admin, code="tuition", name="Scolarité")
    s0 = w.students[0]
    w.inv1 = fin.issue_invoice(
        s0, actor=w.admin, due_date=date(2025, 10, 15), lines=[{"fee_type": w.tuition, "unit_price": "60000"}]
    )
    w.inv2 = fin.issue_invoice(
        s0, actor=w.admin, due_date=date(2026, 1, 15), lines=[{"fee_type": w.tuition, "unit_price": "40000"}]
    )
    w.parent = verified_parent(w, s0)
    w.wallet = wallet_for(w, w.parent)
    return w

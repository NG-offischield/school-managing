"""The demonstration dataset — the ONE place where it is defined (docs/demo-data.md).

Plain data, no logic: `seed.py` turns it into real objects through the domain
services (no SQL, no fixture JSON). Every entry has a stable natural key
(school code, e-mail, student number, wallet identifier, fee type code,
idempotency key) so that a second run finds what exists instead of
duplicating it.

No secret here: the demo accounts' password is injected at run time
(DEMO_PASSWORD), never written in the repository.
"""

from decimal import Decimal

SCHOOL = {
    "code": "DEMO",
    "name": "Collège de Démonstration Les Manguiers",
    "city": "Douala",
    "address": "Rue des Manguiers, Bonapriso",
}

ADMIN = {
    "username": "demo.admin",
    "email": "admin@demo-ecole.test",
    "first_name": "Clarisse",
    "last_name": "Ngo Bassa",
}

# Gate guardian (people.admin_create_guardian, then the real activation flow).
GUARDIAN = {
    "username": "demo.guardian",
    "email": "guardian@demo-ecole.test",
    "first_name": "Emmanuel",
    "last_name": "Essomba",
    "guardian_number": "G-DEMO-01",
}

# Levels and classes of the current school year (created if missing).
LEVELS = [
    {"code": "6E", "name": "Sixième", "order_index": 1},
    {"code": "3E", "name": "Troisième", "order_index": 4},
]
CLASSES = [
    {"name": "6e A", "level": "6E"},
    {"name": "3e B", "level": "3E"},
]

# Exactly the fields of people.Student accepted by admin_create_student
# (student_number, registration_number, first_name, last_name, date_of_birth,
# sex M/F, birth_place, address) + the class of the current year.
STUDENTS = [
    {
        "key": "S1",
        "student_number": "DEMO-2026-001",
        "registration_number": "INS-DEMO-001",
        "first_name": "Léa",
        "last_name": "Mbarga",
        "date_of_birth": "2014-03-12",
        "sex": "F",
        "birth_place": "Douala",
        "class": "6e A",
    },
    {
        "key": "S2",
        "student_number": "DEMO-2026-002",
        "registration_number": "INS-DEMO-002",
        "first_name": "Junior",
        "last_name": "Ekotto",
        "date_of_birth": "2014-07-03",
        "sex": "M",
        "birth_place": "Yaoundé",
        "class": "6e A",
    },
    {
        "key": "S3",
        "student_number": "DEMO-2026-003",
        "registration_number": "INS-DEMO-003",
        "first_name": "Aïcha",
        "last_name": "Bello",
        "date_of_birth": "2013-11-21",
        "sex": "F",
        "birth_place": "Garoua",
        "class": "6e A",
    },
    {
        "key": "S4",
        "student_number": "DEMO-2026-004",
        "registration_number": "INS-DEMO-004",
        "first_name": "Paul",
        "last_name": "Nkoulou",
        "date_of_birth": "2011-01-30",
        "sex": "M",
        "birth_place": "Douala",
        "class": "3e B",
    },
    {
        "key": "S5",
        "student_number": "DEMO-2026-005",
        "registration_number": "INS-DEMO-005",
        "first_name": "Inès",
        "last_name": "Nkoulou",
        "date_of_birth": "2014-09-08",
        "sex": "F",
        "birth_place": "Douala",
        "class": "6e A",
    },
]

# Parents go through the REAL workflow (ADR 0026): registration -> approval ->
# link request with an ID document -> identity check -> pupil's designation ->
# approval with the rights below. `document` is fictitious (only its HMAC is stored).
PARENTS = [
    {
        "key": "A",
        "email": "parent.a@demo-ecole.test",
        "first_name": "Awa",
        "last_name": "Mbarga",
        "phone": "+237600000001",
        "document": "CM DEMO-0001",
        "children": [{"student": "S1", "relationship": "MOTHER"}],
    },
    {
        "key": "B",
        "email": "parent.b@demo-ecole.test",
        "first_name": "Samuel",
        "last_name": "Ekotto",
        "phone": "+237600000002",
        "document": "CM DEMO-0002",
        "children": [{"student": "S2", "relationship": "FATHER"}],
    },
    {
        "key": "C",
        "email": "parent.c@demo-ecole.test",
        "first_name": "Mariam",
        "last_name": "Bello",
        "phone": "+237600000003",
        "document": "CM DEMO-0003",
        "children": [{"student": "S3", "relationship": "MOTHER"}],
    },
    {
        "key": "D",
        "email": "parent.d@demo-ecole.test",
        "first_name": "Roger",
        "last_name": "Nkoulou",
        "phone": "+237600000004",
        "document": "CM DEMO-0004",
        "children": [
            {"student": "S4", "relationship": "FATHER"},
            {"student": "S5", "relationship": "FATHER"},
        ],
    },
]
# Every demo link grants: see the finances, pay, notifications, complaints.
LINK_RIGHTS = {
    "can_pay": True,
    "can_view_financial_data": True,
    "can_receive_notifications": True,
    "can_submit_complaints": True,
}

FEE_TYPES = [
    {"code": "TUITION", "name": "Frais de scolarité"},
    {"code": "CANTEEN", "name": "Cantine"},
    {"code": "TRANSPORT", "name": "Transport scolaire"},
    {"code": "EXAM", "name": "Frais d'examen"},
]

# One invoice per (student, fee type). `due_in_days` is relative to the run
# date (negative = already due). The CASH payments below are recorded at the
# desk by the administration (payer = the parent), as Finance allows.
INVOICES = [
    {"key": "F-S1-TUITION", "student": "S1", "fee_type": "TUITION", "amount": "75000", "due_in_days": 20},
    {"key": "F-S2-TUITION", "student": "S2", "fee_type": "TUITION", "amount": "75000", "due_in_days": 20},
    {"key": "F-S3-CANTEEN", "student": "S3", "fee_type": "CANTEEN", "amount": "25000", "due_in_days": 15},
    {"key": "F-S4-EXAM", "student": "S4", "fee_type": "EXAM", "amount": "15000", "due_in_days": -10},
    {"key": "F-S4-TRANSPORT", "student": "S4", "fee_type": "TRANSPORT", "amount": "30000", "due_in_days": -5},
    {"key": "F-S5-TUITION", "student": "S5", "fee_type": "TUITION", "amount": "75000", "due_in_days": 45},
]

# Payments made during the seed (stable idempotency keys: replayed, never
# repeated, on a second run).
CASH_PAYMENTS = [
    # S4's exam fees: fully paid at the desk -> invoice PAID, receipt available.
    {"key": "demo-seed-cash-exam-s4", "invoice": "F-S4-EXAM", "payer": "D", "amount": "15000"},
    # S4's transport: 10 000 of 30 000 -> invoice PARTIALLY_PAID.
    {"key": "demo-seed-cash-transport-s4", "invoice": "F-S4-TRANSPORT", "payer": "D", "amount": "10000"},
]

# Simulated wallets (Finance's own Wallet model, opened by the administration).
# `balance` is the demo target: set at creation, restored by --refill-wallets.
WALLETS = [
    {"owner": "A", "provider": "FAKE_ORANGE", "identifier": "690000101", "balance": Decimal("100000")},
    {"owner": "B", "provider": "FAKE_MTN", "identifier": "670000202", "balance": Decimal("1000")},
    # Exactly the amount of S3's canteen invoice.
    {"owner": "C", "provider": "FAKE_ORANGE", "identifier": "690000303", "balance": Decimal("25000")},
    {"owner": "D", "provider": "FAKE_MTN", "identifier": "670000404", "balance": Decimal("500000")},
]

# The school's simulated treasury (Finance's SimulationTreasury, one per school):
# initial working capital, credited once; payments then add to it.
TREASURY_FUNDING = Decimal("2000000")

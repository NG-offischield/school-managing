"""Finance integrity (ADR 0013).

- Composite keys: every row inside one school; the wallet of a payment
  belongs to its payer; an allocation's invoice and payment concern the same
  student; a refund allocation belongs to its refund's payment.
- Append-only ledgers: wallet / treasury transactions, allocations, refunds.
- Payments: never deleted; once out of PENDING, only the refund progression
  may change (refunded_amount upwards, SUCCEEDED -> PARTIALLY_REFUNDED ->
  REFUNDED).
"""

from django.db import migrations

from common.migration_operations import EnforceSameValue

APPEND_ONLY_FN = """
CREATE OR REPLACE FUNCTION finance_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'finance_history_immutable: % rows cannot be modified or deleted', TG_TABLE_NAME
        USING ERRCODE = 'check_violation';
END;
$$ LANGUAGE plpgsql;
"""

APPEND_ONLY_TABLES = [
    "finance_wallettransaction",
    "finance_treasurytransaction",
    "finance_paymentallocation",
    "finance_paymentrefund",
]

PAYMENT_GUARD = """
CREATE OR REPLACE FUNCTION finance_payment_guard() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'payment_immutable: payments are never deleted' USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status = 'PENDING' THEN
        RETURN NEW;  -- completion of a pending payment
    END IF;
    IF (NEW.id, NEW.school_id, NEW.created_at, NEW.payment_reference, NEW.idempotency_key, NEW.request_fingerprint,
        NEW.student_id, NEW.payer_id, NEW.initiated_by_id, NEW.fee_type_id, NEW.wallet_id, NEW.amount, NEW.currency,
        NEW.payment_method, NEW.provider, NEW.initiated_at, NEW.completed_at, NEW.failure_reason,
        NEW.provider_reference)
       IS DISTINCT FROM
       (OLD.id, OLD.school_id, OLD.created_at, OLD.payment_reference, OLD.idempotency_key, OLD.request_fingerprint,
        OLD.student_id, OLD.payer_id, OLD.initiated_by_id, OLD.fee_type_id, OLD.wallet_id, OLD.amount, OLD.currency,
        OLD.payment_method, OLD.provider, OLD.initiated_at, OLD.completed_at, OLD.failure_reason,
        OLD.provider_reference)
       OR NEW.refunded_amount < OLD.refunded_amount
       OR (NEW.status IS DISTINCT FROM OLD.status AND NOT (
            OLD.status IN ('SUCCEEDED', 'PARTIALLY_REFUNDED')
            AND NEW.status IN ('PARTIALLY_REFUNDED', 'REFUNDED')))
       OR (NEW.refunded_amount <> OLD.refunded_amount AND OLD.status NOT IN ('SUCCEEDED', 'PARTIALLY_REFUNDED')) THEN
        RAISE EXCEPTION 'payment_immutable: a completed payment can only progress through refunds'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER finance_payment_guard
    BEFORE UPDATE OR DELETE ON finance_payment
    FOR EACH ROW EXECUTE FUNCTION finance_payment_guard();
"""


def _append_only_sql():
    sql = APPEND_ONLY_FN
    for table in APPEND_ONLY_TABLES:
        sql += (
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION finance_append_only();\n"
        )
    return sql


def _append_only_reverse():
    sql = "".join(f"DROP TRIGGER IF EXISTS {t}_append_only ON {t};\n" for t in APPEND_ONLY_TABLES)
    return sql + "DROP FUNCTION IF EXISTS finance_append_only();"


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0001_initial"),
        ("people", "0002_same_school_constraints"),
        ("academics", "0007_room_same_school"),
    ]

    operations = [
        *[EnforceSameValue("feeschedule", f) for f in ("fee_type", "academic_year", "level", "school_class")],
        EnforceSameValue("feeschedule", "school_class", shared_field="academic_year"),
        *[EnforceSameValue("invoice", f) for f in ("student", "payer", "academic_year", "issued_by")],
        *[EnforceSameValue("invoiceline", f) for f in ("invoice", "fee_type", "fee_schedule")],
        EnforceSameValue("wallet", "owner"),
        EnforceSameValue("wallettransaction", "wallet"),
        EnforceSameValue("wallettransaction", "created_by"),
        EnforceSameValue("treasurytransaction", "treasury"),
        EnforceSameValue("treasurytransaction", "created_by"),
        *[EnforceSameValue("payment", f) for f in ("student", "payer", "initiated_by", "fee_type", "wallet")],
        # The wallet used belongs to the payer.
        EnforceSameValue("payment", "wallet", shared_field="payer", target_field="owner"),
        *[EnforceSameValue("paymentallocation", f) for f in ("payment", "invoice", "student", "refund")],
        EnforceSameValue("paymentallocation", "payment", shared_field="student"),
        EnforceSameValue("paymentallocation", "invoice", shared_field="student"),
        EnforceSameValue("paymentallocation", "refund", shared_field="payment"),
        EnforceSameValue("paymentrefund", "payment"),
        EnforceSameValue("paymentrefund", "created_by"),
        migrations.RunSQL(_append_only_sql(), reverse_sql=_append_only_reverse()),
        migrations.RunSQL(
            PAYMENT_GUARD,
            reverse_sql="DROP TRIGGER IF EXISTS finance_payment_guard ON finance_payment; "
            "DROP FUNCTION IF EXISTS finance_payment_guard();",
        ),
    ]

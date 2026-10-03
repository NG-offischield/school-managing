"""Writing the audit trail."""

from .models import AuditLayer, AuditLog


def snapshot(instance, fields):
    """Plain dict of `fields` of `instance` (FKs as ids) for old/new data."""
    data = {}
    for name in fields:
        field = instance._meta.get_field(name)
        data[name] = getattr(instance, field.attname)
    return data


def record_audit(action, *, actor, entity, old=None, new=None, layer=AuditLayer.BUSINESS, school=None, ctx=None):
    """Append an audit row in the CURRENT transaction (rolled back with the
    change it describes). `ctx` is an accounts.services.ClientContext."""
    return AuditLog.objects.create(
        school=school or getattr(entity, "school", None),
        layer=layer,
        actor=actor,
        action=action,
        entity_type=entity._meta.label,
        entity_id=entity.pk,
        old_data=old or {},
        new_data=new or {},
        ip_address=getattr(ctx, "ip_address", None),
        user_agent=getattr(ctx, "user_agent", None),
    )

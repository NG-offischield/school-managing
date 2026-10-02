"""Database routing for the security log (ADR 0005).

`security_log` is not a second database: it is a second *connection* to the
same PostgreSQL database. Sending SecurityEvent reads/writes through it puts
them outside the business transaction of the request.
"""

SECURITY_LOG_ALIAS = "security_log"
SECURITY_LOG_MODELS = {"accounts.securityevent"}


class SecurityLogRouter:
    def _is_security_log(self, model):
        return model._meta.label_lower in SECURITY_LOG_MODELS

    def db_for_read(self, model, **hints):
        return SECURITY_LOG_ALIAS if self._is_security_log(model) else None

    def db_for_write(self, model, **hints):
        return SECURITY_LOG_ALIAS if self._is_security_log(model) else None

    def allow_relation(self, obj1, obj2, **hints):
        # Both aliases target the same physical database, so a SecurityEvent
        # may reference a User/School loaded through the default connection.
        if self._is_security_log(obj1) or self._is_security_log(obj2):
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # Schema is created once, through `default`. Migrating via the alias
        # would apply the same migrations twice to the same database.
        if db == SECURITY_LOG_ALIAS:
            return False
        return None

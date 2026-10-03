"""Custom migration operation: database-enforced "same tenant" relations (ADR 0008).

The problem
-----------
A StudentEnrollment points to a Student and to a SchoolClass, and also stores
its own `school_id`. Ordinary foreign keys only guarantee that the student and
the class *exist*; nothing stops a buggy script from enrolling a student of
school A into a class of school B. Checking it in Python only works as long as
every code path goes through the right service.

The solution: composite foreign keys
------------------------------------
PostgreSQL can enforce it itself:

    FOREIGN KEY (student_id, school_id) REFERENCES people_student (id, school_id)

The row is accepted only if the referenced student exists AND belongs to the
same school. The same technique works for any shared column, e.g.
`academic_year_id` (a class used by an enrollment must belong to the
enrollment's year).

PostgreSQL requires the referenced columns to be covered by a UNIQUE
constraint, hence the extra `UNIQUE (id, school_id)` added on the target
table. It is logically redundant (id is already unique) but it is what makes
the composite reference possible.

Notes
-----
- Django 5.2 has no composite foreign keys, so this operation emits SQL. It
  changes no Django model state: the ordinary ForeignKey stays the Django-side
  relation; this constraint is an additional database guarantee.
- MATCH SIMPLE (PostgreSQL default): if the FK column is NULL the constraint
  is not checked, which is exactly right for optional relations.
- DEFERRABLE INITIALLY DEFERRED, like Django's own foreign keys, so rows can be
  inserted in any order inside a transaction.
"""

from django.db.backends.utils import truncate_name
from django.db.migrations.operations.base import Operation


class EnforceSameValue(Operation):
    """Composite FK `(field, shared) -> target(id, shared)`.

    Usage in a migration:
        EnforceSameValue("studentenrollment", "student")                 # same school
        EnforceSameValue("studentenrollment", "school_class", "academic_year")
    """

    reversible = True
    reduces_to_sql = True

    def __init__(self, model_name, field_name, shared_field="school", on_update=None, target_field=None):
        """`on_update="CASCADE"` copies changes of the shared column of the
        target into the referencing rows (used to keep Grade.max_score equal
        to its Assessment.max_score).

        `target_field`: name of the shared column on the TARGET when it differs
        (e.g. TeachingSession.planned_teacher must equal Course.teacher)."""
        if on_update not in (None, "CASCADE"):
            raise ValueError("on_update must be None or 'CASCADE'")
        self.model_name = model_name
        self.field_name = field_name
        self.shared_field = shared_field
        self.on_update = on_update
        self.target_field = target_field

    def deconstruct(self):
        kwargs = {"shared_field": self.shared_field}
        if self.on_update:
            kwargs["on_update"] = self.on_update
        if self.target_field:
            kwargs["target_field"] = self.target_field
        return (self.__class__.__qualname__, [self.model_name, self.field_name], kwargs)

    def state_forwards(self, app_label, state):
        # Database-only guarantee: Django's model state is unchanged.
        pass

    def _names(self, app_label, schema_editor, state):
        model = state.apps.get_model(app_label, self.model_name)
        field = model._meta.get_field(self.field_name)
        target = field.related_model
        shared = model._meta.get_field(self.shared_field).column
        target_shared = target._meta.get_field(self.target_field or self.shared_field).column
        max_len = schema_editor.connection.ops.max_name_length()
        table, target_table = model._meta.db_table, target._meta.db_table
        return {
            "model": model,
            "table": table,
            "column": field.column,
            "shared": shared,
            "target_table": target_table,
            "target_shared": target_shared,
            "unique_name": truncate_name(f"{target_table}_id_{target_shared}_uniq", max_len),
            "fk_name": truncate_name(f"{table}_{field.column}_same_{shared}", max_len),
        }

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        n = self._names(app_label, schema_editor, to_state)
        if not self.allow_migrate_model(schema_editor.connection.alias, n["model"]):
            return
        q = schema_editor.quote_name
        # The UNIQUE(id, shared) on the target may already exist (several
        # tables can reference the same target): create it only once.
        # Identifiers come from model metadata (never user input) and are
        # quoted with quote_name(): no injection vector despite the f-string.
        schema_editor.execute(
            f"""
            DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{n["unique_name"]}') THEN
                ALTER TABLE {q(n["target_table"])}
                  ADD CONSTRAINT {q(n["unique_name"])} UNIQUE ("id", {q(n["target_shared"])});
              END IF;
            END $$;
            """
        )
        schema_editor.execute(
            f"ALTER TABLE {q(n['table'])} ADD CONSTRAINT {q(n['fk_name'])} "
            f"FOREIGN KEY ({q(n['column'])}, {q(n['shared'])}) "
            f'REFERENCES {q(n["target_table"])} ("id", {q(n["target_shared"])}) '
            # Referential actions (CASCADE) run immediately even on a
            # deferrable constraint; only the existence check is deferred.
            + ("ON UPDATE CASCADE " if self.on_update == "CASCADE" else "")
            + "DEFERRABLE INITIALLY DEFERRED"
        )

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        n = self._names(app_label, schema_editor, from_state)
        if not self.allow_migrate_model(schema_editor.connection.alias, n["model"]):
            return
        q = schema_editor.quote_name
        # The target's UNIQUE(id, shared) is left in place: other composite
        # keys may still rely on it, and it is harmless on its own.
        schema_editor.execute(f"ALTER TABLE {q(n['table'])} DROP CONSTRAINT IF EXISTS {q(n['fk_name'])}")

    def describe(self):
        return f"Enforce {self.model_name}.{self.field_name} shares the same {self.shared_field}"

    @property
    def migration_name_fragment(self):
        return f"{self.model_name}_{self.field_name}_same_{self.shared_field}"

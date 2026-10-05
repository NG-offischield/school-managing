"""Same-school guarantees of the parent workflow (ADR 0008 / 0026): every
relation between two school-owned rows is doubled by a composite foreign key,
so PostgreSQL itself refuses a request, an identity check or a link that
would mix two schools."""

from django.db import migrations

from common.migration_operations import EnforceSameValue


class Migration(migrations.Migration):
    dependencies = [
        ("people", "0003_parent_workflow"),
        ("accounts", "0005_parent_workflow"),
    ]

    operations = [
        EnforceSameValue("registrationrequest", "membership"),
        EnforceSameValue("identityverification", "membership"),
        EnforceSameValue("parentstudentlinkrequest", "parent"),
        EnforceSameValue("parentstudentlinkrequest", "student"),
        EnforceSameValue("parentstudentlinkrequest", "identity_verification"),
        EnforceSameValue("parentstudentlinkrequest", "sponsor_parent"),
        EnforceSameValue("parentstudentlinkrequest", "link"),
    ]

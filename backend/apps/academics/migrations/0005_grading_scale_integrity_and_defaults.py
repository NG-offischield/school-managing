"""Grading scales: same-school guarantee and default scales for existing schools."""

from django.db import migrations

from common.migration_operations import EnforceSameValue

DEFAULT_SCALES = [
    ("SUR20", "/20", 20, 10, True),
    ("SUR100", "/100", 100, 50, False),
    ("SUR60", "/60", 60, 30, False),
]


def seed_scales(apps, schema_editor):
    """Schools created before this migration get the default scales, so that
    every school has a reference (is_default) scale for report cards."""
    School = apps.get_model("core", "School")
    GradingScale = apps.get_model("academics", "GradingScale")
    for school in School.objects.all():
        for code, label, max_score, pass_score, is_default in DEFAULT_SCALES:
            GradingScale.objects.get_or_create(
                school=school,
                code=code,
                defaults={"label": label, "max_score": max_score, "pass_score": pass_score, "is_default": is_default},
            )


class Migration(migrations.Migration):
    dependencies = [("academics", "0004_grading_scales")]

    operations = [
        EnforceSameValue("subject", "default_grading_scale"),
        migrations.RunPython(seed_scales, migrations.RunPython.noop),
    ]

"""The fictitious school life of the ISBREE demonstration (apps/website/isbree_world.py):
coherent (classes, timetable, marks, attendance, fees all fit together),
reproducible, idempotent, and able to bring the first demo seed's rows
("(démo)" titles, "… Démo" names) up to date without touching edited content."""

from collections import Counter
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.utils import timezone

from apps.academics.models import Level, SchoolClass
from apps.accounts.models import SchoolMembership
from apps.attendance.models import StudentDailyAttendance
from apps.communication.attachments import private_storage
from apps.finance.models import Invoice, InvoiceStatus
from apps.gradebook.models import Assessment, Grade
from apps.people.models import ParentStudent, Student
from apps.scheduling.models import ScheduleSlot, TeachingSession
from apps.website import isbree_world as world
from apps.website.isbree_seed import PROVISIONAL, demo_missing, seed
from apps.website.models import ContentImage, NewsArticle, Page, RoleResource, SiteLocation

from .conftest import DB
from .isbree_world import jpeg

pytestmark = DB
PASSWORD = "Demo-Isbree-2026-Solide"


def test_timetable_is_conflict_free_and_complete():
    plan = world.timetable()
    hours = {code: hours for code, _, _, hours, _ in world.SUBJECTS}
    for (klass, code), slots in plan.items():
        assert len(slots) == hours[code], (klass, code)
        assert max(Counter(day for day, _ in slots).values()) <= 2  # at most two hours a day
    for klass, *_ in world.CLASSES:
        taken = [slot for (k, _), slots in plan.items() if k == klass for slot in slots]
        assert len(taken) == len(set(taken)) == 21  # one subject per hour, 21 hours a week
        assert not any(day == 3 and hour >= 4 for day, hour in taken)  # Wednesday afternoon free
    for code in hours:  # one teacher per subject: never two classes at once
        taken = [slot for (_, c), slots in plan.items() if c == code for slot in slots]
        assert len(taken) == len(set(taken)), code


def test_a_coherent_school_life():
    w = seed(password=PASSWORD, demo=True)
    school = w.school
    year = SchoolClass.objects.get(school=school, name="6e A").academic_year
    today = timezone.localdate()

    assert list(Level.objects.filter(school=school).order_by("order_index").values_list("name", flat=True)) == [
        "Sixième",
        "Cinquième",
        "Quatrième",
        "Troisième",
    ]
    for name, *_ in world.CLASSES:
        klass = SchoolClass.objects.get(school=school, academic_year=year, name=name)
        assert klass.main_room is not None
        assert klass.enrollments.filter(status="ACTIVE").count() == 6
        assert ScheduleSlot.objects.filter(school_class=klass).count() == 21
    assert Student.objects.filter(school=school).count() == 24
    assert TeachingSession.objects.filter(school=school).exists()

    # The demo parent follows two children, both VERIFIED.
    links = ParentStudent.objects.filter(
        parent__membership__user__email="parent.demo@isbree.test", identity_verified=True, active=True
    )
    assert sorted(link.student.first_name for link in links) == ["Léa", "Noah"]

    # Marks: only for assessments already held, every pupil of the class marked, out of 20.
    assessments = Assessment.objects.filter(school=school)
    assert all(a.assessment_date < today for a in assessments)
    for assessment in assessments[:20]:
        marks = Grade.objects.filter(assessment=assessment)
        assert marks.count() == assessment.course.school_class.enrollments.filter(status="ACTIVE").count()
        assert all(Decimal("0") <= m.score <= Decimal("20") for m in marks)

    # Attendance: past school days only, every pupil has a record, mostly present.
    records = StudentDailyAttendance.objects.filter(school=school)
    assert all(r.date < today and r.date.isoweekday() <= 5 for r in records)
    for day in {r.date for r in records}:
        assert records.filter(date=day).count() == 24
    if records.exists():
        assert records.filter(status__in=["PRESENT", "LATE"]).count() > records.count() * 0.8

    # Fees: three invoices per pupil; paid, partly paid and overdue cases exist.
    assert Invoice.objects.filter(school=school).count() == 24 * len(world.FEES)
    statuses = set(Invoice.objects.filter(school=school).values_list("status", flat=True))
    assert {InvoiceStatus.PAID, InvoiceStatus.PARTIALLY_PAID} <= statuses

    # Nothing visible says "(démo)" any more; invented places are not shown.
    assert not SchoolClass.objects.filter(school=school, name__icontains="démo").exists()
    assert not NewsArticle.objects.filter(school=school, title__icontains="démonstration").exists()
    assert not RoleResource.objects.filter(school=school, title__icontains="démonstration").exists()
    assert not SiteLocation.objects.filter(school=school, is_demo=True, status="PUBLISHED").exists()
    names = SchoolMembership.objects.filter(school=school).values_list("user__last_name", flat=True)
    assert "Démo" not in names
    assert not Page.objects.filter(school=school, body__endswith=PROVISIONAL).exists()
    assert not NewsArticle.objects.filter(school=school, published_at__date__gt=today).exists()

    again = seed(password=PASSWORD, demo=True)
    assert again.created == []  # same day: nothing added, nothing rewritten


def test_the_first_demo_seed_is_brought_up_to_date_but_edits_are_kept():
    w = seed(password=PASSWORD, demo=True)
    school = w.school
    # Put back what the first demo seed had written...
    klass = SchoolClass.objects.get(school=school, name="6e A")
    SchoolClass.objects.filter(pk=klass.pk).update(name="6e A (démo)")
    Level.objects.filter(school=school, code="6E").update(name="6e (démo)", cycle="Démonstration")
    Student.objects.filter(school=school, student_number="ISB-26-0001").update(
        student_number="ISB-DEMO-001", registration_number="ISB-INS-DEMO-001", last_name="Démo"
    )
    parent = SchoolMembership.objects.get(school=school, user__email="parent.demo@isbree.test").user
    parent.last_name = "Démo"
    parent.save(update_fields=["last_name"])
    NewsArticle.objects.filter(school=school, slug="rentree-scolaire").update(
        title="Préparer la rentrée (démonstration)"
    )
    page = Page.objects.get(school=school, slug="a-propos")
    Page.objects.filter(pk=page.pk).update(body=f"{page.body}\n\n{PROVISIONAL}")
    # ...and a news item the school edited itself.
    NewsArticle.objects.filter(school=school, slug="reunion-equipe").update(title="Réunion de rentrée de l'équipe")

    again = seed(password=PASSWORD, demo=True)
    assert again.created
    assert SchoolClass.objects.filter(pk=klass.pk, name="6e A").exists()
    assert Level.objects.get(school=school, code="6E").cycle == world.CYCLE
    lea = Student.objects.get(school=school, student_number="ISB-26-0001")
    assert (lea.first_name, lea.last_name) == ("Léa", "Mballa")
    parent.refresh_from_db()
    assert parent.last_name == "Mballa"
    assert "démonstration" not in NewsArticle.objects.get(school=school, slug="rentree-scolaire").title
    assert not Page.objects.get(pk=page.pk).body.endswith(PROVISIONAL)
    assert NewsArticle.objects.get(school=school, slug="reunion-equipe").title == "Réunion de rentrée de l'équipe"
    assert Student.objects.filter(school=school).count() == 24  # renamed, not duplicated


def test_the_start_check_tells_whether_the_demo_can_work():
    """scripts/render-start.sh: after a failed seed, the API starts only if the
    demo essentials exist (`seed_isbree --check-demo`, read only)."""
    with pytest.raises(CommandError):
        call_command("seed_isbree", "--check-demo")
    seed(password=PASSWORD)  # contents only: no demo accounts yet
    assert "enfant vérifié du parent de démonstration" in demo_missing()
    seed(password=PASSWORD, demo=True)
    assert demo_missing() == []
    call_command("seed_isbree", "--check-demo")  # no error
    SchoolMembership.objects.filter(user__email="gardien.demo@isbree.test").update(status="SUSPENDED")
    assert demo_missing() == ["compte actif gardien.demo@isbree.test"]


def test_illustration_files_lost_by_a_restart_are_put_back(tmp_path):
    """The free host has no persistent disk: the rows stay in the database, the
    files go. The next start (seed --images) writes them back, no duplicate."""
    (tmp_path / "1.jpg").write_bytes(jpeg().read())
    seed(password=PASSWORD, images=str(tmp_path))
    image = ContentImage.objects.get()
    private_storage().delete(image.storage_path)  # what a restart does

    again = seed(password=PASSWORD, images=str(tmp_path))
    assert private_storage().exists(image.storage_path)
    assert ContentImage.objects.count() == 1
    assert again.created == ["fichier d'image restauré : 1.jpg"]
    assert seed(password=PASSWORD, images=str(tmp_path)).created == []


def test_an_interrupted_seed_is_resumed_without_duplicates(monkeypatch):
    """The free host may stop a long first start (deploy timeout, sleep): the
    finished steps stay, the next start completes the rest, nothing twice."""

    def cut(*args, **kwargs):
        raise RuntimeError("start interrupted")

    monkeypatch.setattr(world, "_finance", cut)
    with pytest.raises(RuntimeError):
        seed(password=PASSWORD, demo=True)
    assert Student.objects.count() == 24 and not Invoice.objects.exists()  # earlier steps kept
    monkeypatch.undo()

    resumed = seed(password=PASSWORD, demo=True)
    assert any(line.startswith("facture") for line in resumed.created)
    assert Student.objects.count() == 24 and Invoice.objects.count() == 24 * len(world.FEES)
    assert demo_missing() == []


def test_a_start_with_existing_data_stays_cheap():
    """Every start of the demo host runs the seed against a remote database:
    once the data exist, it only reads, in a few queries per step."""
    seed(password=PASSWORD, demo=True)
    count = [0]

    def counter(execute, sql, params, many, context):
        count[0] += 1
        return execute(sql, params, many, context)

    with connection.execute_wrapper(counter):
        again = seed(password=PASSWORD, demo=True)
    assert again.created == []
    assert count[0] < 300, count[0]

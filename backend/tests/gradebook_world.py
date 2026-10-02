"""A small but complete school year used by the gradebook tests.

Year 2025-2026 (current)
  Trimestre 1 ── Séquence 1 (open)
              └─ Séquence 2 (open)
Class 3e A: students s1, s2, s3 (enrolled), maths coef 4 (teacher tm),
french coef 2 (teacher tf). Default scale /20.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from apps.academics import services as academics
from apps.academics.models import PeriodType
from apps.gradebook import services as gb
from apps.people import services as people

from .factories import (
    CategoryFactory,
    LevelFactory,
    SchoolClassFactory,
    StudentFactory,
    SubjectFactory,
    admin_of,
    make_teacher,
)


@dataclass
class World:
    school: object
    admin: object
    year: object
    t1: object
    s1: object
    s2: object
    klass: object
    maths: object
    french: object
    tm: object
    tf: object
    course_maths: object
    course_french: object
    students: list

    @property
    def tm_member(self):
        return self.tm.employee.membership

    @property
    def tf_member(self):
        return self.tf.employee.membership

    def assess(self, course=None, period=None, max_score=20, weight=1, name="Devoir"):
        course = course or self.course_maths
        teacher = self.tm_member if course == self.course_maths else self.tf_member
        return gb.create_assessment(
            course,
            period or self.s1,
            actor=teacher,
            name=name,
            assessment_type="EXAM",
            max_score=Decimal(max_score),
            weight=Decimal(weight),
        )

    def grade(self, assessment, student, score, **kw):
        teacher = self.tm_member if assessment.course == self.course_maths else self.tf_member
        return gb.enter_grade(assessment, student, Decimal(str(score)), actor=teacher, **kw)


def make_world(school):
    admin = admin_of(school)
    year = academics.set_current_year(
        academics.create_academic_year(
            school, name="2025-2026", start_date=date(2025, 9, 1), end_date=date(2026, 7, 31)
        )
    )
    t1 = academics.create_period(
        year,
        name="Trimestre 1",
        period_type=PeriodType.TRIMESTER,
        order_index=1,
        start_date=date(2025, 9, 1),
        end_date=date(2025, 12, 20),
    )
    s1 = academics.create_period(
        year,
        name="Séquence 1",
        period_type=PeriodType.SEQUENCE,
        order_index=1,
        start_date=date(2025, 9, 1),
        end_date=date(2025, 10, 31),
        parent=t1,
    )
    s2 = academics.create_period(
        year,
        name="Séquence 2",
        period_type=PeriodType.SEQUENCE,
        order_index=2,
        start_date=date(2025, 11, 1),
        end_date=date(2025, 12, 20),
        parent=t1,
    )
    klass = SchoolClassFactory(school=school, name="3e A", academic_year=year, level=LevelFactory(school=school))
    sci, lit = CategoryFactory(school=school, code="SCI"), CategoryFactory(school=school, code="LIT")
    maths = SubjectFactory(school=school, code="MATH", name="Mathématiques", category=sci)
    french = SubjectFactory(school=school, code="FR", name="Français", category=lit)
    tm = make_teacher(school, category=sci, primary_subject=maths)
    tf = make_teacher(school, category=lit, primary_subject=french)
    course_maths = gb.create_course(klass, maths, tm, actor=admin, coefficient=Decimal("4"))
    course_french = gb.create_course(klass, french, tf, actor=admin, coefficient=Decimal("2"))
    students = [StudentFactory(school=school, last_name=f"Élève{i}") for i in range(3)]
    for student in students:
        people.enroll_student(student, klass)
    return World(school, admin, year, t1, s1, s2, klass, maths, french, tm, tf, course_maths, course_french, students)

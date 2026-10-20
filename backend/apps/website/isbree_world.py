"""The fictitious school life of the ISBREE demonstration (`seed_isbree --demo`).

One coherent, reproducible world instead of a few isolated rows:

- four classes of the first cycle (6e A to 3e A), each with its room;
- seven subjects, each taught in every class by ONE teacher (the demo teacher
  teaches mathematics), with a conflict-free weekly timetable and the dated
  sessions around today (regenerated at each run, so the planning never
  looks empty);
- 24 pupils (six per class) — the demo parent has two of them, in 6e A and 4e A;
- the year's periods (three terms, two sequences each), the assessments
  already held and their marks;
- the attendance of the last school days (gate scans by the demo guardian,
  then the day closed: a few late arrivals and absences);
- the fees of the year, invoices and cash payments recorded at the desk
  (paid, partly paid, overdue).

Everything is FICTITIOUS (names, numbers, amounts, marks) and goes through
the domain services, as an administrator would do it: rules, constraints and
audit apply. Idempotent: every object is looked up by a stable natural key;
nothing is deleted. Reserved `.test` e-mail addresses, no phone number.
"""

import hashlib
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.utils import timezone

from apps.academics import services as academics
from apps.academics.models import AcademicPeriod, Level, PedagogicalCategory, PeriodType, Room, SchoolClass, Subject
from apps.accounts.models import SchoolMembership
from apps.attendance import services as attendance
from apps.attendance.models import AttendancePolicy, StudentDailyAttendance
from apps.finance import services as finance
from apps.finance.models import FeeType, Invoice, InvoiceStatus
from apps.gradebook import services as gradebook
from apps.gradebook.models import Assessment, Course, Grade
from apps.people import parent_workflow
from apps.people import services as people
from apps.people.models import ParentStudent, Student
from apps.scheduling import services as scheduling
from apps.scheduling.models import ScheduleSlot, SchoolBreak

DOMAIN = "isbree.test"
CYCLE = "Premier cycle"

LEVELS = [("6E", "Sixième"), ("5E", "Cinquième"), ("4E", "Quatrième"), ("3E", "Troisième")]
# (class, level code, room code, room name)
CLASSES = [
    ("6e A", "6E", "S101", "Salle 101"),
    ("5e A", "5E", "S102", "Salle 102"),
    ("4e A", "4E", "S201", "Salle 201"),
    ("3e A", "3E", "S202", "Salle 202"),
]

# Category codes: SCI (created by the first demo seed), LITERARY (default
# category of every school), EPS (created here).
CATEGORIES = {"SCI": "Mathématiques et sciences", "EPS": "Éducation physique et sportive"}
# (code, name, category, weekly hours, coefficient)
SUBJECTS = [
    ("MATH", "Mathématiques", "SCI", 4, Decimal("4")),
    ("FR", "Français", "LITERARY", 5, Decimal("4")),
    ("ANG", "Anglais", "LITERARY", 3, Decimal("3")),
    ("HG", "Histoire-Géographie", "LITERARY", 3, Decimal("2")),
    ("SVT", "Sciences de la vie et de la Terre", "SCI", 2, Decimal("2")),
    ("PC", "Physique-Chimie", "SCI", 2, Decimal("2")),
    ("EPS", "Éducation physique et sportive", "EPS", 2, Decimal("1")),
]
# One teacher per subject. MATH is the demo teacher (enseignant.demo@isbree.test).
TEACHERS = {
    "FR": ("Mireille", "Ngono", "ENS-FR-01"),
    "ANG": ("Grace", "Tabi", "ENS-ANG-01"),
    "HG": ("Hervé", "Mbida", "ENS-HG-01"),
    "SVT": ("Florence", "Eyenga", "ENS-SVT-01"),
    "PC": ("Rodrigue", "Kamga", "ENS-PC-01"),
    "EPS": ("Ibrahim", "Moussa", "ENS-EPS-01"),
}

# Teaching hours: four in the morning, two in the afternoon; Wednesday afternoon free.
HOURS = [
    (time(7, 30), time(8, 25)),
    (time(8, 25), time(9, 20)),
    (time(9, 35), time(10, 30)),
    (time(10, 30), time(11, 25)),
    (time(13, 0), time(13, 55)),
    (time(13, 55), time(14, 50)),
]
WEEKDAYS = (1, 2, 3, 4, 5)

# Pupils: (number, first name, last name, sex, birth date, class). ISB-26-0001 is
# the pupil created by the first demo seed (then "ISB-DEMO-001"); 0007 is her brother.
STUDENTS = [
    ("ISB-26-0001", "Léa", "Mballa", "F", "2015-03-12", "6e A"),
    ("ISB-26-0002", "Kevin", "Ndzana", "M", "2015-01-27", "6e A"),
    ("ISB-26-0003", "Aïssatou", "Bouba", "F", "2014-11-05", "6e A"),
    ("ISB-26-0004", "Junior", "Essomba", "M", "2015-06-18", "6e A"),
    ("ISB-26-0005", "Ruth", "Nkolo", "F", "2015-08-02", "6e A"),
    ("ISB-26-0006", "Yannick", "Tchoupo", "M", "2014-12-14", "6e A"),
    ("ISB-26-0007", "Noah", "Mballa", "M", "2013-04-21", "4e A"),
    ("ISB-26-0008", "Brenda", "Fouda", "F", "2014-02-09", "5e A"),
    ("ISB-26-0009", "Samuel", "Onana", "M", "2014-05-30", "5e A"),
    ("ISB-26-0010", "Mariam", "Hamadou", "F", "2013-10-11", "5e A"),
    ("ISB-26-0011", "Cédric", "Abena", "M", "2014-07-22", "5e A"),
    ("ISB-26-0012", "Vanessa", "Ekane", "F", "2014-03-15", "5e A"),
    ("ISB-26-0013", "Ulrich", "Nana", "M", "2014-09-03", "5e A"),
    ("ISB-26-0014", "Christelle", "Atangana", "F", "2013-01-19", "4e A"),
    ("ISB-26-0015", "Boris", "Mvondo", "M", "2013-06-07", "4e A"),
    ("ISB-26-0016", "Fadimatou", "Oumarou", "F", "2012-12-28", "4e A"),
    ("ISB-26-0017", "Arnaud", "Ewane", "M", "2013-08-16", "4e A"),
    ("ISB-26-0018", "Sandrine", "Bella", "F", "2013-03-04", "4e A"),
    ("ISB-26-0019", "Loïc", "Manga", "M", "2012-05-25", "3e A"),
    ("ISB-26-0020", "Estelle", "Ngo Nyemb", "F", "2012-02-13", "3e A"),
    ("ISB-26-0021", "Patrick", "Zambo", "M", "2011-11-30", "3e A"),
    ("ISB-26-0022", "Nadège", "Mengue", "F", "2012-07-08", "3e A"),
    ("ISB-26-0023", "Moussa", "Abdoulaye", "M", "2012-04-17", "3e A"),
    ("ISB-26-0024", "Laura", "Tchana", "F", "2012-09-21", "3e A"),
]
LEGACY_NUMBERS = {"ISB-26-0001": ("ISB-DEMO-001", "ISB-INS-DEMO-001")}
PARENT_CHILDREN = ["ISB-26-0001", "ISB-26-0007"]
PARENT_DOCUMENT = "DEMO-0001"  # fictitious ID number of the demo parent (only its HMAC is stored)

# Fees of the year (fictitious amounts, FCFA): (code, name, amount, due month, due day).
FEES = [
    ("INSCRIPTION", "Frais d'inscription", Decimal("25000"), 9, 1),
    ("SCOLARITE_T1", "Scolarité — 1re tranche", Decimal("60000"), 10, 5),
    ("SCOLARITE_T2", "Scolarité — 2e tranche", Decimal("45000"), 1, 15),
]
# Pupils whose 1st instalment is only partly paid, and those who have not paid it yet.
PARTIAL_T1 = {"ISB-26-0007": Decimal("30000"), "ISB-26-0011": Decimal("40000"), "ISB-26-0017": Decimal("20000")}
UNPAID_T1 = {"ISB-26-0015", "ISB-26-0022"}

ATTENDANCE_DAYS = 10  # school days of attendance kept up to date before today
SESSIONS_BEFORE, SESSIONS_AFTER = 21, 35  # dated sessions generated around today


def _key(*parts):
    """A stable pseudo-random number from text (same world at every run)."""
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


# =============================================================================
# Structure: levels, classes, rooms, subjects, teachers, courses
# =============================================================================


def _levels(w):
    levels = {}
    for order, (code, name) in enumerate(LEVELS, start=1):
        level = Level.objects.filter(school=w.school, code=code).first()
        if level is None:
            level = academics.create_level(
                w.school, actor=w.admin, code=code, name=name, cycle=CYCLE, order_index=order, public_visible=True
            )
            w.created.append(f"niveau {name}")
        elif level.name.endswith("(démo)"):  # first demo seed: "6e (démo)", cycle "Démonstration"
            level = academics.update_level(level, actor=w.admin, name=name, cycle=CYCLE, order_index=order)
            w.created.append(f"niveau renommé {name}")
        levels[code] = level
    return levels


def _classes(w, year, levels):
    classes = {}
    for name, level_code, room_code, room_name in CLASSES:
        room = Room.objects.filter(school=w.school, code=room_code).first() or scheduling.create_room(
            w.school, actor=w.admin, code=room_code, name=room_name, capacity=40
        )
        klass = SchoolClass.objects.filter(school=w.school, academic_year=year, name=name).first()
        legacy = SchoolClass.objects.filter(school=w.school, academic_year=year, name=f"{name} (démo)").first()
        if klass is None and legacy is not None:
            klass = academics.update_class(legacy, actor=w.admin, name=name)
            w.created.append(f"classe renommée {name}")
        if klass is None:
            klass = academics.create_class(
                w.school, actor=w.admin, name=name, level=levels[level_code], academic_year=year
            )
            w.created.append(f"classe {name}")
        if klass.main_room_id is None:
            scheduling.set_class_main_room(klass, room, actor=w.admin)
            klass.refresh_from_db()
        classes[name] = klass
    return classes


def _subjects(w):
    for code, name in CATEGORIES.items():
        category = PedagogicalCategory.objects.filter(school=w.school, code=code).first()
        if category is None:
            academics.create_category(w.school, actor=w.admin, code=code, name=name)
            w.created.append(f"catégorie {name}")
        elif category.name.endswith("(démo)"):
            academics.update_category(category, actor=w.admin, name=name)
    subjects = {}
    for code, name, category_code, _, _ in SUBJECTS:
        subject = Subject.objects.filter(school=w.school, code=code).first()
        if subject is None:
            category = PedagogicalCategory.objects.get(school=w.school, code=category_code)
            subject = academics.create_subject(w.school, actor=w.admin, code=code, name=name, category=category)
            w.created.append(f"matière {name}")
        subjects[code] = subject
    return subjects


def _teachers(w, subjects, math_teacher):
    teachers = {"MATH": math_teacher}
    for code, (first_name, last_name, number) in TEACHERS.items():
        email = f"{first_name}.{last_name}@{DOMAIN}".lower().replace("é", "e").replace("ï", "i")
        member = SchoolMembership.objects.filter(school=w.school, user__email__iexact=email).first()
        if member is None:
            subject = subjects[code]
            teacher = people.admin_create_teacher(
                w.school,
                actor=w.admin,
                first_name=first_name,
                last_name=last_name,
                email=email,
                employee_number=number,
                pedagogical_category=subject.category,
                primary_subject=subject,
            )
            w.created.append(f"enseignant {first_name} {last_name}")
        else:
            teacher = member.employee_profile.teacher_profile
        teachers[code] = teacher
    return teachers


def _courses(w, classes, subjects, teachers):
    courses = {}
    for klass in classes.values():
        for code, _, _, hours, coefficient in SUBJECTS:
            course = Course.objects.filter(school_class=klass, subject=subjects[code], active=True).first()
            if course is None:
                course = gradebook.create_course(
                    klass, subjects[code], teachers[code], actor=w.admin, coefficient=coefficient, weekly_hours=hours
                )
                w.created.append(f"cours {code} {klass.name}")
            elif course.coefficient != coefficient:  # the first demo course had the default coefficient
                course = gradebook.update_course(course, actor=w.admin, coefficient=coefficient)
            courses[(klass.name, code)] = course
    return courses


# =============================================================================
# Timetable: weekly slots, holidays, dated sessions
# =============================================================================


def timetable():
    """{(class, subject): [(weekday, hour index), ...]} — deterministic and
    conflict-free: a class has one subject per hour, a teacher (one per
    subject) one class per hour, at most two hours of a subject per day."""
    free_hours = [(d, h) for d in WEEKDAYS for h in range(len(HOURS)) if not (d == 3 and h >= 4)]
    busy_teacher = {code: set() for code, *_ in SUBJECTS}
    plan = {}
    for index, (klass, *_) in enumerate(CLASSES):
        busy_class, per_day = set(), {}
        for code, _, _, hours, _ in SUBJECTS:
            slots = []
            # Start each class on a different day to spread the subjects over the week.
            order = sorted(free_hours, key=lambda dh: ((dh[0] - 1 - index) % 5, dh[1]))
            for day, hour in order:
                if len(slots) == hours:
                    break
                if (day, hour) in busy_class or (day, hour) in busy_teacher[code]:
                    continue
                if per_day.get((code, day), 0) >= 2 or (slots and slots[-1][0] == day and slots[-1][1] != hour - 1):
                    continue
                slots.append((day, hour))
                busy_class.add((day, hour))
                busy_teacher[code].add((day, hour))
                per_day[(code, day)] = per_day.get((code, day), 0) + 1
            if len(slots) != hours:
                raise RuntimeError(f"No room in the timetable for {code} in {klass}.")
            plan[(klass, code)] = slots
    return plan


def _breaks(w, year):
    tz = ZoneInfo(w.school.timezone)
    y = year.start_date.year
    for name, start, end in [
        ("Congés de Noël", date(y, 12, 19), date(y + 1, 1, 3)),
        ("Congés de Pâques", date(y + 1, 3, 27), date(y + 1, 4, 11)),
    ]:
        if not SchoolBreak.objects.filter(academic_year=year, name=name).exists():
            scheduling.create_school_break(
                year,
                actor=w.admin,
                name=name,
                start_datetime=datetime.combine(start, time(0), tz),
                end_datetime=datetime.combine(end, time(23, 59), tz),
            )
            w.created.append(f"vacances : {name}")


def _timetable(w, year, courses):
    for (klass, code), hours in timetable().items():
        course = courses[(klass, code)]
        for day, hour in hours:
            start, end = HOURS[hour]
            if not ScheduleSlot.objects.filter(course=course, weekday=day, start_time=start).exists():
                scheduling.create_slot(course, actor=w.admin, weekday=day, start_time=start, end_time=end)
                w.created.append(f"créneau {klass} {code}")
    today = timezone.localdate()
    start = max(year.start_date, today - timedelta(days=SESSIONS_BEFORE))
    end = min(year.end_date, today + timedelta(days=SESSIONS_AFTER))
    if start <= end:
        summary = scheduling.generate_sessions(w.school, actor=w.admin, date_from=start, date_to=end)
        if summary["created"]:
            w.created.append(f"{summary['created']} séances datées")


# =============================================================================
# Pupils, the demo parent's second child
# =============================================================================


def _students(w, classes):
    students = {}
    for number, first_name, last_name, sex, born, klass in STUDENTS:
        student = Student.objects.filter(school=w.school, student_number=number).first()
        legacy = LEGACY_NUMBERS.get(number)
        if student is None and legacy:
            student = Student.objects.filter(school=w.school, student_number=legacy[0]).first()
            if student is not None:
                student = people.admin_update_student(
                    student,
                    actor=w.admin,
                    student_number=number,
                    registration_number=number.replace("ISB", "INS"),
                    last_name=last_name,
                    date_of_birth=date.fromisoformat(born),
                )
                w.created.append(f"élève renommé {first_name} {last_name}")
        if student is None:
            student = people.admin_create_student(
                w.school,
                actor=w.admin,
                enrollment={"school_class": classes[klass]},
                student_number=number,
                registration_number=number.replace("ISB", "INS"),
                first_name=first_name,
                last_name=last_name,
                date_of_birth=date.fromisoformat(born),
                sex=sex,
                birth_place="Yaoundé",
            )
            w.created.append(f"élève {first_name} {last_name}")
        students[number] = student
    return students


def _family(w, parent_member, students):
    for number in PARENT_CHILDREN:
        student = students[number]
        if ParentStudent.objects.filter(
            parent__membership=parent_member, student=student, identity_verified=True
        ).exists():
            continue
        request = parent_workflow.request_link(
            parent_member,
            student_number=student.student_number,
            date_of_birth=student.date_of_birth,
            relationship_type="MOTHER",
            document_type="CNI",
            document_number=PARENT_DOCUMENT,
        )
        parent_workflow.check_identity(request, actor=w.admin, document_type="CNI", document_number=PARENT_DOCUMENT)
        parent_workflow.record_student_approval(request, actor=w.admin, decision="APPROVED", note="Dossier complet")
        parent_workflow.approve_link_request(
            request,
            actor=w.admin,
            can_pay=True,
            can_view_financial_data=True,
            can_receive_notifications=True,
            can_submit_complaints=True,
        )
        w.created.append(f"lien parent-enfant {student.first_name} {student.last_name}")


# =============================================================================
# Periods, assessments and marks
# =============================================================================


def _periods(w, year):
    y = year.start_date.year
    terms = [
        (
            "1er trimestre",
            date(y, 9, 7),
            date(y, 12, 18),
            [("Séquence 1", 9, 7, 10, 16), ("Séquence 2", 10, 19, 12, 18)],
        ),
        (
            "2e trimestre",
            date(y + 1, 1, 4),
            date(y + 1, 3, 26),
            [("Séquence 3", 1, 4, 2, 12), ("Séquence 4", 2, 15, 3, 26)],
        ),
        (
            "3e trimestre",
            date(y + 1, 4, 12),
            date(y + 1, 6, 25),
            [("Séquence 5", 4, 12, 5, 14), ("Séquence 6", 5, 17, 6, 25)],
        ),
    ]
    sequences = []
    for order, (name, start, end, children) in enumerate(terms, start=1):
        term = AcademicPeriod.objects.filter(academic_year=year, name=name).first() or academics.create_period(
            year, name=name, period_type=PeriodType.TRIMESTER, order_index=order, start_date=start, end_date=end
        )
        for index, (child, m1, d1, m2, d2) in enumerate(children, start=1):
            first, last = date(y + (m1 < 9), m1, d1), date(y + (m2 < 9), m2, d2)
            sequence = AcademicPeriod.objects.filter(academic_year=year, name=child).first()
            if sequence is None:
                sequence = academics.create_period(
                    year,
                    name=child,
                    period_type=PeriodType.SEQUENCE,
                    order_index=index,
                    start_date=first,
                    end_date=last,
                    parent=term,
                )
                w.created.append(f"période {child}")
            sequences.append(sequence)
    return sequences


def _mark(student, code, assessment_name):
    """A plausible mark out of 20: the pupil's level, the subject, the day."""
    level = 9 + _key(student.student_number) % 8  # 9 to 16
    swing = _key(student.student_number, code) % 7 - 3  # -3 to +3
    noise = _key(student.student_number, code, assessment_name) % 5 - 2  # -2 to +2
    half_points = _key(assessment_name, student.student_number) % 2
    return Decimal(max(3, min(19, level + swing + noise))) + Decimal("0.5") * half_points


def _marks(w, sequences, courses, students):
    today = timezone.localdate()
    pupils = {}
    for student in students.values():
        enrollment = student.enrollments.filter(status="ACTIVE").select_related("school_class").first()
        if enrollment:
            pupils.setdefault(enrollment.school_class.name, []).append(student)
    for sequence in sequences:
        for name, kind, offset in [
            ("Interrogation écrite", "TEST", 14),
            ("Devoir surveillé", "EXAM", 30),
        ]:
            held = sequence.start_date + timedelta(days=offset)
            if held > min(today - timedelta(days=2), sequence.end_date):
                continue  # not held yet: no invented future marks
            for (klass, code), course in courses.items():
                label = f"{name} — {sequence.name}"
                assessment = Assessment.objects.filter(course=course, academic_period=sequence, name=label).first()
                if assessment is None:
                    assessment = gradebook.create_assessment(
                        course,
                        sequence,
                        actor=w.admin,
                        name=label,
                        assessment_type=kind,
                        max_score=Decimal("20"),
                        assessment_date=held,
                    )
                    w.created.append(f"évaluation {klass} {code} {label}")
                for student in pupils.get(klass, []):
                    if not Grade.objects.filter(assessment=assessment, student=student).exists():
                        gradebook.enter_grade(assessment, student, _mark(student, code, label), actor=w.admin)


# =============================================================================
# Attendance of the last school days
# =============================================================================


def _attendance(w, year, guardian_member, students):
    for day in WEEKDAYS:
        if not AttendancePolicy.objects.filter(school=w.school, day_of_week=day).exists():
            attendance.set_policy(
                w.school, day, actor=w.admin, late_after_time=time(7, 30), morning_absence_cutoff=time(10, 0)
            )
    qr = {number: attendance.issue_qr_code(s, actor=w.admin, academic_year=year) for number, s in students.items()}
    tz = ZoneInfo(w.school.timezone)
    breaks = list(SchoolBreak.objects.filter(academic_year=year))
    days, day = [], timezone.localdate() - timedelta(days=1)
    while len(days) < ATTENDANCE_DAYS and day >= year.start_date:
        moment = datetime.combine(day, time(12), tz)
        if day.isoweekday() in WEEKDAYS and not any(b.start_datetime <= moment <= b.end_datetime for b in breaks):
            days.append(day)
        day -= timedelta(days=1)
    for day in reversed(days):
        if StudentDailyAttendance.objects.filter(school=w.school, date=day).exists():
            continue
        for number in students:
            roll = _key(number, day) % 100
            if roll < 4:
                continue  # absent: closing the day records it
            minutes = 40 if roll < 10 else 5 + roll % 25  # 07:35 (late) or 07:05-07:29
            arrival = datetime.combine(day, time(7), tz) + timedelta(minutes=minutes)
            attendance.scan(qr[number].token, actor=guardian_member, at=arrival)
        attendance.finalize_day(w.school, day, actor=w.admin)
        w.created.append(f"présences du {day:%d/%m/%Y}")


# =============================================================================
# Fees, invoices and payments at the desk
# =============================================================================


def _finance(w, year, students):
    fee_types = {}
    for code, name, *_ in FEES:
        fee_types[code] = FeeType.objects.filter(school=w.school, code=code).first() or finance.create_fee_type(
            w.school, actor=w.admin, code=code, name=name
        )
    y = year.start_date.year
    for number, student in students.items():
        for code, _, amount, month, day in FEES:
            fee_type = fee_types[code]
            invoice = (
                Invoice.objects.filter(school=w.school, student=student, lines__fee_type=fee_type)
                .exclude(status=InvoiceStatus.CANCELLED)
                .first()
            )
            if invoice is None:
                invoice = finance.issue_invoice(
                    student,
                    actor=w.admin,
                    due_date=date(y + (month < 9), month, day),
                    lines=[{"fee_type": fee_type, "unit_price": amount}],
                )
                w.created.append(f"facture {code} {number}")
            paid = Decimal("0")
            if code == "INSCRIPTION":
                paid = amount
            elif code == "SCOLARITE_T1" and number not in UNPAID_T1:
                paid = PARTIAL_T1.get(number, amount)
            if paid:
                outcome = finance.initiate_payment(
                    student,
                    actor=w.admin,
                    amount=paid,
                    payment_method="CASH",
                    idempotency_key=f"isbree-demo-{number}-{code}",
                    invoices=[invoice],
                )
                if not outcome.replayed:
                    w.created.append(f"paiement {code} {number}")


# =============================================================================


def structure(w, year):
    """Levels, classes and subjects: what the demo accounts of isbree_seed need first."""
    levels = _levels(w)
    return _classes(w, year, levels), _subjects(w)


def build(w, *, year, classes, subjects, maths_teacher, parent_member, guardian_member):
    """Complete the school life around the demo accounts of isbree_seed._demo."""
    teachers = _teachers(w, subjects, maths_teacher)
    courses = _courses(w, classes, subjects, teachers)
    _breaks(w, year)
    _timetable(w, year, courses)
    students = _students(w, classes)
    _family(w, parent_member, students)
    sequences = _periods(w, year)
    _marks(w, sequences, courses, students)
    _attendance(w, year, guardian_member, students)
    _finance(w, year, students)

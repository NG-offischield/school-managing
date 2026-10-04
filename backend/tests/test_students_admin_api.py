"""Students administration (admin desktop "Gestion académique → Élèves",
ADR 0018): services + /api/v1/students/ writes, enrollments, class change,
archive, photo, history, isolation, permissions, history protection."""

import io
from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.utils import timezone
from PIL import Image

from apps.academics import services as academics
from apps.attendance import services as att
from apps.attendance.models import StudentDailyAttendance
from apps.audit.models import AuditLog
from apps.documents import services as docs
from apps.people import services as people
from apps.people.models import EnrollmentStatus, HardDeleteForbidden, Student, StudentEnrollment, StudentStatus

from .conftest import DB
from .factories import LevelFactory, SchoolClassFactory, SchoolFactory, StudentFactory, member_with_role
from .gradebook_world import make_world
from .test_classes_api import as_, data, error

pytestmark = DB

STUDENTS = "/api/v1/students/"


@pytest.fixture
def w(school):
    w = make_world(school)  # 2025-2026 current, class 3e A with 3 enrolled pupils, grades possible
    w.klass_b = SchoolClassFactory(school=school, name="3e B", academic_year=w.year, level=w.klass.level)
    w.level_2 = LevelFactory(school=school, code="2NDE", name="Seconde")
    w.seconde = SchoolClassFactory(school=school, name="2nde A", academic_year=w.year, level=w.level_2)
    return w


def identity(**extra):
    return {
        "student_number": "MAT-2025-001",
        "registration_number": "INS-001",
        "first_name": "Awa",
        "last_name": "Ndiaye",
        "date_of_birth": "2012-05-04",
        "sex": "F",
        "birth_place": "Douala",
        **extra,
    }


def picture(fmt="PNG", size=(400, 500), exif=False):
    image = Image.new("RGB", size, (30, 90, 160))
    out = io.BytesIO()
    options = {}
    if exif:
        tags = Image.Exif()
        tags[0x010F] = "PhoneMaker"  # Make
        tags[0x0110] = "Model X"  # Model
        options["exif"] = tags.tobytes()
    image.save(out, format=fmt, **options)
    return SimpleUploadedFile(f"photo.{fmt.lower()}", out.getvalue(), content_type=f"image/{fmt.lower()}")


# =============================================================================
# Create / read / update
# =============================================================================


def test_admin_creates_a_student_and_enrolls_in_one_step(w):
    body = data(
        as_(w.admin).post(
            STUDENTS,
            identity(enrollment={"school_class": str(w.klass_b.pk), "enrollment_date": "2025-09-02"}),
            format="json",
        ),
        201,
    )
    assert (body["student_number"], body["status"], body["has_photo"]) == ("MAT-2025-001", "ACTIVE", False)
    assert body["enrollment"]["class_name"] == "3e B" and body["enrollment"]["academic_year_name"] == "2025-2026"
    assert body["enrollment"]["level_code"] == w.klass.level.code and body["enrollment"]["status"] == "ACTIVE"
    student = Student.objects.get(pk=body["id"])
    enrollment = student.enrollments.get()
    assert (enrollment.academic_year, enrollment.school_class, enrollment.enrollment_date) == (
        w.year,
        w.klass_b,
        date(2025, 9, 2),
    )
    assert AuditLog.objects.filter(action="STUDENT_CREATED", entity_id=student.pk).exists()
    assert AuditLog.objects.filter(action="STUDENT_ENROLLED", entity_id=enrollment.pk).exists()


def test_create_is_atomic_and_numbers_unique(w):
    admin = as_(w.admin)
    data(admin.post(STUDENTS, identity(), format="json"), 201)
    err = error(
        admin.post(STUDENTS, identity(registration_number="INS-002", student_number="mat-2025-001"), format="json"), 409
    )
    assert err["details"]["rule"] == "duplicate_student_number"
    err = error(admin.post(STUDENTS, identity(student_number="MAT-2"), format="json"), 409)
    assert err["details"]["rule"] == "duplicate_registration_number"
    # Enrollment refused -> the student is not created either (one transaction).
    count = Student.objects.count()
    closed = academics.create_academic_year(
        w.school, name="2019-2020", start_date=date(2019, 9, 1), end_date=date(2020, 7, 31)
    )
    old_class = SchoolClassFactory(school=w.school, name="Old", academic_year=closed, level=w.klass.level)
    closed.status = "CLOSED"
    closed.save()
    err = error(
        admin.post(
            STUDENTS,
            identity(
                student_number="MAT-9", registration_number="INS-9", enrollment={"school_class": str(old_class.pk)}
            ),
            format="json",
        ),
        400,
    )
    assert err["details"]["rule"] == "year_closed" and Student.objects.count() == count
    with pytest.raises(IntegrityError), transaction.atomic():  # PostgreSQL agrees on uniqueness
        StudentFactory(school=w.school, student_number="MAT-2025-001")


def test_identity_validation(w):
    admin = as_(w.admin)
    future = timezone.localdate().replace(year=timezone.localdate().year + 1).isoformat()
    assert error(admin.post(STUDENTS, identity(date_of_birth=future), format="json"), 400)["details"]["rule"] == (
        "birth_date_future"
    )
    assert error(admin.post(STUDENTS, identity(sex="X"), format="json"), 400)["code"] == "VALIDATION_ERROR"
    assert error(admin.post(STUDENTS, identity(first_name="  "), format="json"), 400)
    assert error(admin.post(STUDENTS, identity(height_cm=999), format="json"), 400)["details"]["rule"] == (
        "height_invalid"
    )


def test_detail_update_and_archived_is_frozen(w):
    admin = as_(w.admin)
    student = w.students[0]
    url = f"{STUDENTS}{student.pk}/"
    body = data(admin.get(url))
    assert body["enrollment"]["class_name"] == "3e A" and "address" in body
    body = data(admin.patch(url, {"first_name": "Aïssatou", "address": "Bonapriso", "height_cm": 150}, format="json"))
    assert (body["first_name"], body["address"], body["height_cm"]) == ("Aïssatou", "Bonapriso", 150)
    assert AuditLog.objects.filter(action="STUDENT_UPDATED", entity_id=student.pk).exists()
    other = w.students[1]
    err = error(admin.patch(url, {"student_number": other.student_number.lower()}, format="json"), 409)
    assert err["details"]["rule"] == "duplicate_student_number"
    assert data(admin.patch(url, {"status": "GRADUATED"}, format="json"))["status"] == "ACTIVE"  # not via PATCH


def test_list_filters_search_and_year_columns(w):
    admin = as_(w.admin)
    new = data(admin.post(STUDENTS, identity(enrollment={"school_class": str(w.seconde.pk)}), format="json"), 201)
    unenrolled = data(
        admin.post(
            STUDENTS, identity(student_number="M-X", registration_number="I-X", last_name="Zola"), format="json"
        ),
        201,
    )
    rows = data(admin.get(STUDENTS))
    assert len(rows) == 5
    by_id = {r["id"]: r for r in rows}
    assert by_id[new["id"]]["enrollment"]["class_name"] == "2nde A"
    assert by_id[unenrolled["id"]]["enrollment"] is None
    assert [r["id"] for r in data(admin.get(f"{STUDENTS}?level={w.level_2.pk}"))] == [new["id"]]
    assert {r["id"] for r in data(admin.get(f"{STUDENTS}?school_class={w.klass.pk}"))} == {
        str(s.pk) for s in w.students
    }
    assert [r["id"] for r in data(admin.get(f"{STUDENTS}?enrollment_status=NONE"))] == [unenrolled["id"]]
    assert [r["id"] for r in data(admin.get(f"{STUDENTS}?search=ndia"))] == [new["id"]]
    assert [r["id"] for r in data(admin.get(f"{STUDENTS}?search=m-x"))] == [unenrolled["id"]]
    assert len(data(admin.get(f"{STUDENTS}?academic_year={w.year.pk}"))) == 4  # that year's pupils only
    assert data(admin.get(f"{STUDENTS}?status=ARCHIVED")) == []
    page = admin.get(f"{STUDENTS}?page_size=2").json()
    assert page["meta"]["count"] == 5 and len(page["data"]) == 2  # paginated by the API
    assert error(admin.get(f"{STUDENTS}?enrollment_status=NOPE"), 400)


# =============================================================================
# Enrollment, class change, withdrawal
# =============================================================================


def test_enroll_rules(w):
    admin = as_(w.admin)
    student = data(admin.post(STUDENTS, identity(), format="json"), 201)
    url = f"{STUDENTS}{student['id']}/enrollments/"
    body = data(admin.post(url, {"school_class": str(w.klass_b.pk)}, format="json"), 201)
    assert (body["class_name"], body["level_code"], body["academic_year"]) == (
        "3e B",
        w.klass.level.code,
        str(w.year.pk),
    )
    err = error(admin.post(url, {"school_class": str(w.klass.pk)}, format="json"), 409)
    assert err["details"]["rule"] == "already_enrolled"  # one class per year
    rows = data(admin.get(url))
    assert [r["class_name"] for r in rows] == ["3e B"]
    # Date outside the year, full class, inactive class.
    other = data(admin.post(STUDENTS, identity(student_number="M2", registration_number="I2"), format="json"), 201)
    url2 = f"{STUDENTS}{other['id']}/enrollments/"
    err = error(
        admin.post(url2, {"school_class": str(w.klass_b.pk), "enrollment_date": "2030-01-01"}, format="json"), 400
    )
    assert err["details"]["rule"] == "date_outside_year"
    w.klass_b.capacity = 1
    w.klass_b.save()
    assert error(admin.post(url2, {"school_class": str(w.klass_b.pk)}, format="json"), 409)["details"]["rule"] == (
        "class_full"
    )
    w.seconde.active = False
    w.seconde.save()
    assert error(admin.post(url2, {"school_class": str(w.seconde.pk)}, format="json"), 400)["details"]["rule"] == (
        "class_inactive"
    )


def test_change_class_same_year_only(w):
    admin = as_(w.admin)
    enrollment = w.students[0].enrollments.get()
    url = f"/api/v1/enrollments/{enrollment.pk}/change-class/"
    body = data(admin.post(url, {"school_class": str(w.klass_b.pk)}, format="json"))
    assert body["class_name"] == "3e B" and StudentEnrollment.objects.filter(student=w.students[0]).count() == 1
    assert error(admin.post(url, {"school_class": str(w.klass_b.pk)}, format="json"), 409)["details"]["rule"] == (
        "same_class"
    )
    next_year = academics.create_academic_year(
        w.school, name="2026-2027", start_date=date(2026, 9, 1), end_date=date(2027, 7, 31)
    )
    later = SchoolClassFactory(school=w.school, name="2nde B", academic_year=next_year, level=w.level_2)
    err = error(admin.post(url, {"school_class": str(later.pk)}, format="json"), 400)
    assert err["details"]["rule"] == "class_other_year"
    with pytest.raises(IntegrityError), transaction.atomic():  # the DB refuses a class of another year too
        StudentEnrollment.objects.filter(pk=enrollment.pk).update(school_class=later)
    history = data(admin.get(f"{STUDENTS}{w.students[0].pk}/history/"))
    assert history[0]["action"] == "STUDENT_CLASS_CHANGED" and history[0]["summary"] == "3e A → 3e B (2025-2026)"


def test_withdraw_then_archive_then_reactivate(w):
    admin = as_(w.admin)
    student = w.students[0]
    url = f"{STUDENTS}{student.pk}/"
    assert error(admin.post(f"{url}archive/"), 409)["details"]["rule"] == "active_enrollment"
    enrollment = student.enrollments.get()
    body = data(
        admin.post(
            f"/api/v1/enrollments/{enrollment.pk}/withdraw/",
            {"end_date": str(enrollment.enrollment_date)},
            format="json",
        )
    )
    assert (body["status"], body["end_date"]) == ("WITHDRAWN", str(enrollment.enrollment_date))
    assert error(admin.post(f"/api/v1/enrollments/{enrollment.pk}/withdraw/"), 409)["details"]["rule"] == (
        "enrollment_closed"
    )
    assert (
        error(
            admin.post(
                f"/api/v1/enrollments/{enrollment.pk}/change-class/", {"school_class": str(w.klass_b.pk)}, format="json"
            ),
            409,
        )["details"]["rule"]
        == "enrollment_closed"
    )
    body = data(admin.post(f"{url}archive/"))
    assert body["status"] == "ARCHIVED" and body["archived_at"]
    # An enrollment prepared for a year that has not started yet can be withdrawn too.
    later_year = academics.create_academic_year(
        w.school, name="2030-2031", start_date=date(2030, 9, 1), end_date=date(2031, 7, 31)
    )
    later_class = SchoolClassFactory(school=w.school, name="Futur", academic_year=later_year, level=w.klass.level)
    other = w.students[1]
    future = people.admin_enroll_student(other, later_class, actor=w.admin)
    assert future.enrollment_date == date(2030, 9, 1)  # kept inside its year
    early = error(
        admin.post(f"/api/v1/enrollments/{future.pk}/withdraw/", {"end_date": "2030-08-01"}, format="json"), 400
    )
    assert early["details"]["rule"] == "withdraw_before_enrollment"
    body = data(admin.post(f"/api/v1/enrollments/{future.pk}/withdraw/"))
    assert (body["status"], body["end_date"]) == ("WITHDRAWN", "2030-09-01")
    assert error(admin.patch(url, {"first_name": "X"}, format="json"), 400)["details"]["rule"] == "student_archived"
    assert (
        error(admin.post(f"{url}enrollments/", {"school_class": str(w.klass_b.pk)}, format="json"), 400)["details"][
            "rule"
        ]
        == "student_not_active"
    )
    assert [r["id"] for r in data(admin.get(f"{STUDENTS}?status=ARCHIVED"))] == [str(student.pk)]
    body = data(admin.post(f"{url}reactivate/"))
    assert (body["status"], body["archived_at"]) == ("ACTIVE", None)
    actions = [h["action"] for h in data(admin.get(f"{url}history/"))]
    assert actions[:3] == ["STUDENT_REACTIVATED", "STUDENT_ARCHIVED", "STUDENT_WITHDRAWN"]


def test_history_is_protected_for_students_with_grades_attendance_and_qr(w):
    """Archiving keeps every historical row; nothing can delete a student."""
    student = w.students[0]
    grade = w.grade(w.assess(), student, 15)
    qr = att.issue_qr_code(student, actor=w.admin)  # a newly enrolled student gets the annual QR as before
    day = StudentDailyAttendance.objects.create(
        school=w.school, student=student, academic_year=w.year, date=date(2026, 3, 2), status="ABSENT"
    )
    people.admin_withdraw_enrollment(student.enrollments.get(), actor=w.admin)
    people.admin_archive_student(student, actor=w.admin)
    for row in (grade, qr, day):
        row.refresh_from_db()  # still there, unchanged
    assert student.enrollments.get().status == EnrollmentStatus.WITHDRAWN
    assert grade.score == Decimal("15") and qr.student_id == student.pk
    with pytest.raises(HardDeleteForbidden):
        student.delete()
    with pytest.raises(HardDeleteForbidden):
        Student.objects.filter(pk=student.pk).delete()
    with pytest.raises(IntegrityError), transaction.atomic():  # PROTECT at the database level too
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM people_student WHERE id = %s", [student.pk])


def test_new_student_gets_qr_and_card_with_photo(w):
    admin = as_(w.admin)
    body = data(admin.post(STUDENTS, identity(enrollment={"school_class": str(w.klass_b.pk)}), format="json"), 201)
    student = Student.objects.get(pk=body["id"])
    data(admin.post(f"{STUDENTS}{student.pk}/photo/", {"photo": picture()}, format="multipart"))
    student.refresh_from_db()
    qr = att.issue_qr_code(student, actor=w.admin)
    card, _ = docs.generate("STUDENT_CARD", student, actor=w.admin)
    assert card.content["photo"] == student.photo.name and dict(card.content["fields"])["Classe"] == "3e B"
    assert card.content["qr"]["id"] == str(qr.pk)
    # Attendance and planning see the enrollment like any other.
    assert att._enrolled(student, w.year)


# =============================================================================
# Photo
# =============================================================================


def test_photo_upload_normalised_private_and_validated(w):
    admin = as_(w.admin)
    student = w.students[0]
    url = f"{STUDENTS}{student.pk}/photo/"
    assert admin.get(url).status_code == 404  # no photo yet
    body = data(admin.post(url, {"photo": picture("JPEG", (3000, 2000), exif=True)}, format="multipart"))
    assert body["has_photo"] is True
    student.refresh_from_db()
    assert student.photo.name.startswith("students/photos/") and student.photo.name.endswith(".jpg")
    assert "photo" not in student.photo.name.rsplit("/", 1)[-1]  # random name, not the client's
    stored = Image.open(student.photo.open("rb"))
    assert stored.format == "JPEG" and max(stored.size) == 800 and not stored.getexif()  # EXIF (GPS…) dropped
    response = admin.get(url)
    assert response.status_code == 200 and response["Content-Type"] == "image/jpeg"
    assert response["Cache-Control"] == "private, no-store"
    fake = SimpleUploadedFile("photo.jpg", b"not an image at all", content_type="image/jpeg")
    assert error(admin.post(url, {"photo": fake}, format="multipart"), 400)["details"]["rule"] == "photo_invalid"
    gif = picture("GIF")
    assert error(admin.post(url, {"photo": gif}, format="multipart"), 400)["details"]["rule"] == "photo_format"
    tiny = picture("PNG", (60, 60))
    assert error(admin.post(url, {"photo": tiny}, format="multipart"), 400)["details"]["rule"] == "photo_too_small"
    big = SimpleUploadedFile("big.jpg", b"0" * (3 * 1024 * 1024 + 1), content_type="image/jpeg")
    assert error(admin.post(url, {"photo": big}, format="multipart"), 400)["details"]["rule"] == "photo_too_large"
    assert data(admin.delete(url))["has_photo"] is False
    assert AuditLog.objects.filter(action="STUDENT_PHOTO_SET", entity_id=student.pk).exists()


# =============================================================================
# Isolation and permissions
# =============================================================================


def test_cross_school_isolation(w):
    other = SchoolFactory(code="OTHER9")
    foreign = StudentFactory(school=other)
    foreign_admin = member_with_role(other, "ADMIN")
    foreign_level = LevelFactory(school=other)
    foreign_year = academics.create_academic_year(
        other, name="2025-2026", start_date=date(2025, 9, 1), end_date=date(2026, 7, 31)
    )
    foreign_class = SchoolClassFactory(school=other, name="X", academic_year=foreign_year, level=foreign_level)
    admin = as_(w.admin)
    assert str(foreign.pk) not in {r["id"] for r in data(admin.get(STUDENTS))}
    for method, url, payload in (
        ("get", f"{STUDENTS}{foreign.pk}/", None),
        ("patch", f"{STUDENTS}{foreign.pk}/", {"first_name": "x"}),
        ("post", f"{STUDENTS}{foreign.pk}/archive/", None),
        ("post", f"{STUDENTS}{foreign.pk}/enrollments/", {"school_class": str(w.klass.pk)}),
        ("get", f"{STUDENTS}{foreign.pk}/photo/", None),
        ("get", f"{STUDENTS}{foreign.pk}/history/", None),
        # our student, another school's class: 404 as well
        ("post", f"{STUDENTS}{w.students[0].pk}/enrollments/", {"school_class": str(foreign_class.pk)}),
        (
            "post",
            f"/api/v1/enrollments/{w.students[0].enrollments.get().pk}/change-class/",
            {"school_class": str(foreign_class.pk)},
        ),
    ):
        response = getattr(admin, method)(url, payload, format="json")
        assert response.status_code == 404, (method, url)
    # The services refuse it too (not only the school-scoped lookups).
    with pytest.raises(PermissionDenied):
        people.admin_update_student(w.students[0], actor=foreign_admin, first_name="x")
    with pytest.raises(ValidationError) as exc:
        people.admin_change_class(w.students[0].enrollments.get(), foreign_class, actor=w.admin)
    assert exc.value.code == "class_other_school"
    with pytest.raises(ValidationError) as exc:
        people.admin_enroll_student(StudentFactory(school=w.school), foreign_class, actor=w.admin)
    assert exc.value.code == "class_other_school"


def test_permissions(w):
    teacher = as_(w.tm_member)
    student = w.students[0]
    assert error(teacher.post(STUDENTS, identity(), format="json"), 403)
    enrollment = student.enrollments.get()
    for url, payload in (
        (f"/api/v1/enrollments/{enrollment.pk}/change-class/", {"school_class": str(w.klass_b.pk)}),
        (f"/api/v1/enrollments/{enrollment.pk}/withdraw/", {}),
    ):
        assert teacher.post(url, payload, format="json").status_code in (403, 404)
    visible = {r["id"] for r in data(teacher.get(STUDENTS))}
    assert str(student.pk) in visible  # the class teacher sees the pupil (scope unchanged)…
    # …but cannot change anything
    for _ in (1,):
        assert error(teacher.patch(f"{STUDENTS}{student.pk}/", {"first_name": "x"}, format="json"), 403)
        assert error(teacher.post(f"{STUDENTS}{student.pk}/archive/"), 403)
        assert error(teacher.get(f"{STUDENTS}{student.pk}/history/"), 403)
        assert "address" not in data(teacher.get(f"{STUDENTS}{student.pk}/"))  # admin fields stay private
    staff = member_with_role(w.school, "STAFF")
    assert as_(staff).get(f"{STUDENTS}{student.pk}/").status_code == 404
    with pytest.raises(PermissionDenied):
        people.admin_enroll_student(student, w.klass_b, actor=w.tm_member)
    with pytest.raises(PermissionDenied):
        people.admin_change_class(enrollment, w.klass_b, actor=w.tm_member)
    with pytest.raises(PermissionDenied):
        people.admin_create_student(w.school, actor=w.tm_member, **{**identity(), "date_of_birth": date(2012, 5, 4)})
    assert StudentStatus.ACTIVE == Student.objects.get(pk=student.pk).status

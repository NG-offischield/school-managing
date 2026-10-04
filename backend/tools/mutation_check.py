"""Mutation check of the administration verticals (ADR 0018 to ADR 0020).

Each mutation removes ONE protection from the code (school filtering,
year/class control, permission check, compatibility control), runs the
tests of the suite, and expects them to FAIL ("killed"). A mutation that
survives means the tests do not protect that rule. The source file is
always restored.

    docker compose run --rm -T web python tools/mutation_check.py students
    docker compose run --rm -T web python tools/mutation_check.py teachers
    docker compose run --rm -T web python tools/mutation_check.py courses

Exit code 0 only if every mutation is killed.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STUDENTS = [
    (
        "school filter: class looked up outside the current school",
        "apps/people/student_api.py",
        'scope_to_current_school(SchoolClass.objects.select_related("academic_year", "level"), request)',
        'SchoolClass.objects.select_related("academic_year", "level")',
    ),
    (
        "school filter: student looked up outside the current school",
        "apps/people/student_api.py",
        "student = self.restrict(scope_to_current_school(Student.objects.all(), self.request)).filter(",
        "student = self.restrict(Student.objects.all()).filter(",
    ),
    (
        "school filter: service accepts a class of another school",
        "apps/people/services.py",
        "    if school_class.school_id != student.school_id:\n",
        "    if False:\n",
    ),
    (
        "year/class: class change to a class of another year",
        "apps/people/services.py",
        "    if school_class.academic_year_id != enrollment.academic_year_id:\n",
        "    if False:\n",
    ),
    (
        "year/class: second enrollment in the same year",
        "apps/people/services.py",
        "    if StudentEnrollment.objects.filter(student=student, academic_year=year).exists():\n",
        "    if False:\n",
    ),
    (
        "year/class: enrollment date outside the year",
        "apps/people/services.py",
        "    if enrollment_date is not None and not year.start_date <= enrollment_date <= year.end_date:\n",
        "    if False:\n",
    ),
    (
        "permission: anyone may create a student",
        "apps/people/services.py",
        '(both or nothing)."""\n    require_role(actor, ADMIN_ROLES, school=school)\n',
        '(both or nothing)."""\n',
    ),
    (
        "permission: anyone may change a class",
        "apps/people/services.py",
        '(history); the student follows the new class from now on."""\n'
        "    require_role(actor, ADMIN_ROLES, school=enrollment.school)\n",
        '(history); the student follows the new class from now on."""\n',
    ),
    (
        "permission: student history readable by any member who sees the student",
        "apps/people/student_api.py",
        "        if not self.is_admin():\n            raise PermissionDenied\n",
        "",
    ),
]

TEACHERS = [
    (
        "school filter: subject / category / level looked up outside the current school",
        "apps/people/teacher_api.py",
        "    found = scope_to_current_school(model.objects.all(), request).filter(pk=pk).first()\n",
        "    found = model.objects.all().filter(pk=pk).first()\n",
    ),
    (
        "school filter: teacher looked up outside the current school",
        "apps/people/teacher_api.py",
        "            self.visible_teachers(scope_to_current_school(TeacherProfile.objects.all(), self.request))\n",
        "            self.visible_teachers(TeacherProfile.objects.all())\n",
    ),
    (
        "school filter: service accepts a subject of another school",
        "apps/people/services.py",
        "    if subject.school_id != school.pk:\n"
        '        raise ValidationError("The subject belongs to another school."',
        '    if False:\n        raise ValidationError("The subject belongs to another school."',
    ),
    (
        "permission: anyone may add a qualification",
        "apps/people/services.py",
        'A previously rejected qualification is re-evaluated."""\n'
        "    require_role(actor, ADMIN_ROLES, school=teacher.school)\n",
        'A previously rejected qualification is re-evaluated."""\n',
    ),
    (
        "permission: another school's admin may update a teacher",
        "apps/people/services.py",
        '"active" state (status change) follows the same rule as deactivation."""\n'
        "    require_role(actor, ADMIN_ROLES, school=teacher.school)\n",
        '"active" state (status change) follows the same rule as deactivation."""\n',
    ),
    (
        "permission: any member may read the compatibility verdict",
        "apps/people/teacher_api.py",
        "    def require_admin(self):\n        if not self.is_admin():\n            raise PermissionDenied\n",
        "    def require_admin(self):\n        return None\n",
    ),
    (
        "compatibility: an incompatible declaration is stored anyway",
        "apps/people/services.py",
        "    evaluation = evaluate(teacher, subject, level)\n"
        "    if evaluation.result == CompatibilityResult.INCOMPATIBLE:\n        raise IncompatibleSubject(",
        "    evaluation = evaluate(teacher, subject, level)\n    if False:\n        raise IncompatibleSubject(",
    ),
    (
        "compatibility: an incompatible rule is read as compatible",
        "apps/people/compatibility.py",
        "        else:\n            result = CompatibilityResult.INCOMPATIBLE\n",
        "        else:\n            result = CompatibilityResult.COMPATIBLE\n",
    ),
    (
        "compatibility: the primary subject is not judged at creation",
        "apps/people/services.py",
        "    declare_qualification(teacher, primary_subject)\n    return teacher\n",
        "    return teacher\n",
    ),
]

COURSES = [
    (
        "school filter: class / subject / teacher / scale looked up outside the current school",
        "apps/gradebook/course_api.py",
        "    found = scope_to_current_school(model.objects.all(), request).filter(pk=pk).first()\n",
        "    found = model.objects.all().filter(pk=pk).first()\n",
    ),
    (
        "school filter: course looked up outside the current school",
        "apps/gradebook/course_api.py",
        "found = self.visible(scope_to_current_school(Course.objects.all(), self.request)).filter(",
        "found = self.visible(Course.objects.all()).filter(",
    ),
    (
        "school filter: service accepts a teacher of another school",
        "apps/gradebook/services.py",
        '    if teacher.school_id != school_class.school_id:\n        return "teacher_other_school"\n',
        '    if False:\n        return "teacher_other_school"\n',
    ),
    (
        "compatibility: an incompatible verdict is ignored",
        "apps/gradebook/services.py",
        '    if verdict == CompatibilityResult.INCOMPATIBLE:\n        return "incompatible_subject"\n',
        '    if False:\n        return "incompatible_subject"\n',
    ),
    (
        "compatibility: the teacher is not checked at all",
        "apps/gradebook/services.py",
        "    _check_course_frame(school_class, subject)\n    _check_teacher(teacher, subject, school_class)\n",
        "    _check_course_frame(school_class, subject)\n",
    ),
    (
        "year: a course can be created in a closed year",
        "apps/gradebook/services.py",
        "    if school_class.academic_year.status not in OPEN_YEARS:\n",
        "    if False:\n",
    ),
    (
        "year: a course of a closed year can be modified",
        "apps/gradebook/services.py",
        "    if course.academic_year.status not in OPEN_YEARS:\n",
        "    if False:\n",
    ),
]

SUITES = {
    "students": (["tests/test_students_admin_api.py"], STUDENTS),
    "teachers": (["tests/test_teachers_admin_api.py"], TEACHERS),
    "courses": (["tests/test_courses_admin_api.py"], COURSES),
}


def run_tests(tests):
    return subprocess.run(  # noqa: S603 — fixed argument list, no external input
        [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *tests],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).returncode


def main(name):
    tests, mutations = SUITES[name]
    if run_tests(tests) != 0:
        print("The tests fail WITHOUT mutation: fix them first.")
        return 2
    survivors = 0
    for label, relative, original, mutated in mutations:
        path = ROOT / relative
        source = path.read_text(encoding="utf-8")
        if source.count(original) != 1:
            print(f"[ERROR ] {label}: target not found exactly once in {relative}")
            survivors += 1
            continue
        try:
            path.write_text(source.replace(original, mutated), encoding="utf-8")
            killed = run_tests(tests) != 0
        finally:
            path.write_text(source, encoding="utf-8")  # always restored
        survivors += 0 if killed else 1
        print(f"[{'KILLED' if killed else 'SURVIVED'}] {label}")
    print(f"{len(mutations) - survivors}/{len(mutations)} mutations killed")
    return 0 if survivors == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in SUITES:
        sys.exit(f"usage: mutation_check.py {'|'.join(SUITES)}")
    sys.exit(main(sys.argv[1]))

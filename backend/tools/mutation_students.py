"""Mutation check of the students administration (ADR 0018).

Each mutation removes ONE protection from the code (school filtering,
year/class control, permission check), runs the students tests, and expects
them to FAIL ("killed"). A mutation that survives means the tests do not
protect that rule. The source file is always restored.

    docker compose run --rm -T web python tools/mutation_students.py

Exit code 0 only if every mutation is killed.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ["tests/test_students_admin_api.py"]

MUTATIONS = [
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


def run_tests():
    return subprocess.run(  # noqa: S603 — fixed argument list, no external input
        [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *TESTS],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).returncode


def main():
    if run_tests() != 0:
        print("The tests fail WITHOUT mutation: fix them first.")
        return 2
    survivors = 0
    for label, relative, original, mutated in MUTATIONS:
        path = ROOT / relative
        source = path.read_text(encoding="utf-8")
        if source.count(original) != 1:
            print(f"[ERROR ] {label}: target not found exactly once in {relative}")
            survivors += 1
            continue
        try:
            path.write_text(source.replace(original, mutated), encoding="utf-8")
            killed = run_tests() != 0
        finally:
            path.write_text(source, encoding="utf-8")  # always restored
        survivors += 0 if killed else 1
        print(f"[{'KILLED' if killed else 'SURVIVED'}] {label}")
    print(f"{len(MUTATIONS) - survivors}/{len(MUTATIONS)} mutations killed")
    return 0 if survivors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

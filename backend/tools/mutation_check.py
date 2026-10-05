"""Mutation check of the administration verticals (ADR 0018 to ADR 0020) and of
the account activation (ADR 0024), the parent workflow (ADR 0026) and the guardian / staff apps (ADR 0027).

Each mutation removes ONE protection from the code (school filtering,
year/class control, permission check, compatibility control), runs the
tests of the suite, and expects them to FAIL ("killed"). A mutation that
survives means the tests do not protect that rule. The source file is
always restored.

    docker compose run --rm -T web python tools/mutation_check.py students
    docker compose run --rm -T web python tools/mutation_check.py teachers
    docker compose run --rm -T web python tools/mutation_check.py courses
    docker compose run --rm -T web python tools/mutation_check.py activation
    docker compose run --rm -T web python tools/mutation_check.py parents
    docker compose run --rm -T web python tools/mutation_check.py field

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

ACTIVATION = [
    (
        "token check: any code matches an activation",
        "apps/accounts/activation.py",
        "    activation = queryset.filter(code_hash=code_hash(code)).first()\n",
        "    activation = queryset.first()\n",
    ),
    (
        "school isolation: a member of another school is reachable by its id",
        "apps/accounts/activation_api.py",
        'queryset = scope_to_current_school(SchoolMembership.objects.select_related("user", "school"), self.request)',
        'queryset = SchoolMembership.objects.select_related("user", "school")',
    ),
    (
        "school isolation: the service accepts an administrator of another school",
        "apps/accounts/activation.py",
        "    if actor is None or actor.school_id != school.pk or not (actor.role_codes() & ADMIN_ROLES):\n",
        "    if actor is None or not (actor.role_codes() & ADMIN_ROLES):\n",
    ),
    (
        "single use: a used code is accepted again",
        "apps/accounts/activation.py",
        '    if activation.used_at is not None:\n        _reject("ALREADY_USED", ctx, activation)\n',
        '    if False:\n        _reject("ALREADY_USED", ctx, activation)\n',
    ),
    (
        "expiry: an expired code is accepted",
        "apps/accounts/activation.py",
        '    if activation.expires_at <= timezone.now():\n        _reject("EXPIRED", ctx, activation)\n',
        '    if False:\n        _reject("EXPIRED", ctx, activation)\n',
    ),
    (
        "revocation: a revoked code is accepted",
        "apps/accounts/activation.py",
        '    if activation.revoked_at is not None:\n        _reject("REVOKED", ctx, activation)\n',
        '    if False:\n        _reject("REVOKED", ctx, activation)\n',
    ),
    (
        "disabled account: its code can still be used",
        "apps/accounts/activation.py",
        '    if is_disabled(membership):\n        _reject("ACCOUNT_DISABLED", ctx, activation)\n',
        '    if False:\n        _reject("ACCOUNT_DISABLED", ctx, activation)\n',
    ),
]

PARENTS = [
    # --- parent / child filter -------------------------------------------------
    (
        "parent/child filter: /parents/children/ lists every verified link of the school",
        "apps/people/api.py",
        "queryset.filter(parent__membership=self.membership(), active=True, identity_verified=True)",
        "queryset.filter(active=True, identity_verified=True)",
    ),
    (
        "parent/child filter: student visibility (attendance, ...) ignores the parent",
        "apps/people/api.py",
        "                parent_links__parent__membership=membership,\n",
        "",
    ),
    (
        "parent/child filter: child endpoints of the parent app ignore the parent",
        "apps/people/parent_workflow_api.py",
        "            parent_links__parent__membership=self.membership(),\n",
        "",
    ),
    (
        "parent/child filter: scans of any child of the school",
        "apps/attendance/api.py",
        "                parent_links__parent__membership=self.membership(),\n",
        "",
    ),
    # --- verification ----------------------------------------------------------
    (
        "verification: declared (unverified) links listed as children",
        "apps/people/api.py",
        "queryset.filter(parent__membership=self.membership(), active=True, identity_verified=True)",
        "queryset.filter(parent__membership=self.membership(), active=True)",
    ),
    (
        "verification: student visibility through an unverified link",
        "apps/people/api.py",
        "                parent_links__identity_verified=True,\n",
        "",
    ),
    (
        "verification: link approved without a verified identity",
        "apps/people/parent_workflow.py",
        "    if identity.status != IdentityStatus.VERIFIED:\n",
        "    if False:\n",
    ),
    (
        "verification: link approved without the pupil's designation",
        "apps/people/parent_workflow.py",
        "    if request.student_approval_status not in (StudentApproval.APPROVED, StudentApproval.NOT_REQUIRED):\n",
        "    if False:\n",
    ),
    (
        "verification: any document number accepted",
        "apps/people/parent_workflow.py",
        "        if matches:\n",
        "        if True:\n",
    ),
    (
        "verification: an unverified parent issues sponsor codes",
        "apps/people/parent_workflow.py",
        "    if student.school_id != membership.school_id or _verified_link(parent, student) is None:\n",
        "    if student.school_id != membership.school_id:\n",
    ),
    (
        "verification: sponsored parent gets more rights than the sponsor",
        "apps/people/parent_workflow.py",
        '        ):\n            raise ValidationError(\n                "A sponsored parent',
        '        ) and False:\n            raise ValidationError(\n                "A sponsored parent',
    ),
    (
        "verification: sponsored parent may pay although the sponsor may not",
        "apps/people/parent_workflow.py",
        "        if (can_pay and not sponsor_link.can_pay) or (\n",
        "        if (False) or (\n",
    ),
    # --- school isolation ------------------------------------------------------
    (
        "school isolation: link request to a pupil of another school",
        "apps/people/parent_workflow.py",
        "    student = Student.objects.filter(\n        school=membership.school,\n",
        "    student = Student.objects.filter(\n",
    ),
    (
        "school isolation: admin reads link requests of another school",
        "apps/people/parent_workflow_api.py",
        "get_object_or_404(scope_to_current_school(ParentStudentLinkRequest.objects.all(), self.request), pk=pk)",
        "get_object_or_404(ParentStudentLinkRequest.objects.all(), pk=pk)",
    ),
    (
        "school isolation: admin reads registrations of another school",
        "apps/people/parent_workflow_api.py",
        "get_object_or_404(scope_to_current_school(RegistrationRequest.objects.all(), self.request), pk=pk)",
        "get_object_or_404(RegistrationRequest.objects.all(), pk=pk)",
    ),
]

FIELD = [
    # --- isolation (guardian / staff apps, ADR 0027) ---------------------------
    (
        "isolation: a guardian sees every scan of the school",
        "apps/attendance/api.py",
        "        queryset = queryset.filter(scanned_by=self.membership())\n",
        "",
    ),
    (
        "isolation: a staff member sees the whole staff list",
        "apps/people/api.py",
        "    def restrict(self, queryset):\n        if self.is_admin():\n            return queryset\n"
        "        return queryset.filter(employee__membership=self.membership())\n",
        "    def restrict(self, queryset):\n        return queryset\n",
    ),
    (
        "isolation: payroll/me returns colleagues' payrolls",
        "apps/payroll/api.py",
        "            return Q(school=membership.school, status__in=VISIBLE_TO_EMPLOYEE, **{owner: membership})",
        "            return Q(school=membership.school, status__in=VISIBLE_TO_EMPLOYEE)",
    ),
    (
        "school isolation: tenant scoping of every read endpoint removed",
        "common/views.py",
        "        return self.restrict(scope_to_current_school(self.queryset.all(), self.request))",
        "        return self.restrict(self.queryset.all())",
    ),
    # --- permissions -----------------------------------------------------------
    (
        "permission: staff see the pupils' solvency at the gate",
        "apps/attendance/api.py",
        'SOLVENCY_VIEWER_ROLES = frozenset({"GUARDIAN", *ADMIN_ROLES})',
        'SOLVENCY_VIEWER_ROLES = frozenset({"GUARDIAN", "STAFF", *ADMIN_ROLES})',
    ),
    (
        "permission: any member may scan QR codes",
        "apps/attendance/services.py",
        "    if not membership_has_role(actor, SCANNER_ROLES):\n",
        "    if False:\n",
    ),
    (
        "permission: an inactive guardian may still scan",
        "apps/attendance/services.py",
        '    if guardian is not None and guardian.status != "ACTIVE":\n',
        "    if False:\n",
    ),
    (
        "permission: guardians may use messaging (spec §8)",
        "apps/communication/access.py",
        'MESSAGING_ROLES = frozenset({"TEACHER", "PARENT", "STAFF", *ADMIN_ROLES})',
        'MESSAGING_ROLES = frozenset({"TEACHER", "PARENT", "STAFF", "GUARDIAN", *ADMIN_ROLES})',
    ),
]

SUITES = {
    "students": (["tests/test_students_admin_api.py"], STUDENTS),
    "teachers": (["tests/test_teachers_admin_api.py"], TEACHERS),
    "courses": (["tests/test_courses_admin_api.py"], COURSES),
    "activation": (["tests/test_account_activation.py"], ACTIVATION),
    "parents": (["tests/test_parent_workflow.py"], PARENTS),
    "field": (["tests/test_guardian_staff_api.py"], FIELD),
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

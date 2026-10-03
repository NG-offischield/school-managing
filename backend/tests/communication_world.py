"""Communication test world, built on the payroll world (planning, finance,
payroll): class 3e A (maths by tm, french by tf), pupils s0..s2.

- `parent`: verified parent of s0 (notifications and complaints allowed);
- `other_parent`: verified parent of s1 only;
- `unverified`: declared (NOT verified) parent of s0;
- `outsider_teacher`: a teacher with no course in 3e A;
- `guardian`, the staff member of the payroll world.
"""

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.people import services as people
from apps.people.models import VerificationMethod

from .factories import ParentFactory, make_teacher, member_with_role
from .payroll_world import make_payroll_world


def verified_parent(w, student, **rights):
    parent = ParentFactory(school=w.school)
    link = people.link_parent(parent, student, relationship_type="MOTHER")
    people.verify_parent_link(link, actor=w.admin, method=VerificationMethod.ADMIN_IN_PERSON)
    for key, value in rights.items():
        setattr(link, key, value)
    link.save()
    return parent.membership


def make_communication_world(school):
    w = make_payroll_world(school)
    w.parent = verified_parent(w, w.students[0])
    w.other_parent = verified_parent(w, w.students[1])
    declared = ParentFactory(school=school)
    people.link_parent(declared, w.students[0], relationship_type="FATHER")
    w.unverified = declared.membership
    w.outsider_teacher = make_teacher(school).employee.membership
    w.maths_substitute = make_teacher(school, category=w.maths.category, primary_subject=w.maths)
    w.guardian = member_with_role(school, "GUARDIAN")
    people.create_guardian(w.guardian, guardian_number="G-1")
    w.staff_member = w.staff.employee.membership
    return w


def png(name="photo.png", size=(4, 4)):
    buffer = io.BytesIO()
    Image.new("RGB", size, "red").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


def pdf(name="doc.pdf", body=b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"):
    return SimpleUploadedFile(name, body, content_type="application/pdf")


def fake(name="facture.pdf"):
    """An executable renamed .pdf with a lying content type."""
    return SimpleUploadedFile(name, b"MZ\x90\x00\x03\x00\x00\x00" + b"\x00" * 64, content_type="application/pdf")

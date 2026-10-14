"""Shared fixtures of the ISBREE web tests (ADR 0032): a complete school (the
communication world: admin, verified / declared parents, teachers, guardian,
staff) + editorial content of every audience, + helpers."""

import io
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
from rest_framework.test import APIClient

from apps.accounts.models import MembershipRole, Role, RoleCode
from apps.website import services as web
from apps.website.models import PublicationStatus

from .communication_world import make_communication_world
from .factories import member_with_role

PUBLISHED = PublicationStatus.PUBLISHED


def client(member=None, **headers):
    api = APIClient(**headers)
    if member is not None:
        api.force_authenticate(member.user)
    return api


def data(response, expected=200):
    assert response.status_code == expected, response.content[:500]
    return response.json()["data"]


def jpeg(name="photo.jpg", size=(64, 48)):
    """A JPEG with EXIF author / description tags: they must not survive."""
    image = Image.new("RGB", size, (30, 60, 90))
    exif = image.getexif()
    exif[0x013B] = "Photographer"  # Artist
    exif[0x010E] = "Secret place"  # ImageDescription
    out = io.BytesIO()
    image.save(out, format="JPEG", exif=exif.tobytes())
    return SimpleUploadedFile(name, out.getvalue(), content_type="image/jpeg")


def pdf(name="liste.pdf"):
    from pypdf import PdfWriter

    writer, out = PdfWriter(), io.BytesIO()
    writer.add_blank_page(width=595, height=842)
    writer.write(out)
    return SimpleUploadedFile(name, out.getvalue(), content_type="application/pdf")


MANIFEST = bytes([3, 0, 8, 0]) + b"manifest"
DEX = b"dex" + bytes([10]) + b"035" + bytes([0])


def apk(name="app.apk", *, certificate=b"CN=ISBREE Release, O=ISBREE", block=None, signed=True):
    """A minimal APK-shaped zip: manifest, dex, and (optionally) a v1
    certificate and / or a v2 APK Signing Block holding `block` bytes,
    inserted before the central directory like apksigner does (the
    end-of-central-directory offset is moved accordingly)."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        archive.writestr("AndroidManifest.xml", MANIFEST)
        archive.writestr("classes.dex", DEX)
        if signed and certificate is not None:
            archive.writestr("META-INF/CERT.RSA", bytes([0x30, 0x82]) + certificate)
    data = out.getvalue()
    if block is not None:
        eocd = data.rfind(b"PK" + bytes([5, 6]))
        cd_offset = int.from_bytes(data[eocd + 16 : eocd + 20], "little")
        payload = block + bytes(8)
        size = len(payload) + 8 + 16
        signing = size.to_bytes(8, "little") + payload + size.to_bytes(8, "little") + b"APK Sig Block 42"
        data = data[:cd_offset] + signing + data[cd_offset:]
        eocd += len(signing)
        data = data[: eocd + 16] + (cd_offset + len(signing)).to_bytes(4, "little") + data[eocd + 20 :]
    return SimpleUploadedFile(name, data, content_type="application/vnd.android.package-archive")


def make_isbree_world(school):
    w = make_communication_world(school)
    w.school.phone, w.school.email = "+237698686729", "contact@ecole.test"
    w.school.save(update_fields=["phone", "email"])
    w.editor = member_with_role(school, RoleCode.CONTENT_MANAGER)
    MembershipRole.objects.get_or_create(membership=w.staff_member, role=Role.objects.get(code=RoleCode.STAFF))
    w.level = w.klass.level
    w.level.public_visible = True  # offered on the public site
    w.level.save(update_fields=["public_visible"])

    def content(table, /, **values):
        values.setdefault("status", PUBLISHED)
        return web.save_content(table, school, actor=w.admin, values=values)

    w.content = content
    w.public_page = content("pages", kind="ABOUT", title="À propos", body="Présentation", audiences=["PUBLIC"])
    w.teacher_page = content("pages", kind="TEACHING_POLICY", title="Politique", body="Interne", audiences=["TEACHER"])
    w.draft_page = content("pages", kind="OTHER", title="Brouillon", audiences=["PUBLIC"], status="DRAFT")
    w.public_faq = content("faq", category="ADMISSIONS", question="Comment ?", answer="Ainsi.", audiences=["PUBLIC"])
    w.parent_faq = content("faq", category="PORTAL", question="Parents ?", answer="Oui.", audiences=["PARENT"])
    w.public_news = content(
        "news", title="Rentrée", summary="La rentrée arrive.", body="Détails", audiences=["PUBLIC", "PARENT"]
    )
    w.staff_news = content("news", title="Note interne", summary="Réunion du personnel.", audiences=["STAFF"])
    # Role resources: general and scoped.
    w.class_supplies = content(
        "resources", kind="SUPPLIES", title="Fournitures 3e A", audiences=["PARENT"], school_class=w.klass
    )
    w.parent_general = content("resources", kind="PRACTICAL_INFO", title="Horaires", audiences=["PARENT"])
    w.teacher_programme = content(
        "resources", kind="PROGRAMME", title="Programme 3e", audiences=["TEACHER"], level=w.level
    )
    w.guardian_procedure = content("resources", kind="PROCEDURE", title="Accès au portail", audiences=["GUARDIAN"])
    return w

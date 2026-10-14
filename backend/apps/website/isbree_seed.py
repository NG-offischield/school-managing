"""Initial ISBREE content and demonstration accounts (ADR 0032).

`manage.py seed_isbree` (never with the production settings):

- the school ISBREE (provisioned like any school, ADR 0006) with the contact
  information the school gave: phone, e-mail (ISBREE_CONTACT_EMAIL, from the
  environment only), location "Etoug-Ebe, Yaoundé" — the exact street address
  stays UNCONFIRMED (never shown publicly until the school confirms it);
- a first version of every editorial content, ALL flagged `to_validate`:
  wording proposed for the school to correct, nothing presented as an
  official rule, fee, date, diploma or accreditation;
- with --demo: fictitious demonstration data, flagged `is_demo` or named
  "(démo)": two levels, a class, two locations ("Campus Horizon", "Annexe
  Les Manguiers"), demo news, and one account per portal role (parent with a
  VERIFIED child, teacher with a course and a weekly slot, staff with a
  function, gate guardian) whose password is ISBREE_DEMO_PASSWORD (never
  stored nor printed; reserved .test addresses);
- with --images DIR: the illustration images (re-encoded, EXIF removed),
  always flagged `is_illustration` (they do not show ISBREE).

Idempotent: every object is looked up first; nothing is deleted or rewritten
(an existing content keeps the school's edits).
"""

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone

from apps.academics import services as academics
from apps.academics.models import AcademicYear, AcademicYearStatus, Level, PedagogicalCategory, SchoolClass, Subject
from apps.accounts import activation
from apps.accounts.models import MembershipRole, MembershipStatus, Role, RoleCode, SchoolMembership, User
from apps.core.models import School
from apps.core.services import FirstAdmin, SchoolProvisioningService
from apps.gradebook import services as gradebook
from apps.gradebook.models import Course
from apps.people import parent_workflow
from apps.people import services as people
from apps.people.models import EmployeeType, ParentStudent, RegistrationRequest, StaffFunction, Student

from . import services as web
from .models import ContentImage, FaqEntry, NewsArticle, Page, RoleResource, SiteLocation, SiteProfile

CODE = "ISBREE"
DEMO_DOMAIN = "isbree.test"
PRODUCTION_SETTINGS = "config.settings.production"
DEFAULT_PHONE = "+237698686729"  # given by the school in the specification


@dataclass
class Seeded:
    school: School = None
    admin: SchoolMembership = None
    created: list = field(default_factory=list)


def _refuse_production():
    if settings.SETTINGS_MODULE == PRODUCTION_SETTINGS:
        raise ImproperlyConfigured("seed_isbree is never run with the production settings.")


def _password(password):
    if not password:
        raise ImproperlyConfigured(
            "ISBREE_DEMO_PASSWORD is required to create the accounts (never stored nor printed)."
        )
    return password


# =============================================================================
# Editorial first version — every text is flagged to_validate
# =============================================================================

PROVISIONAL = (
    "Texte provisoire proposé pour la première version du site : il doit être relu, complété et validé par "
    "l'établissement avant publication définitive."
)

PROFILE = {
    "tagline": "Apprendre, grandir et s'ouvrir au monde",
    "presentation": (
        "ISBREE accueille ses élèves à Etoug-Ebe, à Yaoundé. L'établissement accompagne chaque enfant dans ses "
        "apprentissages et dans sa vie d'élève, en lien étroit avec les familles."
    ),
    "values": "Respect\nRigueur\nBienveillance\nOuverture\nResponsabilité",
    "pedagogy": (
        "Un suivi attentif de chaque élève, des apprentissages structurés et une communication régulière avec "
        "les familles. Les modalités précises seront présentées par l'établissement."
    ),
    "location_details": "Etoug-Ebe, Yaoundé",
    "office_hours": "",
}

PAGES = [
    (
        "ABOUT",
        "a-propos",
        "À propos d'ISBREE",
        "Qui nous sommes et ce qui guide notre action.",
        f"## Présentation\n{PROFILE['presentation']}\n\n## Notre mission\nAccompagner chaque élève vers la "
        "réussite et l'autonomie, dans un cadre exigeant et bienveillant.\n\n## Notre vision\nUne école ouverte, "
        f"où chacun trouve sa place et développe ses talents.\n\n{PROVISIONAL}",
        ["PUBLIC", "PARENT", "TEACHER", "STAFF", "GUARDIAN"],
    ),
    (
        "PEDAGOGY",
        "approche-pedagogique",
        "Notre approche pédagogique",
        "Comment nous accompagnons les apprentissages.",
        f"{PROFILE['pedagogy']}\n\n## Ce que nous privilégions\n- Le suivi individuel des élèves\n- Le travail "
        f"régulier et la méthode\n- Le dialogue avec les familles\n\n{PROVISIONAL}",
        ["PUBLIC", "PARENT", "TEACHER"],
    ),
    (
        "SCHOOL_LIFE",
        "vie-scolaire",
        "La vie scolaire",
        "Activités, événements et vie de l'établissement.",
        "La vie scolaire rassemble les activités, les événements et les temps forts de l'année. Les actualités et la "
        f"galerie présentent ce que l'établissement choisit de partager.\n\n{PROVISIONAL}",
        ["PUBLIC", "PARENT"],
    ),
    (
        "ADMISSIONS",
        "admissions",
        "Admissions et préinscription",
        "Les étapes pour demander une place à ISBREE.",
        "## Les étapes\n- Vous remplissez le formulaire de préinscription en ligne.\n- L'établissement examine votre "
        "demande et peut vous demander des informations complémentaires.\n- Vous êtes informé de la décision.\n- Si la "
        "demande est acceptée, vous recevez une invitation pour activer votre Espace ISBREE.\n\n## À savoir\nUne "
        "préinscription acceptée n'est pas une inscription définitive : l'inscription est finalisée avec "
        "l'établissement. La liste des documents à fournir, le calendrier et les éventuels frais vous sont "
        f"communiqués par l'établissement.\n\n{PROVISIONAL}",
        ["PUBLIC", "PARENT"],
    ),
    (
        "TEACHING_POLICY",
        "politique-enseignement",
        "Principes d'enseignement",
        "Repères pour l'équipe enseignante.",
        "Cette page réunira les principes pédagogiques, l'organisation des apprentissages et les consignes "
        f"professionnelles définis par l'établissement.\n\n{PROVISIONAL}",
        ["TEACHER"],
    ),
    (
        "PRACTICAL",
        "informations-pratiques",
        "Informations pratiques",
        "Horaires, contacts et repères utiles.",
        "Les horaires, l'organisation des entrées et sorties et les contacts utiles seront précisés ici par "
        f"l'établissement.\n\n{PROVISIONAL}",
        ["PARENT", "TEACHER", "STAFF", "GUARDIAN"],
    ),
    (
        "LEGAL_NOTICE",
        "mentions-legales",
        "Mentions légales",
        "Éditeur du site et hébergement.",
        "## Éditeur\nISBREE — Etoug-Ebe, Yaoundé (Cameroun).\nStatut juridique, numéro d'enregistrement et "
        "responsable de la publication : [à compléter par l'établissement].\n\n## Contact\nTéléphone : +237 698 686 "
        "729.\n\n## Hébergement\n[À compléter lors de la mise en production.]\n\n"
        f"{PROVISIONAL}",
        ["PUBLIC"],
    ),
    (
        "PRIVACY",
        "confidentialite",
        "Politique de confidentialité",
        "Quelles données nous recueillons et pourquoi.",
        "## Données recueillies\nLors d'une préinscription : les nom, prénom, téléphone et e-mail du responsable, "
        "son lien avec l'enfant, les nom et prénom de l'enfant, éventuellement sa date de naissance et son "
        "établissement précédent, le niveau et l'année souhaités et votre commentaire.\n\n## Utilisation\nCes "
        "données servent uniquement à examiner la demande et à vous recontacter. Elles ne sont ni vendues ni "
        "utilisées à des fins publicitaires.\n\n## Accès\nSeule l'administration de l'établissement y accède.\n\n"
        "## Durée de conservation\n[À définir par l'établissement.]\n\n## Vos droits\nVous pouvez demander l'accès, "
        "la rectification ou la suppression de vos données en contactant l'établissement.\n\n## Cookies\nLe site "
        "public n'utilise aucun cookie de suivi ni de publicité. L'Espace ISBREE utilise uniquement le cookie "
        f"nécessaire à la connexion.\n\n{PROVISIONAL}",
        ["PUBLIC", "PARENT", "TEACHER", "STAFF", "GUARDIAN"],
    ),
    (
        "TERMS",
        "conditions-utilisation",
        "Conditions d'utilisation",
        "Règles d'usage du site et de l'Espace ISBREE.",
        "L'Espace ISBREE est réservé aux personnes disposant d'un compte remis par l'établissement. Chaque "
        "utilisateur est responsable de la confidentialité de son mot de passe. Les informations scolaires "
        f"consultées sont personnelles et ne doivent pas être diffusées.\n\n{PROVISIONAL}",
        ["PUBLIC", "PARENT", "TEACHER", "STAFF", "GUARDIAN"],
    ),
    (
        "RULES",
        "reglement",
        "Règlement intérieur",
        "Le règlement applicable à l'établissement.",
        "Le règlement intérieur sera publié ici lorsque l'établissement aura transmis le document officiel.\n\n"
        f"{PROVISIONAL}",
        ["PUBLIC", "PARENT", "TEACHER", "STAFF", "GUARDIAN"],
    ),
]

FAQ = [
    (
        "PREENROLLMENT",
        "Comment faire une demande de préinscription ?",
        "Remplissez le formulaire de la page Admissions. Vous recevez une référence de demande ; l'établissement vous recontacte après examen.",
        ["PUBLIC", "PARENT"],
    ),
    (
        "PREENROLLMENT",
        "Une préinscription acceptée vaut-elle inscription ?",
        "Non. Elle permet de poursuivre la démarche avec l'établissement, qui finalise l'inscription.",
        ["PUBLIC", "PARENT"],
    ),
    (
        "DOCUMENTS",
        "Quels documents faut-il fournir ?",
        "La liste des documents vous est communiquée par l'établissement lors de l'examen de votre demande.",
        ["PUBLIC", "PARENT"],
    ),
    (
        "ADMISSIONS",
        "Faut-il payer pour se préinscrire en ligne ?",
        "Aucun paiement n'est demandé sur le site. Les éventuels frais d'inscription sont communiqués par l'établissement.",
        ["PUBLIC"],
    ),
    (
        "ACTIVATION",
        "Comment activer mon Espace ISBREE ?",
        "Lorsque votre demande est acceptée, l'établissement vous remet un lien d'invitation valable 48 heures et utilisable une seule fois. Il vous permet de choisir votre mot de passe.",
        ["PUBLIC", "PARENT"],
    ),
    (
        "ACTIVATION",
        "Mon lien d'invitation a expiré, que faire ?",
        "Contactez l'établissement : il peut vous remettre un nouveau lien. L'ancien devient alors inutilisable.",
        ["PUBLIC", "PARENT"],
    ),
    (
        "PORTAL",
        "Pourquoi ne vois-je pas encore les informations de mon enfant ?",
        "Les informations scolaires d'un enfant s'affichent seulement après la vérification du lien parent-enfant par l'établissement.",
        ["PARENT"],
    ),
    (
        "PORTAL",
        "Comment installer l'application mobile ?",
        "La section « Applications » de votre Espace propose l'application correspondant à votre rôle lorsqu'une version officielle est disponible.",
        ["PARENT", "TEACHER", "STAFF", "GUARDIAN"],
    ),
    (
        "CONTACT",
        "Comment joindre l'établissement ?",
        "Par téléphone au +237 698 686 729 ou par les coordonnées de la page Contact.",
        ["PUBLIC", "PARENT", "TEACHER", "STAFF", "GUARDIAN"],
    ),
    (
        "TEACHING",
        "Où trouver les programmes et ressources ?",
        "Dans votre Espace, rubrique Ressources : elles sont publiées par l'établissement pour vos classes.",
        ["TEACHER"],
    ),
    (
        "WORK",
        "Où trouver les consignes de mon poste ?",
        "Dans votre Espace, rubrique Missions et consignes, publiées par l'établissement.",
        ["STAFF", "GUARDIAN"],
    ),
]


def _editorial(w):
    school, actor = w.school, w.admin
    profile, created = SiteProfile.objects.get_or_create(school=school, defaults={**PROFILE, "to_validate": True})
    if created:
        w.created.append("présentation de l'établissement")
    for order, (kind, slug, title, summary, body, audiences) in enumerate(PAGES):
        if not Page.objects.filter(school=school, slug=slug).exists():
            web.save_content(
                "pages",
                school,
                actor=actor,
                values={
                    "kind": kind,
                    "slug": slug,
                    "title": title,
                    "summary": summary,
                    "body": body,
                    "audiences": audiences,
                    "status": "PUBLISHED",
                    "to_validate": True,
                    "order": order,
                },
            )
            w.created.append(f"page {slug}")
    for order, (category, question, answer, audiences) in enumerate(FAQ):
        if not FaqEntry.objects.filter(school=school, question=question).exists():
            web.save_content(
                "faq",
                school,
                actor=actor,
                values={
                    "category": category,
                    "question": question,
                    "answer": answer,
                    "audiences": audiences,
                    "status": "PUBLISHED",
                    "to_validate": True,
                    "order": order,
                },
            )
            w.created.append("question de FAQ")


# =============================================================================
# Demonstration (--demo): fictitious, flagged
# =============================================================================

DEMO_NEWS = [
    (
        "journee-portes-ouvertes",
        "Journée portes ouvertes (démonstration)",
        "EVENT",
        "Une actualité fictive pour présenter la mise en page des événements.",
        ["PUBLIC", "PARENT"],
    ),
    (
        "rentree-scolaire",
        "Préparer la rentrée (démonstration)",
        "NEWS",
        "Une actualité fictive : les informations réelles de rentrée seront publiées par l'établissement.",
        ["PUBLIC", "PARENT", "TEACHER", "STAFF"],
    ),
    (
        "reunion-equipe",
        "Réunion de l'équipe (démonstration)",
        "ANNOUNCEMENT",
        "Une annonce fictive réservée au personnel.",
        ["TEACHER", "STAFF"],
    ),
]


def _demo_content(w, klass):
    school, actor = w.school, w.admin
    for order, (name, description, address, is_main) in enumerate(
        [
            (
                "Établissement ISBREE",
                "Le site de l'établissement.",
                "Etoug-Ebe, Yaoundé (adresse exacte à confirmer)",
                True,
            ),
            ("Campus Horizon", "Lieu FICTIF de démonstration.", "", False),
            ("Annexe Les Manguiers", "Lieu FICTIF de démonstration.", "", False),
        ]
    ):
        if not SiteLocation.objects.filter(school=school, name=name).exists():
            web.save_content(
                "locations",
                school,
                actor=actor,
                values={
                    "name": name,
                    "description": description,
                    "address_text": address,
                    "is_main": is_main,
                    "status": "PUBLISHED",
                    "is_demo": not is_main,
                    "to_validate": is_main,
                    "order": order,
                },
            )
            w.created.append(f"lieu {name}")
    for slug, title, category, summary, audiences in DEMO_NEWS:
        if not NewsArticle.objects.filter(school=school, slug=slug).exists():
            web.save_content(
                "news",
                school,
                actor=actor,
                values={
                    "slug": slug,
                    "title": title,
                    "category": category,
                    "summary": summary,
                    "body": f"{summary}\n\nCette actualité est une donnée de démonstration.",
                    "audiences": audiences,
                    "status": "PUBLISHED",
                    "is_demo": True,
                },
            )
            w.created.append(f"actualité {slug}")
    resources = [
        (
            "SUPPLIES",
            f"Liste de fournitures — {klass.name} (démonstration)",
            "Exemple de liste : cahiers, stylos, règle. La liste officielle sera publiée par l'établissement.",
            ["PARENT"],
            {"school_class": klass},
        ),
        (
            "PRACTICAL_INFO",
            "Horaires et entrées (démonstration)",
            "Exemple d'information pratique destinée aux familles.",
            ["PARENT"],
            {},
        ),
        (
            "PROGRAMME",
            f"Progression de mathématiques — {klass.level.name} (démonstration)",
            "Exemple de progression pédagogique publiée pour les enseignants du niveau.",
            ["TEACHER"],
            {"level": klass.level},
        ),
        (
            "MISSION",
            "Missions du secrétariat (démonstration)",
            "Exemple de description de poste : accueil, gestion des dossiers, relais d'information.",
            ["STAFF"],
            {"staff_function": StaffFunction.objects.filter(school=school, code="SECRETARIAT").first()},
        ),
        (
            "PROCEDURE",
            "Contrôle des accès au portail (démonstration)",
            "Exemple de procédure : vérifier le QR code de l'élève avec l'application Gardien, orienter les visiteurs vers l'accueil.",
            ["GUARDIAN"],
            {},
        ),
    ]
    for kind, title, body, audiences, scope in resources:
        if not RoleResource.objects.filter(school=school, title=title).exists():
            web.save_content(
                "resources",
                school,
                actor=actor,
                values={
                    "kind": kind,
                    "title": title,
                    "body": body,
                    "audiences": audiences,
                    "status": "PUBLISHED",
                    "is_demo": True,
                    **{k: v for k, v in scope.items() if v is not None},
                },
            )
            w.created.append(f"ressource {kind}")


def _year(w):
    today = timezone.localdate()
    year = AcademicYear.objects.filter(school=w.school, start_date__lte=today, end_date__gte=today).first()
    if year is None:
        start = date(today.year if today.month >= 9 else today.year - 1, 9, 1)
        year = academics.create_academic_year(
            w.school,
            name=f"{start.year}-{start.year + 1}",
            start_date=start,
            end_date=date(start.year + 1, 7, 31),
            status=AcademicYearStatus.ACTIVE,
        )
        w.created.append(f"année {year.name}")
    if not year.is_current:
        year = academics.set_current_year(year)
    return year


def _account(w, *, email, first_name, last_name, role, password):
    """A demo account of the school with `role`, activated with the REAL
    activation flow (code issued by the administration, then completed)."""
    membership = SchoolMembership.objects.filter(school=w.school, user__email__iexact=email).first()
    if membership is None:
        if User.objects.filter(email__iexact=email).exists():
            raise ImproperlyConfigured(f"{email} already belongs to another account.")
        user = User.objects.create_user(
            username=email, email=email, password=None, first_name=first_name, last_name=last_name
        )
        membership = SchoolMembership.objects.create(
            school=w.school, user=user, status=MembershipStatus.ACTIVE, is_primary_school=True, joined_at=timezone.now()
        )
        MembershipRole.objects.create(membership=membership, role=Role.objects.get(code=role), assigned_by=w.admin)
        w.created.append(f"compte {email}")
    if not membership.user.has_usable_password():
        _, code = activation.issue_activation(membership, actor=w.admin)
        activation.complete_activation(code, _password(password))
        membership.refresh_from_db()
    return membership


def _demo(w, password):
    school, actor = w.school, w.admin
    year = _year(w)
    levels = []
    for order, (code, name) in enumerate([("6E", "6e (démo)"), ("5E", "5e (démo)")]):
        level = Level.objects.filter(school=school, code=code).first() or academics.create_level(
            school, actor=actor, code=code, name=name, cycle="Démonstration", order_index=order, public_visible=True
        )
        levels.append(level)
    klass = SchoolClass.objects.filter(
        school=school, academic_year=year, name="6e A (démo)"
    ).first() or academics.create_class(school, actor=actor, name="6e A (démo)", level=levels[0], academic_year=year)
    category = PedagogicalCategory.objects.filter(school=school, code="SCI").first() or academics.create_category(
        school, actor=actor, code="SCI", name="Sciences (démo)"
    )
    maths = Subject.objects.filter(school=school, code="MATH").first() or academics.create_subject(
        school, actor=actor, code="MATH", name="Mathématiques", category=category
    )
    function = StaffFunction.objects.filter(school=school, code="SECRETARIAT").first() or StaffFunction.objects.create(
        school=school, code="SECRETARIAT", name="Secrétariat (démo)"
    )
    # Teacher with a course.
    teacher_email = f"enseignant.demo@{DEMO_DOMAIN}"
    teacher_member = SchoolMembership.objects.filter(school=school, user__email__iexact=teacher_email).first()
    if teacher_member is None:
        teacher = people.admin_create_teacher(
            school,
            actor=actor,
            first_name="Samuel",
            last_name="Démo",
            email=teacher_email,
            employee_number="ENS-DEMO-01",
            pedagogical_category=category,
            primary_subject=maths,
        )
        teacher_member = teacher.employee.membership
        w.created.append(f"enseignant {teacher_email}")
    if not teacher_member.user.has_usable_password():
        _, code = activation.issue_activation(teacher_member, actor=actor)
        activation.complete_activation(code, _password(password))
    teacher = teacher_member.employee_profile.teacher_profile
    if not Course.objects.filter(school_class=klass, subject=maths, teacher=teacher).exists():
        gradebook.create_course(klass, maths, teacher, actor=actor, weekly_hours=4)
    # Staff member with a function.
    staff_member = _account(
        w,
        email=f"personnel.demo@{DEMO_DOMAIN}",
        first_name="Agnès",
        last_name="Démo",
        role=RoleCode.STAFF,
        password=password,
    )
    if not hasattr(staff_member, "employee_profile"):
        employee = people.create_employee(staff_member, employee_number="PER-DEMO-01", employee_type=EmployeeType.STAFF)
        staff = people.create_staff(employee, staff_number="PER-DEMO-01")
        people.assign_staff_function(staff, function, actor=actor)
    # Gate guardian.
    guardian_email = f"gardien.demo@{DEMO_DOMAIN}"
    guardian_member = SchoolMembership.objects.filter(school=school, user__email__iexact=guardian_email).first()
    if guardian_member is None:
        guardian_member = people.admin_create_guardian(
            school, actor=actor, first_name="Marc", last_name="Démo", email=guardian_email, guardian_number="G-DEMO-01"
        ).membership
        w.created.append(f"gardien {guardian_email}")
    if not guardian_member.user.has_usable_password():
        _, code = activation.issue_activation(guardian_member, actor=actor)
        activation.complete_activation(code, _password(password))
    # A pupil and a parent with a VERIFIED link (real workflow, ADR 0026).
    student = Student.objects.filter(
        school=school, student_number="ISB-DEMO-001"
    ).first() or people.admin_create_student(
        school,
        actor=actor,
        enrollment={"school_class": klass},
        student_number="ISB-DEMO-001",
        registration_number="ISB-INS-DEMO-001",
        first_name="Léa",
        last_name="Démo",
        date_of_birth=date(2014, 3, 12),
        sex="F",
    )
    parent_email = f"parent.demo@{DEMO_DOMAIN}"
    if not User.objects.filter(email__iexact=parent_email).exists():
        parent_workflow.register_parent(
            first_name="Claire",
            last_name="Démo",
            email=parent_email,
            password=_password(password),
            school_code=school.code,
        )
        w.created.append(f"parent {parent_email}")
    parent_member = SchoolMembership.objects.get(school=school, user__email__iexact=parent_email)
    pending = RegistrationRequest.objects.filter(membership=parent_member, status="PENDING").first()
    if pending is not None:
        parent_workflow.approve_registration(pending, actor=actor)
        parent_member = SchoolMembership.objects.get(pk=parent_member.pk)  # ACTIVE now, with the PARENT role
    if not ParentStudent.objects.filter(
        parent__membership=parent_member, student=student, identity_verified=True
    ).exists():
        request = parent_workflow.request_link(
            parent_member,
            student_number=student.student_number,
            date_of_birth=student.date_of_birth,
            relationship_type="MOTHER",
            document_type="CNI",
            document_number="DEMO-0001",
        )
        parent_workflow.check_identity(request, actor=actor, document_type="CNI", document_number="DEMO-0001")
        parent_workflow.record_student_approval(request, actor=actor, decision="APPROVED", note="Démonstration ISBREE")
        parent_workflow.approve_link_request(request, actor=actor, can_receive_notifications=True)
        w.created.append("lien parent-enfant vérifié (démo)")
    _demo_content(w, klass)


# =============================================================================
# Illustration images (--images DIR)
# =============================================================================

IMAGE_TEXTS = {
    # file stem -> (alt text, caption, category). Illustrations provided for the demonstration.
    "1": ("Des élèves travaillent en classe", "Travail en classe", "CLASSROOMS"),
    "2": ("Des élèves dans la cour d'un établissement", "La cour", "CAMPUS"),
    "3": ("Une classe équipée d'ordinateurs portables", "Apprendre avec le numérique", "CLASSROOMS"),
    "4": ("Des élèves lèvent la main en classe", "Participation en classe", "CLASSROOMS"),
    "5": ("Une salle de classe aux pupitres en bois", "Une salle de classe", "CLASSROOMS"),
    "6": ("Un bâtiment scolaire moderne entouré de verdure", "Un cadre d'étude", "CAMPUS"),
    "7": ("Un amphithéâtre aux tables alignées", "Salle de cours", "CLASSROOMS"),
    "8": ("Une salle de classe lumineuse", "Espace d'apprentissage", "CLASSROOMS"),
    "9": ("Un gymnase couvert avec terrains de basket", "Le sport", "SPORTS"),
    "10": ("Des enfants jouent au football sur un terrain en herbe", "Activités sportives", "SPORTS"),
}


def _images(w, folder):
    folder = Path(folder)
    for order, path in enumerate(sorted(folder.iterdir(), key=lambda p: (len(p.stem), p.stem))):
        if path.stem not in IMAGE_TEXTS or path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            continue
        alt, caption, category = IMAGE_TEXTS[path.stem]
        if ContentImage.objects.filter(school=w.school, alt_text=alt).exists():
            continue
        upload = SimpleUploadedFile(path.name, path.read_bytes())
        web.add_image(
            w.school,
            actor=w.admin,
            upload=upload,
            values={
                "alt_text": alt,
                "caption": caption,
                "category": category,
                "order": order,
                "credit": "Image d'illustration fournie — ne représente pas ISBREE",
                "is_illustration": True,
                "status": "PUBLISHED",
                "audiences": ["PUBLIC", "PARENT", "TEACHER", "STAFF", "GUARDIAN"],
            },
        )
        w.created.append(f"image {path.name}")


# =============================================================================


@transaction.atomic
def seed(*, password=None, demo=False, images=None, contact_email=None, contact_phone=None):
    _refuse_production()
    w = Seeded()
    w.school = School.objects.filter(code=CODE).first()
    if w.school is None:
        provisioned = SchoolProvisioningService().provision(
            code=CODE,
            name="ISBREE",
            city="Yaoundé",
            address="Etoug-Ebe, Yaoundé",
            admin=FirstAdmin(
                username="isbree.admin",
                email=f"admin@{DEMO_DOMAIN}",
                first_name="Administration",
                last_name="ISBREE",
                password=_password(password),
            ),
        )
        w.school, w.admin = provisioned.school, provisioned.admin_membership
        w.created.append("établissement ISBREE + administrateur isbree.admin")
    else:
        w.admin = SchoolMembership.objects.get(school=w.school, user__username="isbree.admin")
    changed = []
    phone = contact_phone or DEFAULT_PHONE
    if not w.school.phone:
        w.school.phone = phone
        changed.append("phone")
    if contact_email and not w.school.email:
        w.school.email = contact_email
        changed.append("email")
    if changed:
        w.school.save(update_fields=[*changed, "updated_at"])
        w.created.append("coordonnées de contact")
    _editorial(w)
    if demo:
        _demo(w, password)
    if images:
        _images(w, images)
    return w

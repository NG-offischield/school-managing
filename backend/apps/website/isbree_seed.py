"""Initial ISBREE content and demonstration accounts (ADR 0032).

`manage.py seed_isbree` (never with the production settings):

- the school ISBREE (provisioned like any school, ADR 0006) with the contact
  information the school gave: phone, e-mail (ISBREE_CONTACT_EMAIL, from the
  environment only), location "Etoug-Ebe, Yaoundé" — the exact street address
  stays UNCONFIRMED (never shown publicly until the school confirms it);
- a first version of every editorial content, ALL flagged `to_validate`:
  wording proposed for the school to correct, nothing presented as an
  official rule, fee, date, diploma or accreditation;
- with --demo: fictitious demonstration data — one account per portal role
  (parent with two VERIFIED children, mathematics teacher, staff with a
  function, gate guardian) whose password is ISBREE_DEMO_PASSWORD (never
  stored nor printed; reserved .test addresses), the school life around them
  (isbree_world: classes, timetable, marks, attendance, fees) and news and
  role resources flagged `is_demo`. The public site and the portal state once,
  in their footer, that these data are fictitious;
- with --images DIR: the illustration images (re-encoded, EXIF removed),
  always flagged `is_illustration` (they do not show ISBREE).

Idempotent: every object is looked up first; nothing is deleted. A content is
rewritten only while it still holds the first seed's text (titles marked
"(démonstration)", names "… Démo", text ending with the provisional notice):
an existing content edited by the school keeps its edits.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.utils import timezone

from apps.academics import services as academics
from apps.academics.models import AcademicYear, AcademicYearStatus
from apps.accounts import activation
from apps.accounts.models import MembershipRole, MembershipStatus, Role, RoleCode, SchoolMembership, User
from apps.communication.attachments import private_storage
from apps.core.models import School
from apps.core.services import FirstAdmin, SchoolProvisioningService
from apps.people import parent_workflow
from apps.people import services as people
from apps.people.models import EmployeeType, RegistrationRequest, StaffFunction

from . import files
from . import isbree_world as world
from . import services as web
from .models import (
    ContentImage,
    FaqEntry,
    NewsArticle,
    Page,
    PublicationStatus,
    RoleResource,
    SiteLocation,
    SiteProfile,
)

CODE = "ISBREE"
DEMO_DOMAIN = "isbree.test"
PRODUCTION_SETTINGS = "config.settings.production"
DEFAULT_PHONE = "+237698686729"  # given by the school in the specification

# Fictitious names of the demo accounts (the first demo seed called them all "<first name> Démo").
DEMO_PEOPLE = {
    "teacher": ("Samuel", "Ateba"),
    "staff": ("Agnès", "Biloa"),
    "guardian": ("Marc", "Owona"),
    "parent": ("Claire", "Mballa"),
}
LEGACY_LAST_NAME = "Démo"


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


def _admin_password(admin_password, password):
    """The administrator's password. In a PUBLIC demo (ISBREE_PUBLIC_DEMO) the shared
    password of the demonstration accounts is published: the administrator must
    then have its own, distinct one (ISBREE_ADMIN_PASSWORD), never handed out."""
    if getattr(settings, "ISBREE_PUBLIC_DEMO", False) and (not admin_password or admin_password == password):
        raise ImproperlyConfigured(
            "Public demo: ISBREE_ADMIN_PASSWORD is required and must differ from ISBREE_DEMO_PASSWORD."
        )
    return _password(admin_password or password)


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
    for order, (kind, slug, title, summary, seeded_body, audiences) in enumerate(PAGES):
        # The provisional status is shown from the `to_validate` flag: the same
        # sentence at the end of the text only repeated it (first seed).
        body = seeded_body.removesuffix(f"\n\n{PROVISIONAL}")
        existing = Page.objects.filter(school=school, slug=slug).first()
        if existing is not None and existing.body == seeded_body != body:
            web.save_content("pages", school, actor=actor, values={"body": body}, instance=existing)
            w.created.append(f"page {slug} : mention provisoire en double retirée")
        if existing is None:
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


def _saturday_after(day):
    return day + timedelta(days=(5 - day.weekday()) % 7)


def demo_news(y):
    """Fictitious news of the school year starting in September of `y`:
    (slug, title, category, published on, event date, summary, body, audiences)."""
    return [
        (
            "rentree-scolaire",
            f"Une rentrée sereine pour l'année {y}-{y + 1}",
            "NEWS",
            date(y, 9, 4),
            None,
            "Les élèves de la 6e à la 3e ont retrouvé leurs classes : emplois du temps, fournitures et premiers repères.",
            "Les quatre classes du premier cycle ont fait leur rentrée dans le calme. Chaque élève a reçu son emploi "
            "du temps et sa carte d'élève, présentée chaque matin au portail.\n\n## Les premiers jours\n- Accueil "
            "des classes par leur professeur principal\n- Présentation du règlement intérieur\n- Remise des "
            "listes de fournitures, aussi consultables dans l'Espace ISBREE\n\nLes familles retrouvent l'emploi du "
            "temps, les notes et les absences dans l'application Parent.",
            ["PUBLIC", "PARENT", "TEACHER", "STAFF"],
        ),
        (
            "reunion-equipe",
            "Conseil pédagogique de début d'année",
            "ANNOUNCEMENT",
            date(y, 9, 9),
            None,
            "L'équipe enseignante a arrêté les progressions et le calendrier des évaluations du premier trimestre.",
            "Le conseil pédagogique a réuni les professeurs des sept disciplines.\n\n## Décisions\n- Deux "
            "évaluations par séquence et par matière : une interrogation écrite et un devoir surveillé\n- Saisie "
            "des notes dans l'application Enseignant au plus tard une semaine après l'évaluation\n- Progressions "
            "publiées dans la rubrique Ressources",
            ["TEACHER", "STAFF"],
        ),
        (
            "semaine-de-la-lecture",
            "Semaine de la lecture : les 6e à la bibliothèque",
            "NEWS",
            date(y, 10, 2),
            None,
            "Pendant une semaine, les élèves de 6e A ont découvert la bibliothèque et présenté leur livre préféré.",
            "Chaque jour, une heure de français a eu lieu à la bibliothèque. Les élèves ont choisi un roman, puis "
            "l'ont présenté à leurs camarades en quelques minutes.\n\nL'activité se poursuit toute l'année : un "
            "créneau de lecture libre est proposé chaque vendredi.",
            ["PUBLIC", "PARENT"],
        ),
        (
            "journee-portes-ouvertes",
            "Journée portes ouvertes",
            "EVENT",
            date(y, 10, 12),
            _saturday_after(date(y, 11, 10)),
            "Familles et futurs élèves sont invités à découvrir les classes, les enseignants et la vie de l'établissement.",
            "## Au programme\n- Visite des salles de classe\n- Rencontre avec les professeurs principaux\n- "
            "Présentation de la préinscription en ligne et de l'Espace ISBREE\n\nL'entrée est libre, de 9 h à 13 h.",
            ["PUBLIC", "PARENT"],
        ),
        (
            "rencontre-parents-professeurs",
            "Rencontre parents-professeurs du premier trimestre",
            "EVENT",
            date(y, 10, 15),
            _saturday_after(date(y, 11, 21)),
            "Chaque famille rencontre le professeur principal pour faire le point sur les résultats de la séquence 1.",
            "Les rendez-vous durent quinze minutes. Les notes de la séquence 1 sont déjà consultables dans "
            "l'application Parent : elles serviront de base à l'échange.\n\nLes familles qui ne peuvent pas venir "
            "peuvent demander un autre créneau à l'administration.",
            ["PARENT", "TEACHER"],
        ),
        (
            "tournoi-inter-classes",
            "Tournoi de football inter-classes",
            "EVENT",
            date(y, 11, 20),
            date(y, 12, 11),
            "Les quatre classes s'affrontent avant les congés de Noël, encadrées par le professeur d'EPS.",
            "Les matchs se jouent pendant les heures d'EPS de la semaine, la finale le vendredi après-midi. "
            "Chaque classe présente une équipe mixte.",
            ["PUBLIC", "PARENT", "TEACHER", "STAFF"],
        ),
    ]


# Titles given by the first demo seed (renamed only while still unchanged).
LEGACY_NEWS_TITLES = {
    "journee-portes-ouvertes": "Journée portes ouvertes (démonstration)",
    "rentree-scolaire": "Préparer la rentrée (démonstration)",
    "reunion-equipe": "Réunion de l'équipe (démonstration)",
}
LEGACY_LOCATIONS = {"Campus Horizon", "Annexe Les Manguiers"}  # invented places: archived
# Cover of each demo news item: an illustration (IMAGE_TEXTS), by its alternative text.
NEWS_COVERS = {
    "rentree-scolaire": "Des élèves dans la cour d'un établissement",
    "reunion-equipe": "Un amphithéâtre aux tables alignées",
    "semaine-de-la-lecture": "Des élèves travaillent en classe",
    "journee-portes-ouvertes": "Un bâtiment scolaire moderne entouré de verdure",
    "rencontre-parents-professeurs": "Une salle de classe lumineuse",
    "tournoi-inter-classes": "Des enfants jouent au football sur un terrain en herbe",
}


def demo_resources(klass):
    """(kind, title, legacy title of the first seed, body, audiences, scope)."""
    return [
        (
            "SUPPLIES",
            f"Liste de fournitures — {klass.name}",
            "Liste de fournitures — 6e A (démo) (démonstration)",
            "- 6 cahiers de 200 pages grand format\n- 4 cahiers de 100 pages\n- 1 cahier de travaux pratiques\n- "
            "Stylos bleu, rouge, vert et noir, crayon à papier, gomme\n- Règle de 30 cm, équerre, rapporteur, compas\n"
            "- Calculatrice de collège\n- Dictionnaire de français\n- Tenue de sport pour l'EPS",
            ["PARENT"],
            {"school_class": klass},
        ),
        (
            "PRACTICAL_INFO",
            "Horaires et entrées des élèves",
            "Horaires et entrées (démonstration)",
            "- Ouverture du portail : 7 h\n- Début des cours : 7 h 30 ; après 7 h 30, l'élève est noté en retard\n- "
            "Fin des cours : 14 h 50, le mercredi 11 h 25\n- À l'entrée, l'élève présente sa carte (QR code) au "
            "gardien : la présence est enregistrée et visible dans l'application Parent\n- Toute absence doit être "
            "justifiée auprès de l'administration",
            ["PARENT"],
            {},
        ),
        (
            "PROGRAMME",
            f"Progression de mathématiques — {klass.level.name}",
            "Progression de mathématiques — 6e (démo) (démonstration)",
            "## Premier trimestre\n- Séquence 1 : nombres entiers et décimaux, opérations\n- Séquence 2 : droites, "
            "segments, cercles ; fractions\n\n## Deuxième trimestre\n- Séquence 3 : angles, symétrie axiale\n- "
            "Séquence 4 : proportionnalité, pourcentages\n\n## Troisième trimestre\n- Séquence 5 : périmètres et "
            "aires\n- Séquence 6 : volumes, organisation de données",
            ["TEACHER"],
            {"level": klass.level},
        ),
        (
            "MISSION",
            "Missions du secrétariat",
            "Missions du secrétariat (démonstration)",
            "- Accueil des familles et des visiteurs\n- Tenue des dossiers des élèves et des préinscriptions\n- "
            "Encaissement des frais au guichet et remise des reçus\n- Relais des informations de l'administration",
            ["STAFF"],
            {"staff_function": None},  # filled in _demo_content
        ),
        (
            "PROCEDURE",
            "Contrôle des entrées au portail",
            "Contrôle des accès au portail (démonstration)",
            "- Scanner la carte (QR code) de chaque élève avec l'application Gardien\n- Un élève sans carte est "
            "orienté vers l'administration\n- Les visiteurs sont accompagnés jusqu'à l'accueil\n- Signaler tout "
            "incident à l'administration le jour même",
            ["GUARDIAN"],
            {},
        ),
    ]


def _demo_content(w, klass):
    school, actor = w.school, w.admin
    main = "Établissement ISBREE"
    if not SiteLocation.objects.filter(school=school, name=main).exists():
        web.save_content(
            "locations",
            school,
            actor=actor,
            values={
                "name": main,
                "description": "Le site de l'établissement.",
                "address_text": "Etoug-Ebe, Yaoundé (adresse exacte à confirmer)",
                "is_main": True,
                "status": "PUBLISHED",
                "is_demo": False,
                "to_validate": True,
                "order": 0,
            },
        )
        w.created.append(f"lieu {main}")
    for location in SiteLocation.objects.filter(
        school=school, name__in=LEGACY_LOCATIONS, is_demo=True, status=PublicationStatus.PUBLISHED
    ):
        web.save_content("locations", school, actor=actor, values={"status": "ARCHIVED"}, instance=location)
        w.created.append(f"lieu fictif archivé : {location.name}")

    tz = ZoneInfo(school.timezone)
    today = timezone.localdate()
    year = klass.academic_year.start_date.year
    for slug, title, category, published, event_date, summary, body, audiences in demo_news(year):
        values = {
            "slug": slug,
            "title": title,
            "category": category,
            "summary": summary,
            "body": body,
            "event_date": event_date,
            "audiences": audiences,
        }
        article = NewsArticle.objects.filter(school=school, slug=slug).first()
        if article is not None and article.title != LEGACY_NEWS_TITLES.get(slug):
            continue  # exists and was not the first seed's text: the school's edits are kept
        if article is None and published > today:
            continue  # not published yet: added by a later run
        row = web.save_content(
            "news",
            school,
            actor=actor,
            values={**values, "status": "PUBLISHED", "is_demo": True},
            instance=article,
        )
        NewsArticle.objects.filter(pk=row.pk).update(published_at=datetime.combine(published, time(9), tz))
        w.created.append(f"actualité {slug}" + (" réécrite" if article else ""))
    # Covers: only for a demo news item still without one (an edited cover is kept).
    for slug, alt in NEWS_COVERS.items():
        image = ContentImage.objects.filter(school=school, alt_text=alt).first()
        article = NewsArticle.objects.filter(school=school, slug=slug, is_demo=True, cover__isnull=True).first()
        if image is not None and article is not None:
            web.save_content("news", school, actor=actor, values={"slug": slug, "cover": image}, instance=article)
            w.created.append(f"couverture de l'actualité {slug}")

    function = StaffFunction.objects.filter(school=school, code="SECRETARIAT").first()
    for kind, title, legacy, body, audiences, scope in demo_resources(klass):
        if "staff_function" in scope:
            scope = {"staff_function": function}
        values = {"kind": kind, "title": title, "body": body, "audiences": audiences}
        old = RoleResource.objects.filter(school=school, title=legacy).first()
        if old is not None:
            web.save_content("resources", school, actor=actor, values=values, instance=old)
            w.created.append(f"ressource renommée : {title}")
        elif not RoleResource.objects.filter(school=school, title=title).exists():
            web.save_content(
                "resources",
                school,
                actor=actor,
                values={**values, "status": "PUBLISHED", "is_demo": True, **{k: v for k, v in scope.items() if v}},
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


def _rename_user(w, membership, first_name, last_name):
    """The first demo seed named every account "<first name> Démo": give the
    person a full fictitious name (only when the seeded name is unchanged)."""
    user = membership.user
    if user.last_name == LEGACY_LAST_NAME and user.first_name == first_name:
        user.last_name = last_name
        user.save(update_fields=["last_name"])
        w.created.append(f"nom complété : {first_name} {last_name}")


DEMO_LOGINS = [f"{prefix}.demo@{DEMO_DOMAIN}" for prefix in ("parent", "enseignant", "personnel", "gardien")]


def demo_missing():
    """What the demonstration cannot work without (read only; [] = complete):
    the school, the four active demo accounts with a password, the demo
    parent's verified child, a class with its pupils."""
    from apps.people.models import ParentStudent, StudentEnrollment

    school = School.objects.filter(code=CODE).first()
    if school is None:
        return [f"établissement {CODE}"]
    missing = []
    for email in DEMO_LOGINS:
        member = (
            SchoolMembership.objects.filter(school=school, user__email__iexact=email).select_related("user").first()
        )
        if member is None or member.status != MembershipStatus.ACTIVE or not member.user.is_active:
            missing.append(f"compte actif {email}")
        elif not member.user.has_usable_password():
            missing.append(f"mot de passe du compte {email}")
    if not ParentStudent.objects.filter(
        parent__membership__user__email__iexact=DEMO_LOGINS[0], identity_verified=True, active=True
    ).exists():
        missing.append("enfant vérifié du parent de démonstration")
    if not StudentEnrollment.objects.filter(school=school, status="ACTIVE").exists():
        missing.append("élèves inscrits dans une classe")
    return missing


def _shared_password(w, membership, password):
    """Public demo (ISBREE_PUBLIC_DEMO): the portal publishes ISBREE_DEMO_PASSWORD
    for the four read-only demo accounts. An account created with an earlier
    value would refuse the published one (401 at every login), so their password
    follows the configured value. Never isbree.admin, never outside the public demo."""
    user = membership.user
    if getattr(settings, "ISBREE_PUBLIC_DEMO", False) and password and not user.check_password(password):
        user.set_password(password)
        user.save(update_fields=["password"])
        w.created.append(f"mot de passe partagé aligné : {user.email}")


def _demo(w, password):
    school, actor = w.school, w.admin
    year = _year(w)
    classes, subjects = world.structure(w, year)
    maths = subjects["MATH"]
    function = StaffFunction.objects.filter(school=school, code="SECRETARIAT").first() or StaffFunction.objects.create(
        school=school, code="SECRETARIAT", name="Secrétariat"
    )
    if function.name == "Secrétariat (démo)":
        function.name = "Secrétariat"
        function.save(update_fields=["name"])
    # The demo teacher: mathematics in every class (isbree_world).
    first, last = DEMO_PEOPLE["teacher"]
    teacher_email = f"enseignant.demo@{DEMO_DOMAIN}"
    teacher_member = SchoolMembership.objects.filter(school=school, user__email__iexact=teacher_email).first()
    if teacher_member is None:
        teacher = people.admin_create_teacher(
            school,
            actor=actor,
            first_name=first,
            last_name=last,
            email=teacher_email,
            employee_number="ENS-MATH-01",
            pedagogical_category=maths.category,
            primary_subject=maths,
        )
        teacher_member = teacher.employee.membership
        w.created.append(f"enseignant {teacher_email}")
    _rename_user(w, teacher_member, first, last)
    if not teacher_member.user.has_usable_password():
        _, code = activation.issue_activation(teacher_member, actor=actor)
        activation.complete_activation(code, _password(password))
    teacher = teacher_member.employee_profile.teacher_profile
    # Staff member with a function.
    first, last = DEMO_PEOPLE["staff"]
    staff_member = _account(
        w,
        email=f"personnel.demo@{DEMO_DOMAIN}",
        first_name=first,
        last_name=last,
        role=RoleCode.STAFF,
        password=password,
    )
    _rename_user(w, staff_member, first, last)
    if not hasattr(staff_member, "employee_profile"):
        employee = people.create_employee(staff_member, employee_number="PER-SEC-01", employee_type=EmployeeType.STAFF)
        staff = people.create_staff(employee, staff_number="PER-SEC-01")
        people.assign_staff_function(staff, function, actor=actor)
    # Gate guardian.
    first, last = DEMO_PEOPLE["guardian"]
    guardian_email = f"gardien.demo@{DEMO_DOMAIN}"
    guardian_member = SchoolMembership.objects.filter(school=school, user__email__iexact=guardian_email).first()
    if guardian_member is None:
        guardian_member = people.admin_create_guardian(
            school, actor=actor, first_name=first, last_name=last, email=guardian_email, guardian_number="G-01"
        ).membership
        w.created.append(f"gardien {guardian_email}")
    _rename_user(w, guardian_member, first, last)
    if not guardian_member.user.has_usable_password():
        _, code = activation.issue_activation(guardian_member, actor=actor)
        activation.complete_activation(code, _password(password))
    # A parent, then her two children with VERIFIED links (real workflow, ADR 0026).
    first, last = DEMO_PEOPLE["parent"]
    parent_email = f"parent.demo@{DEMO_DOMAIN}"
    if not User.objects.filter(email__iexact=parent_email).exists():
        parent_workflow.register_parent(
            first_name=first,
            last_name=last,
            email=parent_email,
            password=_password(password),
            school_code=school.code,
        )
        w.created.append(f"parent {parent_email}")
    parent_member = SchoolMembership.objects.get(school=school, user__email__iexact=parent_email)
    _rename_user(w, parent_member, first, last)
    pending = RegistrationRequest.objects.filter(membership=parent_member, status="PENDING").first()
    if pending is not None:
        parent_workflow.approve_registration(pending, actor=actor)
        parent_member = SchoolMembership.objects.get(pk=parent_member.pk)  # ACTIVE now, with the PARENT role
    for member in (teacher_member, staff_member, guardian_member, parent_member):
        member.user.refresh_from_db()
        _shared_password(w, member, password)
    world.build(
        w,
        year=year,
        classes=classes,
        subjects=subjects,
        maths_teacher=teacher,
        parent_member=parent_member,
        guardian_member=guardian_member,
    )
    _demo_content(w, classes["6e A"])


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


def _restore_file(w, image, path):
    """A host without a persistent disk (the free public demo) loses the stored
    files at each restart while the database keeps their rows: put the
    illustration back at the same path, re-encoded by the same checks."""
    storage = private_storage()
    if storage.exists(image.storage_path):
        return
    checked = files.check_image(SimpleUploadedFile(path.name, path.read_bytes()))
    storage.save(image.storage_path, ContentFile(checked.content))
    digest = hashlib.sha256(checked.content).hexdigest()
    if (image.sha256, image.size) != (digest, len(checked.content)):
        image.sha256, image.size = digest, len(checked.content)
        image.save(update_fields=["sha256", "size", "updated_at"])
    w.created.append(f"fichier d'image restauré : {path.name}")


def _images(w, folder):
    folder = Path(folder)
    for order, path in enumerate(sorted(folder.iterdir(), key=lambda p: (len(p.stem), p.stem))):
        if path.stem not in IMAGE_TEXTS or path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".webp"):
            continue
        alt, caption, category = IMAGE_TEXTS[path.stem]
        existing = ContentImage.objects.filter(school=w.school, alt_text=alt).first()
        if existing is not None:
            _restore_file(w, existing, path)
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
def seed(*, password=None, admin_password=None, demo=False, images=None, contact_email=None, contact_phone=None):
    _refuse_production()
    _admin_password(admin_password, password)  # checked even when the school already exists
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
                password=_admin_password(admin_password, password),
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
    if images:  # first: the demo news use them as covers
        _images(w, images)
    if demo:
        _demo(w, password)
    return w

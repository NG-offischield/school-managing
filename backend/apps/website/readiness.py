"""Production readiness of the ISBREE site (ADR 0032).

Lists what the school still has to confirm before a production opening. It
never blocks development: the desktop shows it, and `manage.py
isbree_readiness --school CODE` prints it (exit code 1 when blocking items
remain, for a deployment checklist).
"""

from apps.admissions.services import offered_levels, offered_years

from .models import (
    ContentImage,
    FaqEntry,
    MobileApp,
    MobileAppRelease,
    NewsArticle,
    Page,
    PageKind,
    PublicationStatus,
    ReleaseStatus,
    RoleResource,
    SiteLocation,
    SiteProfile,
)

BLOCKING, WARNING = "blocking", "warning"
REQUIRED_PAGES = (PageKind.LEGAL_NOTICE, PageKind.PRIVACY, PageKind.TERMS)


def readiness_report(school):
    items = []

    def add(code, severity, message, count=None):
        items.append({"code": code, "severity": severity, "message": message, "count": count})

    if not (school.email or "").strip():
        add("contact_email", BLOCKING, "Adresse e-mail de contact non renseignée (ISBREE_CONTACT_EMAIL).")
    if not (school.phone or "").strip():
        add("contact_phone", BLOCKING, "Numéro de téléphone de contact non renseigné.")
    profile = SiteProfile.objects.filter(school=school).first()
    if profile is None:
        add("profile_missing", BLOCKING, "Présentation de l'établissement absente.")
    else:
        if profile.to_validate:
            add("profile_to_validate", BLOCKING, "Présentation de l'établissement encore à valider.")
        if not profile.address_confirmed:
            add("address_unconfirmed", BLOCKING, "Adresse exacte de l'établissement non confirmée.")
    published = PublicationStatus.PUBLISHED
    for kind in REQUIRED_PAGES:
        if not Page.objects.filter(school=school, kind=kind, status=published).exists():
            add(f"page_{kind.lower()}", BLOCKING, f"Page « {PageKind(kind).label} » non publiée.")
    for model, label in (
        (Page, "pages"),
        (FaqEntry, "questions de la FAQ"),
        (NewsArticle, "actualités"),
        (RoleResource, "ressources"),
    ):
        provisional = model.objects.filter(school=school, status=published, to_validate=True).count()
        if provisional:
            add(
                f"{model.__name__.lower()}_to_validate",
                BLOCKING,
                f"{label.capitalize()} publiées avec un texte à valider.",
                provisional,
            )
    for model, label in (
        (Page, "pages"),
        (FaqEntry, "questions"),
        (NewsArticle, "actualités"),
        (RoleResource, "ressources"),
        (SiteLocation, "lieux"),
        (ContentImage, "images"),
    ):
        demo = model.objects.filter(school=school, status=published, is_demo=True).count()
        if demo:
            add(f"{model.__name__.lower()}_demo", BLOCKING, f"Contenus de démonstration publiés ({label}).", demo)
    illustrations = ContentImage.objects.filter(school=school, status=published, is_illustration=True).count()
    if illustrations:
        add(
            "illustrations",
            WARNING,
            "Images d'illustration publiées (ce ne sont pas des photos de l'établissement).",
            illustrations,
        )
    if not offered_levels(school).exists() or not offered_years(school).exists():
        add("pre_enrollment_closed", WARNING, "Aucun niveau ou aucune année ouverte : la préinscription est fermée.")
    for app in MobileApp:
        if not MobileAppRelease.objects.filter(school=school, app=app, status=ReleaseStatus.PUBLISHED).exists():
            add(f"app_{app.lower()}", WARNING, f"{app.label} : aucune version Release signée publiée.")
    return {"ready": not any(i["severity"] == BLOCKING for i in items), "items": items}

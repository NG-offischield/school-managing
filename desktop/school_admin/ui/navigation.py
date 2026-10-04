"""Sidebar structure. Adding a module = one entry here + its page factory in
main_window.py. Entries without a factory are shown greyed out ("bientôt")."""

from dataclasses import dataclass


@dataclass(frozen=True)
class NavEntry:
    key: str
    label: str
    section: str = ""
    available: bool = True
    description: str = ""


NAVIGATION = [
    NavEntry("dashboard", "Tableau de bord"),
    NavEntry("years", "Années scolaires", "Gestion académique"),
    NavEntry("levels", "Niveaux", "Gestion académique"),
    NavEntry("categories", "Catégories pédagogiques", "Gestion académique"),
    NavEntry("subjects", "Matières", "Gestion académique"),
    NavEntry("classes", "Classes", "Gestion académique"),
    NavEntry("students", "Élèves", "Gestion académique"),
    NavEntry("teachers", "Enseignants", "Personnes", False, "Enseignants, qualifications, compatibilités."),
    NavEntry("planning", "Planning", "Vie scolaire", False, "Emplois du temps, séances, remplacements."),
    NavEntry("attendance", "Présences", "Vie scolaire", False, "Présences, retards, convocations, QR."),
    NavEntry("finance", "Finance", "Gestion", False, "Factures, paiements, trésorerie."),
    NavEntry("payroll", "Paie", "Gestion", False, "Taux, périodes, paies, versements."),
    NavEntry("communication", "Communication", "Gestion", False, "Messagerie, forum, réclamations."),
    NavEntry("documents", "Documents", "Gestion", False, "Bulletins, reçus, cartes, emplois du temps PDF."),
]

#!/bin/sh
# Start command of the public demo API on Render (render.yaml, ADR 0033).
# A script rather than an inline `sh -c "…"`: Render quotes the arguments of
# dockerCommand itself, so an inline chain reached the shell as ONE word
# ("…: not found", exit 127). Stops at the first failing step (set -e).
set -eu

python manage.py migrate --noinput

# The fictitious demo data (seed_isbree --demo, idempotent, never deletes).
# Render cancels a deploy whose service does not open its port in time, and the
# first complete run is long against the remote database: run synchronously,
# it was cancelled again and again (the old instance kept serving).
#
# - The demo essentials already exist (school, the four demo accounts, a
#   verified child, enrolled pupils: seed_isbree --check-demo): the API starts
#   at once and the seed completes the rest in the background, in small
#   transactions (an interrupted run keeps its work, the next start resumes).
#   Its outcome is logged: "seed_isbree terminé" or "ERREUR : seed_isbree".
# - They do not exist (new database): the seed runs BEFORE the API starts; if
#   it fails, the start fails, rather than an API that looks ready but refuses
#   every login.
if python manage.py seed_isbree --check-demo; then
    (
        if python manage.py seed_isbree --demo --images seed-images; then
            echo "seed_isbree terminé : données de démonstration à jour."
        else
            echo "ERREUR : seed_isbree --demo --images a échoué (trace ci-dessus) ; l'API sert les données existantes." >&2
        fi
    ) &
else
    echo "Données de démonstration absentes : seed complet avant le démarrage de l'API."
    python manage.py seed_isbree --demo --images seed-images
fi
exec daphne -b 0.0.0.0 -p "${PORT:-10000}" config.asgi:application

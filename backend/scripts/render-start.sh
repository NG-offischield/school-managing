#!/bin/sh
# Start command of the public demo API on Render (render.yaml, ADR 0033).
# A script rather than an inline `sh -c "…"`: Render quotes the arguments of
# dockerCommand itself, so an inline chain reached the shell as ONE word
# ("…: not found", exit 127). Stops at the first failing step (set -e).
set -eu

python manage.py migrate --noinput
# Idempotent: creates the fictitious demo data once, then only completes them
# (dated sessions and attendance around today) and puts back the illustration
# files (seed-images/) that a restart without persistent disk erased. With
# existing data it only reads (~150 queries); the first, longer run commits step
# by step, so a start cut short is resumed by the next one. On failure, the API
# starts ONLY if what the demo cannot work without is already there (school,
# the four demo accounts, a verified child...): it keeps serving the existing
# data, with the error in the logs. Otherwise the start fails, rather than an
# API that looks ready but refuses every login.
if ! python manage.py seed_isbree --demo --images seed-images; then
    echo "ERREUR : seed_isbree --demo --images a échoué (trace ci-dessus)." >&2
    python manage.py seed_isbree --check-demo
    echo "AVERTISSEMENT : démarrage avec les données de démonstration existantes, sans la mise à jour du seed." >&2
fi
exec daphne -b 0.0.0.0 -p "${PORT:-10000}" config.asgi:application

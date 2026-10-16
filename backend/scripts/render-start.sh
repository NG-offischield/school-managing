#!/bin/sh
# Start command of the public demo API on Render (render.yaml, ADR 0033).
# A script rather than an inline `sh -c "…"`: Render quotes the arguments of
# dockerCommand itself, so an inline chain reached the shell as ONE word
# ("…: not found", exit 127). Stops at the first failing step (set -e).
set -eu

python manage.py migrate --noinput
# Idempotent: creates the fictitious demo data once, then changes nothing.
python manage.py seed_isbree --demo
exec daphne -b 0.0.0.0 -p "${PORT:-10000}" config.asgi:application

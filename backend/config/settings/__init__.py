"""Settings are split per environment (spec §14, Phase 1 step 2).

- base.py         shared configuration, no environment-specific values
- development.py  local / LAN demo
- production.py   hardened settings (secure cookies, no DEBUG)
- test.py         pytest configuration

Select one with DJANGO_SETTINGS_MODULE, e.g. `config.settings.development`.
"""

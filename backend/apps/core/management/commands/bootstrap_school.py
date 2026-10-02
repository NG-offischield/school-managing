"""Create the operational school and its first super-administrator.

Spec §9: "No public admin signup". The very first administrator therefore has
to be created by someone with shell access to the server (a controlled
environment), through this command — there is deliberately NO equivalent HTTP
route:

    docker compose exec web python manage.py bootstrap_school \
        --code LYC-DLA --name "Lycée de Douala" --city Douala --address "Akwa" \
        --admin-username admin --admin-email admin@example.cm \
        --admin-first-name Jean --admin-last-name Dupont

Password handling:
- asked interactively (hidden input, typed twice). Never accepted as a
  command-line argument, where it would end up in the shell history and in the
  process list;
- or, for automated setups only, read from BOOTSTRAP_ADMIN_PASSWORD (remove it
  from the environment afterwards);
- validated against AUTH_PASSWORD_VALIDATORS, hashed with Argon2, never
  printed nor logged.

Second run: the command only bootstraps an EMPTY installation. If a school
already exists it refuses, changes nothing, exits with an error and records a
BOOTSTRAP_REJECTED security event. Adding further schools (multi-tenant) will
be a separate, explicitly designed operation (see ADR 0006).
"""

import getpass
import os
import sys

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from apps.accounts.models import SecurityEventType, SecuritySeverity, User
from apps.accounts.services import ClientContext, record_security_event
from apps.core.models import School
from apps.core.services import FirstAdmin, SchoolProvisioningService

PASSWORD_ENV_VAR = "BOOTSTRAP_ADMIN_PASSWORD"  # noqa: S105 - variable name, not a secret
CLI_CONTEXT = ClientContext(ip_address=None, user_agent="manage.py bootstrap_school")


class Command(BaseCommand):
    help = "Create the first school (tenant) and its first SUPER_ADMIN. Refuses to run twice."

    def add_arguments(self, parser):
        parser.add_argument("--code", required=True)
        parser.add_argument("--name", required=True)
        parser.add_argument("--city", required=True)
        parser.add_argument("--address", required=True)
        parser.add_argument("--admin-username", required=True)
        parser.add_argument("--admin-email", required=True)
        parser.add_argument("--admin-first-name", required=True)
        parser.add_argument("--admin-last-name", required=True)

    # -- helpers ----------------------------------------------------------------

    def _reject(self, reason, message, **metadata):
        # Immediate write on the security_log connection: survives the rollback
        # caused by the CommandError raised just after (ADR 0005).
        record_security_event(
            SecurityEventType.BOOTSTRAP_REJECTED,
            ctx=CLI_CONTEXT,
            severity=SecuritySeverity.WARNING,
            reason=reason,
            **metadata,
        )
        raise CommandError(message)

    def _read_password(self, user):
        password = os.environ.get(PASSWORD_ENV_VAR)
        if not password:
            if not sys.stdin.isatty():
                # Without a terminal getpass would block or read garbage.
                raise CommandError(f"No terminal available: set {PASSWORD_ENV_VAR} for non-interactive use.")
            password = getpass.getpass("Admin password: ")
            if password != getpass.getpass("Admin password (again): "):
                raise CommandError("Passwords do not match.")
        try:
            password_validation.validate_password(password, user)
        except ValidationError as exc:
            # Validator messages describe the rule, never echo the password.
            raise CommandError(" ".join(exc.messages)) from exc
        return password

    # -- command ----------------------------------------------------------------

    @transaction.atomic
    def handle(self, *args, **opts):
        if School.objects.exists():
            self._reject(
                "ALREADY_BOOTSTRAPPED",
                "This installation already has a school: bootstrap refused, nothing was changed.",
                requested_code=opts["code"],
            )
        if User.objects.filter(
            Q(username__iexact=opts["admin_username"]) | Q(email__iexact=opts["admin_email"])
        ).exists():
            self._reject(
                "ADMIN_ALREADY_EXISTS",
                "A user with this username or email already exists: bootstrap refused.",
                requested_username=opts["admin_username"],
            )

        admin_spec = dict(
            username=opts["admin_username"],
            email=opts["admin_email"],
            first_name=opts["admin_first_name"],
            last_name=opts["admin_last_name"],
        )
        # Read (and validate) before writing anything: a bad password leaves
        # no partial data. The unsaved User only feeds the similarity validator.
        password = self._read_password(User(**admin_spec))

        try:
            provisioned = SchoolProvisioningService().provision(
                code=opts["code"],
                name=opts["name"],
                city=opts["city"],
                address=opts["address"],
                admin=FirstAdmin(password=password, **admin_spec),
            )
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc

        school, admin = provisioned.school, provisioned.admin_membership.user
        record_security_event(
            SecurityEventType.BOOTSTRAP_COMPLETED,
            user=admin,
            school=school,
            ctx=CLI_CONTEXT,
            after_commit=True,
            school_code=school.code,
        )
        self.stdout.write(self.style.SUCCESS(f"School {school.code} and SUPER_ADMIN {admin.username} created."))

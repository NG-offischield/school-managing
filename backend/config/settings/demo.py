"""Public demonstration (pre-production) settings — ADR 0033.

The production hardening (DEBUG off, HTTPS, secure cookies, HSTS) plus what
a PUBLIC demo with shared, fictitious accounts needs:

- a dedicated database holding fictitious data only (never the development
  `school` database), over TLS (POSTGRES_SSLMODE=require);
- the demonstration accounts are read-only (common/demo.py);
- `seed_isbree --demo` is allowed (it is refused with the production settings)
  and requires an administrator password distinct from the shared one.

Never use these settings for a real opening to families.
"""

import os

from .production import *  # noqa: F403

ISBREE_PUBLIC_DEMO = True

# Render (and similar hosts) expose the public host name of the service.
if os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS = [*ALLOWED_HOSTS, os.environ["RENDER_EXTERNAL_HOSTNAME"]]  # noqa: F405

# The platform health check reaches the service over plain HTTP internally.
SECURE_REDIRECT_EXEMPT = [r"^api/v1/health/$"]

# Accounts whose (published) credentials are shared with visitors.
DEMO_READ_ONLY_ACCOUNTS = env.list(  # noqa: F405
    "DEMO_READ_ONLY_ACCOUNTS",
    default=[
        "parent.demo@isbree.test",
        "enseignant.demo@isbree.test",
        "personnel.demo@isbree.test",
        "gardien.demo@isbree.test",
    ],
)
MIDDLEWARE = [*MIDDLEWARE, "common.demo.DemoReadOnlyMiddleware"]  # noqa: F405

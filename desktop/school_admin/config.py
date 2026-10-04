"""Desktop configuration.

Backend URL, by priority:
    1. environment variable SCHOOL_ADMIN_API_URL
    2. `api_url` in the user config file (see config_dir(): desktop.json)
    3. default http://127.0.0.1:8000/api/v1/ (development backend)

Nothing secret lives here: no password, no token (tokens: auth/token_store).
"""

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_API_URL = "http://127.0.0.1:8000/api/v1/"
APP_DIR_NAME = "SchoolManagingDesktop"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def config_dir():
    """Per-user directory (no secret inside): %APPDATA% on Windows."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_DIR_NAME


@dataclass(frozen=True)
class AppConfig:
    api_url: str = DEFAULT_API_URL
    timeout: float = 10.0
    language: str = "fr"

    @property
    def insecure_transport(self):
        """Plain HTTP to another machine: credentials would cross the LAN
        unencrypted. Accepted for development, flagged on the login screen."""
        parsed = urlparse(self.api_url)
        return parsed.scheme != "https" and parsed.hostname not in LOCAL_HOSTS


def _normalise(url):
    url = url.strip()
    return url if url.endswith("/") else url + "/"


def load_config(env=None, directory=None):
    env = os.environ if env is None else env
    directory = directory or config_dir()
    values = {}
    path = Path(directory) / "desktop.json"
    if path.exists():
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            values = {}
    api_url = env.get("SCHOOL_ADMIN_API_URL") or values.get("api_url") or DEFAULT_API_URL
    timeout = float(env.get("SCHOOL_ADMIN_TIMEOUT") or values.get("timeout") or 10.0)
    return AppConfig(api_url=_normalise(api_url), timeout=timeout, language=values.get("language", "fr"))

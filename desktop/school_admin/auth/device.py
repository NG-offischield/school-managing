"""Device description sent at login (backend DeviceSerializer).

The install identifier is a random UUID created once and kept in the user
config directory; the backend only stores an HMAC of it. It identifies the
installation (session list, "log out this device"), it is not a secret.
"""

import platform
import sys
import uuid
from pathlib import Path

from .. import __version__
from ..config import config_dir

_PLATFORMS = {"win32": "WINDOWS", "darwin": "MACOS"}


def install_identifier(directory=None):
    path = Path(directory or config_dir()) / "device_id"
    try:
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    except OSError:
        pass
    value = str(uuid.uuid4())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    except OSError:
        pass  # read-only profile: a per-run identifier still works
    return value


def device_info(directory=None):
    return {
        "identifier": install_identifier(directory),
        "device_name": (platform.node() or "Poste d'administration")[:120],
        "device_type": "DESKTOP",
        "platform": _PLATFORMS.get(sys.platform, "LINUX"),
        "os_version": f"{platform.system()} {platform.release()}"[:80],
        "app_version": __version__,
    }

"""Mutation check of the mobile protections of the gate and of the network
permissions (ADR 0028 / 0029). Same principle as backend/tools/mutation_check.py:
each mutation removes ONE protection from the Dart code, runs the Flutter
tests of the package, and expects them to FAIL ("killed"). The source file
is always restored.

    python mobile/tools/mutation_check.py            (from the repository root)
    FLUTTER=C:\\src\\flutter\\bin\\flutter.bat python mobile/tools/mutation_check.py

The server-side rules of the QR (school, revoked, year, enrolment, role,
"my scans only") are covered by `backend/tools/mutation_check.py gate`.
Exit code 0 only if every mutation is killed.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

MOBILE = Path(__file__).resolve().parents[1]
CORE = "packages/school_core"
GUARDIAN = "apps/guardian"

# (label, package whose tests must fail, file, original, mutated)
MUTATIONS = [
    # --- QR control (client side: only a student card leaves the phone) -------
    (
        "QR control: any QR content (URL, Wi-Fi code...) is sent to the server",
        GUARDIAN,
        f"{CORE}/lib/src/ui/gate.dart",
        "bool looksLikeQrToken(String value) => RegExp(r'^[A-Za-z0-9_-]{16,256}$').hasMatch(value.trim());",
        "bool looksLikeQrToken(String value) => value.trim().isNotEmpty;",
    ),
    (
        "double scan: the camera keeps reading after the first valid card",
        GUARDIAN,
        f"{GUARDIAN}/lib/presentation/camera/camera_scan_screen.dart",
        "    if (_done || _state != _State.scanning) return;\n    final value = raw.trim();",
        "    if (_state != _State.scanning) return;\n    final value = raw.trim();",
    ),
    (
        "double scan: the same card answered a moment ago is sent again",
        GUARDIAN,
        f"{CORE}/lib/src/ui/gate.dart",
        "    return token == _lastToken && at != null && _clock().difference(at) < window;",
        "    return false;",
    ),
    (
        "double scan: two submissions at the same time",
        CORE,
        f"{CORE}/lib/src/ui/gate.dart",
        "    if (_busy || isRepeat(token)) return false;",
        "    if (isRepeat(token)) return false;",
    ),
    # --- permissions -----------------------------------------------------------
    (
        "permission: Android 17 local network access never asked",
        CORE,
        f"{CORE}/lib/src/config/local_network.dart",
        "  bool get blocked => required && !granted;",
        "  bool get blocked => false;",
    ),
    (
        "permission: local network permission asked on Android 10-16 too",
        CORE,
        f"{CORE}/lib/src/config/local_network.dart",
        "    if (!needsLocalNetwork(widget.config)) return _set(LocalNetworkStatus.notRequired);",
        "",
    ),
    (
        "permission: refused camera treated as a generic failure (no settings, no explanation)",
        GUARDIAN,
        f"{GUARDIAN}/lib/presentation/camera/camera_scan_screen.dart",
        "          QrCameraFailure.permissionDenied => _State.denied,",
        "          QrCameraFailure.permissionDenied => _State.failed,",
    ),
    (
        "permission: camera kept running in the background (not re-checked on return)",
        GUARDIAN,
        f"{GUARDIAN}/lib/presentation/camera/camera_scan_screen.dart",
        "          _paused = true;\n          _timer?.cancel();\n          _camera.stop();",
        "          _timer?.cancel();",
    ),
    (
        "permission: the system dialog is asked again in a loop (seen on Android 10)",
        GUARDIAN,
        f"{GUARDIAN}/lib/presentation/camera/camera_scan_screen.dart",
        "        if (_paused) {\n          _paused = false;",
        "        if (_paused || _state == _State.denied) {\n          _paused = false;",
    ),
    # --- network configuration -------------------------------------------------
    (
        "network: clear text accepted towards a public address",
        CORE,
        f"{CORE}/lib/src/config/app_config.dart",
        "    if (!isPrivateHost(uri.host)) {",
        "    if (false) {",
    ),
    (
        "network: the WebSocket (and its token) may go to another host",
        CORE,
        f"{CORE}/lib/src/config/app_config.dart",
        "      if (parsed.host != api.host) {",
        "      if (false) {",
    ),
]


def flutter():
    return (
        os.environ.get("FLUTTER")
        or shutil.which("flutter")
        or shutil.which("flutter.bat")
        or "flutter"
    )


def run_tests(package):
    return subprocess.run(  # fixed argument list, no external input
        [flutter(), "test", "--no-pub"],
        cwd=MOBILE / package,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=sys.platform == "win32",  # flutter is a .bat on Windows
    ).returncode


def main():
    for package in sorted({m[1] for m in MUTATIONS}):
        if run_tests(package) != 0:
            print(f"The tests of {package} fail WITHOUT mutation: fix them first.")
            return 2
    survivors = 0
    for label, package, relative, original, mutated in MUTATIONS:
        path = MOBILE / relative
        raw = path.read_bytes()  # bytes: line endings restored exactly (Windows)
        source = raw.decode("utf-8")
        if source.count(original) != 1:
            print(f"[ERROR ] {label}: target not found exactly once in {relative}")
            survivors += 1
            continue
        try:
            path.write_bytes(source.replace(original, mutated).encode("utf-8"))
            killed = run_tests(package) != 0
        finally:
            path.write_bytes(raw)  # always restored
        survivors += 0 if killed else 1
        print(f"[{'KILLED' if killed else 'SURVIVED'}] {label}")
    print(f"{len(MUTATIONS) - survivors}/{len(MUTATIONS)} mutations killed")
    return 0 if survivors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

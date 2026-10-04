import os

import httpx
import pytest

# UI tests run without a display.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from school_admin.api import ApiClient  # noqa: E402
from school_admin.auth.session import AuthService  # noqa: E402
from school_admin.auth.token_store import MemoryTokenStore  # noqa: E402

from .fake_backend import PASSWORD, FakeBackend  # noqa: E402

DEVICE = {
    "identifier": "test-install",
    "device_name": "Poste de test",
    "device_type": "DESKTOP",
    "platform": "WINDOWS",
    "os_version": "test",
    "app_version": "0.1.0",
}


@pytest.fixture
def backend():
    return FakeBackend()


@pytest.fixture
def api(backend):
    client = ApiClient("http://testserver/api/v1/", transport=httpx.MockTransport(backend))
    yield client
    client.close()


@pytest.fixture
def vault():
    return MemoryTokenStore()  # stands in for the OS keyring


@pytest.fixture
def auth(api, vault):
    return AuthService(api, DEVICE, persistent_store=vault)


@pytest.fixture
def logged_in(auth):
    auth.login("admin", PASSWORD)
    return auth

"""HTTP client of the Django API — the desktop's ONLY way to reach data.

- envelope: `{success, data, message, meta}` unwrapped into (data, meta);
- authentication: `Authorization: Bearer <access token>` (backend tokens);
  the access token lives in memory only;
- on a 401 the client asks its `refresh_handler` once (token rotation) and
  replays the request; if that fails, `Unauthorized` reaches the UI, which
  goes back to the login screen;
- offline / timeout become NetworkError / RequestTimeout (never a crash);
- no business rule here: the server decides, the client relays.
"""

import threading

import httpx

from .. import __version__
from .errors import NetworkError, RequestTimeout, ServerError, Unauthorized, error_for


class ApiClient:
    PAGE_SIZE = 100  # backend max_page_size

    def __init__(self, base_url, *, timeout=10.0, language="fr", transport=None):
        self._http = httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(timeout, connect=min(timeout, 5.0)),
            transport=transport,
            headers={
                "Accept": "application/json",
                "Accept-Language": language,
                "User-Agent": f"SchoolAdminDesktop/{__version__}",
            },
        )
        self.access_token = None
        self.refresh_handler = None  # callable() -> bool, set by AuthService
        self._lock = threading.Lock()  # one refresh at a time (worker threads)

    def close(self):
        self._http.close()

    # --- core ------------------------------------------------------------------

    def request(
        self, method, path, *, json=None, params=None, files=None, data=None, raw=False, auth=True, _retry=True
    ):
        """`files`: multipart upload; `raw=True`: return the response bytes
        (images) instead of the unwrapped envelope."""
        headers = {}
        if auth:
            if not self.access_token:
                raise Unauthorized()
            headers["Authorization"] = f"Bearer {self.access_token}"
        try:
            response = self._http.request(
                method, path, json=json, params=params, files=files, data=data, headers=headers
            )
        except httpx.TimeoutException:
            raise RequestTimeout() from None
        except httpx.TransportError:
            raise NetworkError() from None
        if response.status_code == 401 and auth and _retry and self._try_refresh():
            return self.request(
                method, path, json=json, params=params, files=files, data=data, raw=raw, auth=auth, _retry=False
            )
        if raw and response.status_code < 400:
            return response.content
        try:
            body = response.json() if response.content else {}
        except ValueError:
            if response.status_code >= 500:
                raise ServerError(status=response.status_code) from None
            body = {}
        if response.status_code >= 400 or (isinstance(body, dict) and body.get("success") is False):
            raise error_for(response.status_code, body)
        return body.get("data"), body.get("meta") or {}

    def _try_refresh(self):
        if self.refresh_handler is None:
            return False
        with self._lock:
            try:
                return bool(self.refresh_handler())
            except Exception:  # a failed refresh simply means "log in again"
                return False

    # --- helpers ---------------------------------------------------------------

    def get(self, path, **params):
        return self.request("GET", path, params={k: v for k, v in params.items() if v is not None})[0]

    def post(self, path, payload=None):
        return self.request("POST", path, json=payload or {})[0]

    def patch(self, path, payload):
        return self.request("PATCH", path, json=payload)[0]

    def delete(self, path):
        return self.request("DELETE", path)[0]

    def page(self, path, *, page=1, page_size=50, **params):
        """One page of a paginated list: (rows, total count)."""
        params = {k: v for k, v in params.items() if v is not None}
        data, meta = self.request("GET", path, params={**params, "page": page, "page_size": page_size})
        return data or [], meta.get("count", len(data or []))

    def upload(self, path, field, content, *, filename, content_type):
        """Multipart POST of `content` (bytes). Only the bytes and a neutral
        file name leave the computer — never a local path."""
        return self.request("POST", path, files={field: (filename, content, content_type)})[0]

    def post_multipart(self, path, fields, files):
        """Multipart POST of form `fields` and `files` [(field, (name, bytes, type))]:
        only the bytes and the bare file name leave the computer, never a local path."""
        return self.request("POST", path, data=fields, files=files)[0]

    def get_bytes(self, path):
        return self.request("GET", path, raw=True)

    def list_all(self, path, **params):
        """Every row of a paginated list (follows `meta.next`)."""
        params = {k: v for k, v in params.items() if v is not None}
        rows, page = [], 1
        while True:
            data, meta = self.request("GET", path, params={**params, "page": page, "page_size": self.PAGE_SIZE})
            rows.extend(data or [])
            if not meta.get("next"):
                return rows
            page += 1

    def count(self, path, **params):
        """Number of rows of a paginated list, without downloading them."""
        params = {k: v for k, v in params.items() if v is not None}
        data, meta = self.request("GET", path, params={**params, "page_size": 1})
        return meta.get("count", len(data or []))

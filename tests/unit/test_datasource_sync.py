"""
Unit tests for monitor_exporter/datasource_sync.py — the pure helpers.

Covers the two functions that have no network/DB dependency:
  - _to_grafana_payload: translates `datasource` table rows to the JSON
    Grafana's /api/datasources accepts.
  - _diff: decides whether a PUT is needed to align Grafana with a row.

These are exactly the kind of pure mapping/comparison functions that
silently break under refactoring — covering them prevents subtle bugs
like a SQL data source getting an `http://` prefix added to its host
(which Grafana then rejects with a confusing error).
"""
import os
from unittest.mock import patch

import httpx
import datasource_sync as ds


# ---------------------------------------------------------------------------
# _to_grafana_payload
# ---------------------------------------------------------------------------

def test_payload_basic_shape():
    """name → uid mapping, access=proxy, jsonData={} defaults."""
    row = {
        "name": "demo-pg", "type": "postgres", "url": "db.example.com:5432",
        "database_name": "app", "db_user": "ro", "password_env": None,
    }
    p = ds._to_grafana_payload(row)
    assert p["name"] == "demo-pg"
    assert p["uid"] == "demo-pg"            # uid mirrors name
    assert p["type"] == "postgres"
    assert p["access"] == "proxy"
    assert p["isDefault"] is False
    assert p["jsonData"] == {}
    assert p["database"] == "app"
    assert p["user"] == "ro"
    assert "secureJsonData" not in p        # no password env → no secret


def test_payload_sql_driver_keeps_raw_host_port():
    """mysql + postgres get host:port as-is (no http:// prefix)."""
    for driver in ("mysql", "postgres"):
        row = {"name": "d", "type": driver, "url": "db.example.com:5432",
               "database_name": "", "db_user": "", "password_env": None}
        assert ds._to_grafana_payload(row)["url"] == "db.example.com:5432"


def test_payload_non_sql_driver_prepends_http():
    """loki / prometheus etc. get an http:// prefix if missing."""
    row = {"name": "d", "type": "loki", "url": "loki.example.com:3100",
           "database_name": "", "db_user": "", "password_env": None}
    assert ds._to_grafana_payload(row)["url"] == "http://loki.example.com:3100"


def test_payload_non_sql_driver_preserves_explicit_http_scheme():
    """If the URL already has a scheme, leave it alone."""
    row = {"name": "d", "type": "loki", "url": "https://loki.example.com",
           "database_name": "", "db_user": "", "password_env": None}
    assert ds._to_grafana_payload(row)["url"] == "https://loki.example.com"


def test_payload_password_injected_from_env_when_present():
    row = {"name": "d", "type": "postgres", "url": "h:1",
           "database_name": "", "db_user": "u",
           "password_env": "MY_DS_PASSWORD"}
    with patch.dict(os.environ, {"MY_DS_PASSWORD": "s3cr3t"}, clear=False):
        p = ds._to_grafana_payload(row)
    assert p["secureJsonData"] == {"password": "s3cr3t"}


def test_payload_no_secret_when_env_var_unset():
    """`password_env` references an unset env var → no secret key emitted."""
    row = {"name": "d", "type": "postgres", "url": "h:1",
           "database_name": "", "db_user": "",
           "password_env": "DEFINITELY_UNSET_VAR_XYZ"}
    env = {k: v for k, v in os.environ.items() if k != "DEFINITELY_UNSET_VAR_XYZ"}
    with patch.dict(os.environ, env, clear=True):
        p = ds._to_grafana_payload(row)
    assert "secureJsonData" not in p


def test_payload_missing_optional_fields_default_to_empty_string():
    """Postgres returns None for nullable columns; payload must serialise to ''
    so Grafana doesn't see `null` and reject the request."""
    row = {"name": "d", "type": "postgres", "url": "h:1",
           "database_name": None, "db_user": None, "password_env": None}
    p = ds._to_grafana_payload(row)
    assert p["database"] == ""
    assert p["user"] == ""


# ---------------------------------------------------------------------------
# _diff
# ---------------------------------------------------------------------------

def test_diff_identical_returns_false():
    payload = existing = {"type": "postgres", "url": "h:1", "database": "app", "user": "ro"}
    assert ds._diff(payload, existing) is False


def test_diff_url_change_returns_true():
    payload = {"type": "postgres", "url": "new-host:5432", "database": "app", "user": "ro"}
    existing = {"type": "postgres", "url": "old-host:5432", "database": "app", "user": "ro"}
    assert ds._diff(payload, existing) is True


def test_diff_type_change_returns_true():
    """Changing driver (e.g. postgres → mysql) MUST trigger a re-PUT."""
    payload = {"type": "mysql", "url": "h:1", "database": "app", "user": "ro"}
    existing = {"type": "postgres", "url": "h:1", "database": "app", "user": "ro"}
    assert ds._diff(payload, existing) is True


def test_diff_user_change_returns_true():
    payload = {"type": "postgres", "url": "h:1", "database": "app", "user": "new"}
    existing = {"type": "postgres", "url": "h:1", "database": "app", "user": "old"}
    assert ds._diff(payload, existing) is True


def test_diff_missing_keys_treated_as_empty():
    """Grafana sometimes omits empty fields; payload may include them → treat
    missing/None/empty-string as equivalent so we don't infinite-loop on PUTs."""
    payload = {"type": "postgres", "url": "h:1", "database": "", "user": ""}
    existing = {"type": "postgres", "url": "h:1"}     # missing database + user
    assert ds._diff(payload, existing) is False


def test_diff_ignores_uid_and_access_and_jsondata():
    """_diff only compares the 4 fields users can meaningfully edit — other
    fields like uid, access, jsonData are constant in this codebase."""
    payload = {"type": "postgres", "url": "h:1", "database": "app", "user": "ro",
               "uid": "new-uid", "access": "direct", "jsonData": {"x": 1}}
    existing = {"type": "postgres", "url": "h:1", "database": "app", "user": "ro",
                "uid": "old-uid", "access": "proxy", "jsonData": {}}
    assert ds._diff(payload, existing) is False


# ---------------------------------------------------------------------------
# sync_once — error paths
# ---------------------------------------------------------------------------

def _row():
    return {"name": "d", "type": "postgres", "url": "h:1",
            "database_name": "app", "db_user": "ro", "password_env": None}


class _FakeResp:
    def __init__(self, code, body=None):
        self.status_code = code
        self._body = body if body is not None else []
        self.text = ""
    def json(self):
        return self._body


class _FakeClient:
    """Records calls so the test can assert no POST/PUT happened."""
    def __init__(self, get_result):
        self._get_result = get_result   # FakeResp or Exception instance to raise
        self.posts: list = []
        self.puts: list = []
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def get(self, _path):
        if isinstance(self._get_result, Exception):
            raise self._get_result
        return self._get_result
    def post(self, *a, **kw): self.posts.append((a, kw)); return _FakeResp(201)
    def put(self, *a, **kw):  self.puts.append((a, kw));  return _FakeResp(200)


def test_sync_once_skips_when_grafana_api_returns_non_200():
    """Grafana returning 503 must not crash the cycle and must not write."""
    client = _FakeClient(_FakeResp(503))
    with patch.object(ds, "_list_table", lambda _cfg: [_row()]), \
         patch.object(ds, "_grafana_client", lambda _url: client):
        ds.sync_once({"enabled": True}, "http://grafana:3000")
    assert client.posts == []
    assert client.puts == []


def test_sync_once_swallows_grafana_request_error():
    """A network error (DNS/connect/timeout) is logged and the cycle returns."""
    client = _FakeClient(httpx.RequestError("boom"))
    with patch.object(ds, "_list_table", lambda _cfg: [_row()]), \
         patch.object(ds, "_grafana_client", lambda _url: client):
        ds.sync_once({"enabled": True}, "http://grafana:3000")
    assert client.posts == []
    assert client.puts == []


def test_sync_once_no_rows_returns_without_touching_grafana():
    """Empty `datasource` table → no Grafana call at all (defensive)."""
    called = {"n": 0}
    def fake_client(_url):
        called["n"] += 1
        return _FakeClient(_FakeResp(200))
    with patch.object(ds, "_list_table", lambda _cfg: []), \
         patch.object(ds, "_grafana_client", fake_client):
        ds.sync_once({"enabled": True}, "http://grafana:3000")
    assert called["n"] == 0

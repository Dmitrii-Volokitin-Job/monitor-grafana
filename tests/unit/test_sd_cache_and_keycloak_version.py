"""
Unit tests for two narrowly-scoped helpers whose existing coverage was thin:

  - sd_endpoints.cached_fetch  — per-key TTL caching for the /sd/<type> endpoints.
    The base happy-path test exists but cache expiry and per-key isolation
    have never been exercised. A bug in either would manifest as Prometheus
    occasionally seeing stale targets (TTL bug) or all targets returning the
    same payload regardless of type (key-isolation bug).

  - exporter._extract_keycloak_version — extracted from check_keycloak in the
    REFACTORING slot. Indirect coverage via check_keycloak exists; direct tests
    pin the contract so future regressions show up against this helper, not
    deep inside check_keycloak.
"""
import time
from types import SimpleNamespace
from unittest.mock import patch

import sd_endpoints
from monitor_exporter.exporter import _extract_keycloak_version


# ============================================================================
# sd_endpoints.cached_fetch — TTL + per-key isolation
# ============================================================================

class _FakeConn:
    def __init__(self, rows): self._rows = rows
    def cursor(self):
        return self
    def __enter__(self): return self
    def __exit__(self, *a): pass
    def execute(self, *a, **k): pass
    def fetchall(self): return self._rows
    def close(self): pass


_ROW = {
    "system_id": "demo-a-api", "display_name": "demo",
    "system_group": "demo-lab-a", "url": "https://httpbin.org/status/200",
    "blackbox_module": "http_2xx",
    "node_id": None, "node_name": None, "lab_group": None, "node_type": None,
    "cert_alias": None, "cert_description": None,
}


def _patch_connect(call_counter):
    def connect(cfg):
        call_counter["n"] += 1
        return _FakeConn([_ROW])
    return patch.object(sd_endpoints, "_connect", connect)


def test_cached_fetch_expires_after_ttl():
    """Second call within TTL hits the cache; call after TTL re-queries DB."""
    sd_endpoints._cache.clear()
    counter = {"n": 0}
    with _patch_connect(counter):
        sd_endpoints.cached_fetch("http", {})        # miss (DB call #1)
        sd_endpoints.cached_fetch("http", {})        # hit
        assert counter["n"] == 1
        # Force cache expiry by rewinding the stored expires_at into the past.
        # NOTE: cached_fetch uses time.monotonic() — not time.time() — for TTL.
        expires_at, payload = sd_endpoints._cache["http"]
        sd_endpoints._cache["http"] = (time.monotonic() - 1, payload)
        sd_endpoints.cached_fetch("http", {})        # expired → re-query (DB call #2)
    assert counter["n"] == 2, "cache should re-query after TTL expiry"


def test_cached_fetch_isolates_keys_per_sd_type():
    """The /sd/http cache must not leak into /sd/tcp (and vice versa)."""
    sd_endpoints._cache.clear()
    counter = {"n": 0}
    with _patch_connect(counter):
        sd_endpoints.cached_fetch("http", {})
        sd_endpoints.cached_fetch("tcp",  {})
        sd_endpoints.cached_fetch("http", {})        # http still cached
        sd_endpoints.cached_fetch("tcp",  {})        # tcp still cached
    assert counter["n"] == 2, "each sd_type gets its own cache slot"


def test_cached_fetch_unknown_type_raises_keyerror():
    """An sd_type not in _MAPPERS must propagate KeyError, not return stale data."""
    sd_endpoints._cache.clear()
    import pytest
    with pytest.raises(KeyError):
        sd_endpoints.cached_fetch("nonexistent-type", {})


# ============================================================================
# exporter._extract_keycloak_version — version-extraction heuristics
# ============================================================================

def _fake_response(headers: dict):
    return SimpleNamespace(headers=headers)


def test_version_from_x_keycloak_version_header_preferred():
    """X-Keycloak-Version wins over Server header when both are present."""
    resp = _fake_response({
        "X-Keycloak-Version": "22.0.1",
        "Server": "Keycloak/99.9.9",
    })
    assert _extract_keycloak_version(resp) == "22.0.1"


def test_version_from_server_header_fallback():
    """Falls back to `Server: Keycloak/<ver>` when X-Keycloak-Version is missing."""
    resp = _fake_response({"Server": "Keycloak/26.0.1"})
    assert _extract_keycloak_version(resp) == "26.0.1"


def test_version_from_server_header_case_insensitive():
    """Server header matching should be case-insensitive."""
    resp = _fake_response({"Server": "keycloak 22.0.1 (Linux x86_64)"})
    assert _extract_keycloak_version(resp) == "22.0.1"


def test_version_unknown_when_no_clue():
    """No version header and no recognisable Server string → 'unknown'."""
    resp = _fake_response({"Server": "nginx/1.25.0"})
    assert _extract_keycloak_version(resp) == "unknown"


def test_version_unknown_when_headers_empty():
    """Defensive: empty headers dict shouldn't blow up."""
    assert _extract_keycloak_version(_fake_response({})) == "unknown"


def test_version_empty_x_keycloak_header_falls_through_to_server():
    """Empty X-Keycloak-Version (some proxies strip values) → use Server header instead."""
    resp = _fake_response({"X-Keycloak-Version": "", "Server": "Keycloak/24.0.0"})
    assert _extract_keycloak_version(resp) == "24.0.0"

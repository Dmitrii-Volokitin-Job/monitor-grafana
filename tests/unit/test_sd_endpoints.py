"""Unit tests for sd_endpoints.py — the Prometheus HTTP-SD service."""
import sys
import os
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "monitor_exporter"))

import sd_endpoints  # noqa: E402

DB_CONFIG = {"enabled": True, "host": "x", "port": 0, "database": "x", "user": "x", "password": "x"}


class _FakeCursor:
    def __init__(self, rows): self._rows = rows
    def execute(self, sql, args=()): self._sql = sql; self._args = args
    def fetchall(self): return self._rows
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _FakeConn:
    def __init__(self, rows): self._rows = rows
    def cursor(self): return _FakeCursor(self._rows)
    def close(self): pass


@pytest.fixture(autouse=True)
def clear_cache():
    sd_endpoints._cache.clear()
    yield
    sd_endpoints._cache.clear()


def _patch_conn(rows):
    return patch.object(sd_endpoints, "_connect", lambda cfg: _FakeConn(rows))


def test_http_sd_shape():
    rows = [{
        "system_id": "vdcr-dev-ims", "display_name": "Demo Lab A - IMS",
        "system_group": "demo-lab-a", "url": "https://example.com/health",
        "blackbox_module": "http_2xx_or_401",
        "node_id": None, "node_name": None, "lab_group": None, "node_type": None,
        "cert_alias": None, "cert_description": None,
    }]
    with _patch_conn(rows):
        out = sd_endpoints.fetch("http", DB_CONFIG)
    assert len(out) == 1
    e = out[0]
    assert e["targets"] == ["https://example.com/health"]
    assert e["labels"]["system_id"] == "vdcr-dev-ims"
    assert e["labels"]["__param_module"] == "http_2xx_or_401"


def test_http_sd_default_module_when_missing():
    rows = [{
        "system_id": "x", "display_name": "X", "system_group": "G",
        "url": "https://x/", "blackbox_module": None,
        "node_id": None, "node_name": None, "lab_group": None, "node_type": None,
        "cert_alias": None, "cert_description": None,
    }]
    with _patch_conn(rows):
        out = sd_endpoints.fetch("http", DB_CONFIG)
    assert out[0]["labels"]["__param_module"] == "http_2xx"


def test_icmp_sd_uses_node_fields():
    rows = [{
        "system_id": "demo-a-node-1", "display_name": "Demo Lab A - Master 1",
        "system_group": "", "url": "10.0.0.10", "blackbox_module": None,
        "node_id": "demo-a-node-1", "node_name": "Demo Lab A - Master 1",
        "lab_group": "demo-lab-a", "node_type": "MASTER",
        "cert_alias": None, "cert_description": None,
    }]
    with _patch_conn(rows):
        out = sd_endpoints.fetch("icmp", DB_CONFIG)
    e = out[0]
    assert e["targets"] == ["10.0.0.10"]
    assert e["labels"]["node_id"] == "demo-a-node-1"
    assert e["labels"]["lab_group"] == "demo-lab-a"
    assert e["labels"]["node_type"] == "MASTER"


def test_ssl_sd_uses_cert_fields():
    rows = [{
        "system_id": "ssl-demo-wildcard", "display_name": "your-cluster Wildcard",
        "system_group": "SSL", "url": "app.example.com:443",
        "blackbox_module": None,
        "node_id": None, "node_name": None, "lab_group": None, "node_type": None,
        "cert_alias": "demo-wildcard", "cert_description": "Wildcard cert",
    }]
    with _patch_conn(rows):
        out = sd_endpoints.fetch("ssl", DB_CONFIG)
    assert out[0]["labels"]["cert_alias"] == "demo-wildcard"


def test_rows_without_url_are_dropped():
    rows = [{
        "system_id": "no-url", "display_name": "x", "system_group": "g",
        "url": None, "blackbox_module": None,
        "node_id": None, "node_name": None, "lab_group": None, "node_type": None,
        "cert_alias": None, "cert_description": None,
    }]
    with _patch_conn(rows):
        out = sd_endpoints.fetch("http", DB_CONFIG)
    assert out == []


def test_unknown_type_returns_404_via_blueprint():
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(sd_endpoints.create_blueprint(DB_CONFIG))
    client = app.test_client()
    r = client.get("/sd/bogus")
    assert r.status_code == 404


def test_unknown_type_404_body_names_the_bad_type():
    # Lock the error JSON shape — Prometheus parses /sd/* responses, so the
    # body contract matters as much as the status code.
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(sd_endpoints.create_blueprint(DB_CONFIG))
    client = app.test_client()
    r = client.get("/sd/bogus")
    body = r.get_json()
    assert "error" in body
    assert "bogus" in body["error"]


def test_healthz_returns_ok():
    # /sd/healthz is the readiness probe target in the Helm chart
    # (deployments/k8s-helm/.../monitor-exporter-deployment.yaml). Regressing
    # it would silently break K8s rollouts.
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(sd_endpoints.create_blueprint(DB_CONFIG))
    client = app.test_client()
    r = client.get("/sd/healthz")
    assert r.status_code == 200
    assert r.get_json() == {"ok": True}


def test_db_failure_returns_500_with_internal_error_body():
    # If the DB raises during /sd/<type>, the route must return 500 with a
    # generic "internal" body — and the underlying exception text MUST NOT
    # leak to Prometheus (it can contain DSN fragments, hostnames, etc.).
    from flask import Flask
    app = Flask(__name__)
    app.register_blueprint(sd_endpoints.create_blueprint(DB_CONFIG))
    client = app.test_client()
    with patch.object(sd_endpoints, "cached_fetch",
                      side_effect=RuntimeError("db down: secret-conn-string")):
        r = client.get("/sd/http")
    assert r.status_code == 500
    assert r.get_json() == {"error": "internal"}
    assert "secret-conn-string" not in r.get_data(as_text=True)


def test_cache_avoids_second_db_call():
    rows = [{
        "system_id": "x", "display_name": "X", "system_group": "G",
        "url": "https://x/", "blackbox_module": "http_2xx",
        "node_id": None, "node_name": None, "lab_group": None, "node_type": None,
        "cert_alias": None, "cert_description": None,
    }]
    call_count = {"n": 0}

    def connect(cfg):
        call_count["n"] += 1
        return _FakeConn(rows)

    with patch.object(sd_endpoints, "_connect", connect):
        a = sd_endpoints.cached_fetch("http", DB_CONFIG)
        b = sd_endpoints.cached_fetch("http", DB_CONFIG)
    assert a == b
    assert call_count["n"] == 1  # second call served from cache

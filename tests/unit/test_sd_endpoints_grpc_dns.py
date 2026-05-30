"""Coverage for the new grpc + dns mappers added to sd_endpoints."""
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "monitor_exporter"))

import sd_endpoints  # noqa: E402

DB_CONFIG = {"enabled": True, "host": "x", "port": 0, "database": "x", "user": "x", "password": "x"}


class _FakeCursor:
    def __init__(self, rows): self._rows = rows
    def execute(self, sql, args=()): pass
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


def _row(stype, **kw):
    base = {"system_id": "x", "display_name": "X", "system_group": "g",
            "url": "host:443", "blackbox_module": None,
            "node_id": None, "node_name": None, "lab_group": None, "node_type": None,
            "cert_alias": None, "cert_description": None}
    base.update(kw)
    return base


def test_grpc_default_module():
    with patch.object(sd_endpoints, "_connect", lambda c: _FakeConn([_row("GRPC")])):
        out = sd_endpoints.fetch("grpc", DB_CONFIG)
    assert out[0]["labels"]["__param_module"] == "grpc"
    assert out[0]["labels"]["system_type"] == "GRPC"


def test_grpc_explicit_module():
    with patch.object(sd_endpoints, "_connect",
                      lambda c: _FakeConn([_row("GRPC", blackbox_module="grpc_plain")])):
        out = sd_endpoints.fetch("grpc", DB_CONFIG)
    assert out[0]["labels"]["__param_module"] == "grpc_plain"


def test_dns_default_module():
    with patch.object(sd_endpoints, "_connect", lambda c: _FakeConn([_row("DNS", url="1.1.1.1")])):
        out = sd_endpoints.fetch("dns", DB_CONFIG)
    assert out[0]["labels"]["__param_module"] == "dns_udp"
    assert out[0]["targets"] == ["1.1.1.1"]

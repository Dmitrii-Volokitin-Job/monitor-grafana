"""Unit tests for Postgres / Redis / MongoDB / Elasticsearch probe functions."""
import os
import socket
import sys
import threading
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "monitor_exporter"))

# exporter.py registers global Prometheus Gauges at import time. Other test
# modules in this directory also import exporter; pytest collects them in
# alphabetical order and the duplicate registration trips here. Clear the
# default registry before our import so this module is order-independent.
if "exporter" in sys.modules:
    exporter = sys.modules["exporter"]
else:
    import prometheus_client
    for collector in list(prometheus_client.REGISTRY._collector_to_names):
        try:
            prometheus_client.REGISTRY.unregister(collector)
        except Exception:
            pass
    import exporter  # noqa: F401  (registers collectors fresh)
    exporter = sys.modules["exporter"]


# ---- A tiny TCP echo server fixture for protocol probes -----------------------

class _ReplyOnceServer:
    """Listen on an ephemeral port; reply with `reply` once, then close."""
    def __init__(self, reply: bytes):
        self.reply = reply
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        try:
            conn, _ = self.sock.accept()
            try:
                conn.recv(4096)
                if self.reply:
                    conn.sendall(self.reply)
            finally:
                conn.close()
        except Exception:
            pass

    def close(self):
        try: self.sock.close()
        except Exception: pass


# ---- check_postgres -----------------------------------------------------------

def test_postgres_auth_request_means_up():
    srv = _ReplyOnceServer(reply=b"R")    # 'R' = AuthenticationRequest
    try:
        is_up, ms, err = exporter.check_postgres("127.0.0.1", srv.port, timeout=2)
        assert is_up
        assert err == ""
        assert ms > 0
    finally:
        srv.close()


def test_postgres_error_byte_also_means_up():
    srv = _ReplyOnceServer(reply=b"E")    # 'E' = ErrorResponse
    try:
        is_up, _, _ = exporter.check_postgres("127.0.0.1", srv.port, timeout=2)
        assert is_up
    finally:
        srv.close()


def test_postgres_unknown_reply_means_down():
    srv = _ReplyOnceServer(reply=b"X")
    try:
        is_up, _, err = exporter.check_postgres("127.0.0.1", srv.port, timeout=2)
        assert not is_up
        assert "Unexpected" in err
    finally:
        srv.close()


def test_postgres_unreachable_port_means_down():
    # localhost port 1 is reserved; nothing listens
    is_up, _, err = exporter.check_postgres("127.0.0.1", 1, timeout=1)
    assert not is_up
    assert err  # some error string


# ---- check_redis --------------------------------------------------------------

def test_redis_pong_means_up():
    srv = _ReplyOnceServer(reply=b"+PONG\r\n")
    try:
        is_up, _, err = exporter.check_redis("127.0.0.1", srv.port, timeout=2)
        assert is_up
        assert err == ""
    finally:
        srv.close()


def test_redis_noauth_still_means_up():
    """A protected Redis replies '-NOAUTH Authentication required.' — we count
    that as proof of life because the server is clearly running."""
    srv = _ReplyOnceServer(reply=b"-NOAUTH Authentication required.\r\n")
    try:
        is_up, _, _ = exporter.check_redis("127.0.0.1", srv.port, timeout=2)
        assert is_up
    finally:
        srv.close()


def test_redis_garbage_reply_means_down():
    srv = _ReplyOnceServer(reply=b"this is not redis\r\n")
    try:
        is_up, _, err = exporter.check_redis("127.0.0.1", srv.port, timeout=2)
        assert not is_up
        assert "Unexpected" in err
    finally:
        srv.close()


# ---- check_mongodb ------------------------------------------------------------

def test_mongodb_tcp_connect_means_up():
    srv = _ReplyOnceServer(reply=b"")
    try:
        is_up, _, err = exporter.check_mongodb("127.0.0.1", srv.port, timeout=2)
        assert is_up
        assert err == ""
    finally:
        srv.close()


def test_mongodb_unreachable_port_means_down():
    is_up, _, err = exporter.check_mongodb("127.0.0.1", 1, timeout=1)
    assert not is_up


# ---- check_elasticsearch ------------------------------------------------------

def _es_resp(status_code: int, body: dict | None = None):
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = body or {}
    return m


def test_elasticsearch_green_means_up():
    with patch.object(exporter.requests, "get",
                      return_value=_es_resp(200, {"status": "green", "cluster_name": "test"})):
        is_up, _, status, err = exporter.check_elasticsearch("https://es/", 10)
    assert is_up
    assert status == "green"
    assert err == ""


def test_elasticsearch_red_is_still_up_but_status_red():
    with patch.object(exporter.requests, "get",
                      return_value=_es_resp(200, {"status": "red"})):
        is_up, _, status, err = exporter.check_elasticsearch("https://es/", 10)
    assert is_up
    assert status == "red"


def test_elasticsearch_500_means_down():
    with patch.object(exporter.requests, "get", return_value=_es_resp(500)):
        is_up, _, _, err = exporter.check_elasticsearch("https://es/", 10)
    assert not is_up
    assert "HTTP 500" in err


def test_elasticsearch_network_error_means_down():
    import requests as req
    with patch.object(exporter.requests, "get",
                      side_effect=req.exceptions.ConnectionError("boom")):
        is_up, _, _, err = exporter.check_elasticsearch("https://es/", 10)
    assert not is_up
    assert "boom" in err

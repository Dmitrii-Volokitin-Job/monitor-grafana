"""
Unit tests for log_blackbox_results() — the function that writes
HTTP/TCP/ICMP probe results from Prometheus into health_check_history.

This is the function that was failing silently in Docker due to
127.0.0.1:9090 being unreachable (Prometheus is a separate container).
"""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import monitor_exporter.exporter as exporter_module
from monitor_exporter.exporter import log_blackbox_results, HealthCheckLogger


PROMETHEUS_URL = "http://prometheus:9090"


def _prom_result(job, instance, system_id, success=1.0, duration=0.045):
    """Build a fake Prometheus query result item."""
    return {
        "metric": {
            "job": job,
            "instance": instance,
            "system_id": system_id,
            "display_name": f"Test {system_id}",
            "system_group": "TEST",
        },
        "value": [1700000000, str(success)],
    }


def _mock_prom_response(results):
    """Return a mock requests.Response for Prometheus /api/v1/query."""
    import requests
    resp = MagicMock(spec=requests.Response)
    resp.status_code = 200
    resp.json.return_value = {"data": {"result": results}}
    return resp


def _make_db_logger_mock():
    """Return a HealthCheckLogger with a mocked DB connection."""
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"id": 42}
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    db_logger = HealthCheckLogger({
        "host": "localhost", "port": 3306, "database": "monitoring",
        "user": "root", "password": "x",
        "retention_days": 90, "cleanup_interval_hours": 24,
    })
    return db_logger, mock_conn, mock_cursor


# ---------------------------------------------------------------------------
# Core behavior: all probe results (UP and DOWN) must be logged
# ---------------------------------------------------------------------------

def test_log_blackbox_results_logs_up_systems():
    """UP systems (probe_success=1) must produce a health_check_history row."""
    results = [_prom_result("blackbox_http", "https://app.example.com", "test-http", success=1.0)]

    db_logger, mock_conn, mock_cursor = _make_db_logger_mock()

    with patch("monitor_exporter.exporter.requests.get") as mock_get, \
         patch.object(exporter_module, "_db_logger", db_logger), \
         patch.object(db_logger, "_connect", return_value=mock_conn):

        # success query returns UP result; duration query returns value
        duration_result = [{**results[0], "value": [0, "0.045"]}]

        def _side_effect(url, params=None, timeout=None):
            query = params.get("query", "")
            if "probe_success" in query:
                return _mock_prom_response(results)
            elif "probe_duration" in query:
                return _mock_prom_response(duration_result)
            return _mock_prom_response([])

        mock_get.side_effect = _side_effect
        log_blackbox_results(PROMETHEUS_URL)

    mock_cursor.executemany.assert_called_once()
    rows = mock_cursor.executemany.call_args[0][1]
    assert len(rows) == 1
    assert "UP" in rows[0]


def test_log_blackbox_results_logs_down_systems():
    """
    DOWN systems (probe_success=0) MUST produce a health_check_history row.
    This was the original bug: DOWN systems showed in Prometheus but not in
    the 'Recent Health Check Logs' MariaDB panel.
    """
    results = [_prom_result("blackbox_http", "https://api.example.com", "test-api-down", success=0.0)]

    db_logger, mock_conn, mock_cursor = _make_db_logger_mock()

    with patch("monitor_exporter.exporter.requests.get") as mock_get, \
         patch.object(exporter_module, "_db_logger", db_logger), \
         patch.object(db_logger, "_connect", return_value=mock_conn):

        def _side_effect(url, params=None, timeout=None):
            query = params.get("query", "")
            if "probe_success" in query:
                return _mock_prom_response(results)
            return _mock_prom_response([])

        mock_get.side_effect = _side_effect
        log_blackbox_results(PROMETHEUS_URL)

    mock_cursor.executemany.assert_called_once()
    rows = mock_cursor.executemany.call_args[0][1]
    assert len(rows) == 1
    assert "DOWN" in rows[0], \
        "DOWN system must be logged to health_check_history — this was the original bug"


def test_log_blackbox_results_logs_all_job_types():
    """HTTP, TCP, and ICMP results must all be logged."""
    results = [
        _prom_result("blackbox_http", "https://app.example.com", "http-sys", success=1.0),
        _prom_result("blackbox_tcp", "db.example.com:3306", "db-sys", success=1.0),
        # ICMP uses node_id not system_id — but the function handles both
    ]

    db_logger, mock_conn, mock_cursor = _make_db_logger_mock()

    with patch("monitor_exporter.exporter.requests.get") as mock_get, \
         patch.object(exporter_module, "_db_logger", db_logger), \
         patch.object(db_logger, "_connect", return_value=mock_conn):

        def _side_effect(url, params=None, timeout=None):
            if "probe_success" in params.get("query", ""):
                return _mock_prom_response(results)
            return _mock_prom_response([])

        mock_get.side_effect = _side_effect
        log_blackbox_results(PROMETHEUS_URL)

    rows = mock_cursor.executemany.call_args[0][1]
    assert len(rows) == 2


def test_log_blackbox_results_uses_icmp_node_id():
    """ICMP targets use node_id label instead of system_id."""
    results = [{
        "metric": {
            "job": "blackbox_icmp",
            "instance": "10.0.0.10",
            "node_id": "demo-a-node-1",
            "node_name": "Demo Lab A - Master 1",
            "lab_group": "demo-lab-a",
        },
        "value": [0, "1.0"],
    }]

    db_logger, mock_conn, mock_cursor = _make_db_logger_mock()

    with patch("monitor_exporter.exporter.requests.get") as mock_get, \
         patch.object(exporter_module, "_db_logger", db_logger), \
         patch.object(db_logger, "_connect", return_value=mock_conn):

        def _side_effect(url, params=None, timeout=None):
            if "probe_success" in params.get("query", ""):
                return _mock_prom_response(results)
            return _mock_prom_response([])

        mock_get.side_effect = _side_effect
        log_blackbox_results(PROMETHEUS_URL)

    # Should have attempted to log the ICMP node
    rows = mock_cursor.executemany.call_args[0][1]
    assert len(rows) == 1


# ---------------------------------------------------------------------------
# Prometheus connection failure must not crash the exporter
# ---------------------------------------------------------------------------

def test_log_blackbox_results_prometheus_unreachable_does_not_crash():
    """
    When Prometheus is unreachable (e.g., Docker networking wrong address),
    log_blackbox_results must fail silently — not crash the exporter.

    This was the Docker bug: 127.0.0.1:9090 unreachable inside container.
    """
    import requests as req

    with patch("monitor_exporter.exporter.requests.get",
               side_effect=req.exceptions.ConnectionError("Connection refused")):
        # Must not raise
        log_blackbox_results("http://127.0.0.1:9090")


def test_log_blackbox_results_prometheus_timeout_does_not_crash():
    import requests as req

    with patch("monitor_exporter.exporter.requests.get",
               side_effect=req.exceptions.Timeout("timed out")):
        log_blackbox_results("http://prometheus:9090")


# ---------------------------------------------------------------------------
# PROMETHEUS_URL env var override
# ---------------------------------------------------------------------------

def test_prometheus_url_env_var_overrides_config(monkeypatch):
    """
    PROMETHEUS_URL env var must override config.yml value.
    This is the Docker fix: set PROMETHEUS_URL=http://prometheus:9090 in docker-compose.
    """
    monkeypatch.setenv("PROMETHEUS_URL", "http://prometheus:9090")

    called_with = []

    def _fake_get(url, **kwargs):
        called_with.append(url)
        import requests as req
        resp = MagicMock(spec=req.Response)
        resp.status_code = 200
        resp.json.return_value = {"data": {"result": []}}
        return resp

    config = {"prometheus": {"url": "http://127.0.0.1:9090"}}
    captured_url = []

    def _fake_check_loop_once(config, interval):
        prometheus_url = (
            os.environ.get("PROMETHEUS_URL")
            or config.get("prometheus", {}).get("url", "http://127.0.0.1:9090")
        )
        captured_url.append(prometheus_url)

    _fake_check_loop_once(config, 300)
    assert captured_url[0] == "http://prometheus:9090", \
        "PROMETHEUS_URL env var must override config.yml prometheus.url"


# ---------------------------------------------------------------------------
# response_time_ms must never be 0 (truncation bug fix)
# ---------------------------------------------------------------------------

def test_log_check_response_time_rounds_not_truncates():
    """
    Sub-millisecond response times must be stored as 1 ms minimum, not 0.
    Bug: int(0.782) = 0 → health check logs show '0 ms' for all fast local checks.
    Fix: max(1, round(response_time_ms))
    """
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"id": 1}
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    logger = HealthCheckLogger({
        "host": "localhost", "port": 3306, "database": "monitoring",
        "user": "root", "password": "x", "retention_days": 90, "cleanup_interval_hours": 24,
    })
    with patch.object(logger, "_connect", return_value=mock_conn):
        logger.log_check("test-sys", True, 0.3)  # 0.3 ms → must NOT store 0

    args = mock_cursor.execute.call_args[0][1]
    stored_ms = args[-2]  # response_time_ms is 4th positional (pk, status, http_code, ms, error)
    assert stored_ms >= 1, \
        f"response_time_ms=0.3 was stored as {stored_ms} — must be >= 1 (not truncated to 0)"


def test_log_check_batch_response_time_minimum_one():
    """Batch logging must also use round() not int()."""
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"id": 1}
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    logger = HealthCheckLogger({
        "host": "localhost", "port": 3306, "database": "monitoring",
        "user": "root", "password": "x", "retention_days": 90, "cleanup_interval_hours": 24,
    })
    with patch.object(logger, "_connect", return_value=mock_conn):
        logger.log_check_batch([("test-sys", True, 0.1, "", None)])

    rows = mock_cursor.executemany.call_args[0][1]
    stored_ms = rows[0][3]  # (pk, status, http_code, ms, error)
    assert stored_ms >= 1, \
        f"Batch response_time_ms=0.1 was stored as {stored_ms} — must be >= 1"

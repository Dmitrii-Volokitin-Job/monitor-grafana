"""
Unit tests for HealthCheckLogger — mocked DB connection, no real DB.

Critical: DB failures must never crash the exporter (silent degradation).
"""
import sys
import os
import time
import pytest
from unittest.mock import patch, MagicMock, call

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from monitor_exporter.exporter import HealthCheckLogger


DB_CONFIG = {
    "host": "localhost", "port": 5432, "database": "monitoring",
    "user": "monitoring", "password": "x",
    "retention_days": 90, "cleanup_interval_hours": 24,
}


def make_logger_with_mock_conn():
    """Return (logger, mock_conn, mock_cursor) with _connect patched."""
    mock_cursor = MagicMock()
    # psycopg dict_row returns dicts; HealthCheckLogger uses row["id"]
    mock_cursor.fetchone.return_value = {"id": 42}
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    logger = HealthCheckLogger(DB_CONFIG)
    return logger, mock_conn, mock_cursor


# ---------------------------------------------------------------------------
# log_check — SQL correctness
# ---------------------------------------------------------------------------

def test_log_check_up_inserts_UP_string():
    logger, mock_conn, mock_cursor = make_logger_with_mock_conn()
    with patch.object(logger, "_connect", return_value=mock_conn):
        logger.log_check("test-sys", True, 45.2)

    args = mock_cursor.execute.call_args[0][1]
    assert "UP" in args


def test_log_check_down_inserts_DOWN_string():
    logger, mock_conn, mock_cursor = make_logger_with_mock_conn()
    with patch.object(logger, "_connect", return_value=mock_conn):
        logger.log_check("test-sys", False, 100.0)

    args = mock_cursor.execute.call_args[0][1]
    assert "DOWN" in args


def test_log_check_error_truncated_to_500_chars():
    logger, mock_conn, mock_cursor = make_logger_with_mock_conn()
    long_error = "E" * 600
    with patch.object(logger, "_connect", return_value=mock_conn):
        logger.log_check("test-sys", False, 10.0, error=long_error)

    args = mock_cursor.execute.call_args[0][1]
    stored_error = args[-1]  # last positional arg
    assert len(stored_error) <= 500


def test_log_check_http_status_code_passed():
    logger, mock_conn, mock_cursor = make_logger_with_mock_conn()
    with patch.object(logger, "_connect", return_value=mock_conn):
        logger.log_check("test-sys", False, 10.0, http_status_code=503)

    args = mock_cursor.execute.call_args[0][1]
    assert 503 in args


def test_log_check_http_status_none_for_non_http():
    logger, mock_conn, mock_cursor = make_logger_with_mock_conn()
    with patch.object(logger, "_connect", return_value=mock_conn):
        logger.log_check("test-sys", True, 10.0)  # no http_status_code

    args = mock_cursor.execute.call_args[0][1]
    assert None in args  # nullable column should be None


# ---------------------------------------------------------------------------
# Unknown system_id → skip insert
# ---------------------------------------------------------------------------

def test_log_check_unknown_system_id_skips_insert():
    """If system_id isn't in monitored_system, _get_system_pk returns None → no INSERT."""
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None  # not found
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    logger = HealthCheckLogger(DB_CONFIG)
    with patch.object(logger, "_connect", return_value=mock_conn):
        logger.log_check("nonexistent-system", True, 10.0)

    # execute should have been called only for the SELECT, not INSERT
    for c in mock_cursor.execute.call_args_list:
        assert "INSERT" not in c[0][0]


# ---------------------------------------------------------------------------
# PK caching
# ---------------------------------------------------------------------------

def test_system_pk_cache_avoids_duplicate_selects():
    """Second call for same system_id must not issue another SELECT."""
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"id": 99}
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    logger = HealthCheckLogger(DB_CONFIG)
    with patch.object(logger, "_connect", return_value=mock_conn):
        logger.log_check("sys-a", True, 10.0)
    with patch.object(logger, "_connect", return_value=mock_conn):
        logger.log_check("sys-a", True, 10.0)

    select_calls = [c for c in mock_cursor.execute.call_args_list
                    if "SELECT" in c[0][0]]
    assert len(select_calls) == 1, "SELECT should only be issued once per system_id"


# ---------------------------------------------------------------------------
# log_check_batch
# ---------------------------------------------------------------------------

def test_log_check_batch_inserts_multiple_rows():
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {"id": 1}
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    logger = HealthCheckLogger(DB_CONFIG)
    results = [
        ("sys-1", True, 10.0, "", None),
        ("sys-2", False, 20.0, "err", None),
        ("sys-3", True, 30.0, "", 200),
    ]
    with patch.object(logger, "_connect", return_value=mock_conn):
        logger.log_check_batch(results)

    mock_cursor.executemany.assert_called_once()
    rows_arg = mock_cursor.executemany.call_args[0][1]
    assert len(rows_arg) == 3


def test_log_check_batch_empty_list_does_nothing():
    logger = HealthCheckLogger(DB_CONFIG)
    connect_mock = MagicMock()
    with patch.object(logger, "_connect", return_value=connect_mock):
        logger.log_check_batch([])
    connect_mock.assert_not_called()


# ---------------------------------------------------------------------------
# run_cleanup — rate limiting
# ---------------------------------------------------------------------------

def test_retention_cleanup_issues_delete():
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 5
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    logger = HealthCheckLogger(DB_CONFIG)
    logger._last_cleanup = 0  # force cleanup to run
    with patch.object(logger, "_connect", return_value=mock_conn):
        logger.run_cleanup()

    delete_calls = [c for c in mock_cursor.execute.call_args_list
                    if "DELETE" in c[0][0]]
    assert len(delete_calls) == 1


def test_retention_cleanup_runs_at_most_once_per_interval():
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 0
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    logger = HealthCheckLogger(DB_CONFIG)
    logger._last_cleanup = 0  # first call will run

    with patch.object(logger, "_connect", return_value=mock_conn):
        logger.run_cleanup()  # runs
        logger.run_cleanup()  # skipped (interval not elapsed)

    delete_calls = [c for c in mock_cursor.execute.call_args_list
                    if "DELETE" in c[0][0]]
    assert len(delete_calls) == 1


def test_retention_cleanup_uses_configured_retention_days():
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 0
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    config = {**DB_CONFIG, "retention_days": 30}
    logger = HealthCheckLogger(config)
    logger._last_cleanup = 0

    with patch.object(logger, "_connect", return_value=mock_conn):
        logger.run_cleanup()

    args = mock_cursor.execute.call_args[0][1]
    assert 30 in args


# ---------------------------------------------------------------------------
# Resilience — DB failures must not propagate
# ---------------------------------------------------------------------------

def test_log_check_db_failure_does_not_raise():
    logger = HealthCheckLogger(DB_CONFIG)
    with patch.object(logger, "_connect", side_effect=Exception("DB unreachable")):
        # Must not raise
        logger.log_check("sys", True, 10.0)


def test_run_cleanup_db_failure_does_not_raise():
    logger = HealthCheckLogger(DB_CONFIG)
    logger._last_cleanup = 0
    with patch.object(logger, "_connect", side_effect=Exception("DB unreachable")):
        logger.run_cleanup()  # must not raise

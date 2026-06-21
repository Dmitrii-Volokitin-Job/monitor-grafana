"""
Unit tests for LDAP check logic.

Critical invariant: LDAPBindError = UP, not DOWN.
The LDAP server responded (auth rejected is expected for anonymous bind) — the
server is reachable. Only socket/connection failures = DOWN.
"""
import sys
import os
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from monitor_exporter.exporter import (
    check_ldap,
    parse_ldap_url,
    extract_ldap_version,
)
from ldap3.core.exceptions import (
    LDAPBindError,
    LDAPSocketOpenError,
    LDAPSocketReceiveError,
    LDAPSessionTerminatedByServerError,
    LDAPException,
)


# ---------------------------------------------------------------------------
# parse_ldap_url
# ---------------------------------------------------------------------------

def test_ldap_url_parsing_ldaps_636():
    host, port, use_ssl = parse_ldap_url("ldaps://host.example.com:636")
    assert host == "host.example.com"
    assert port == 636
    assert use_ssl is True


def test_ldap_url_parsing_ldaps_default_port():
    host, port, use_ssl = parse_ldap_url("ldaps://host.example.com")
    assert port == 636
    assert use_ssl is True


def test_ldap_url_parsing_ldap_plain():
    host, port, use_ssl = parse_ldap_url("ldap://host.example.com")
    assert port == 389
    assert use_ssl is False


def test_ldap_url_parsing_ldap_custom_port():
    host, port, use_ssl = parse_ldap_url("ldap://host.example.com:3389")
    assert port == 3389
    assert use_ssl is False


# ---------------------------------------------------------------------------
# extract_ldap_version
# ---------------------------------------------------------------------------

def test_ldap_version_from_vendor_version():
    server = MagicMock()
    server.info.vendor_version = ["OpenLDAP 2.6.3"]
    assert extract_ldap_version(server) == "OpenLDAP 2.6.3"


def test_ldap_version_from_vendor_name_fallback():
    server = MagicMock()
    server.info.vendor_version = None
    server.info.vendor_name = "389 Directory Server"
    assert extract_ldap_version(server) == "389 Directory Server"


def test_ldap_version_from_supported_ldap_version():
    server = MagicMock()
    server.info.vendor_version = None
    server.info.vendor_name = None
    server.info.supported_ldap_version = [2, 3]
    assert extract_ldap_version(server) == "LDAPv3"


def test_ldap_version_unknown_when_no_info():
    server = MagicMock()
    server.info = None
    assert extract_ldap_version(server) == "unknown"


def test_ldap_version_unknown_when_exception():
    server = MagicMock()
    type(server).info = PropertyMock(side_effect=Exception("boom"))
    assert extract_ldap_version(server) == "unknown"


# ---------------------------------------------------------------------------
# check_ldap — happy path
# ---------------------------------------------------------------------------

TARGET = {
    "system_id": "test-ldap",
    "display_name": "Test LDAP",
    "system_group": "TEST",
    "url": "ldaps://ldap.example.com:636",
    "timeout_seconds": 5,
}


def _make_ldap_mocks(bind_result=True, bind_side_effect=None):
    """Return (MockServer, MockConnection) patchers."""
    mock_conn = MagicMock()
    mock_conn.bind.return_value = bind_result
    if bind_side_effect:
        mock_conn.bind.side_effect = bind_side_effect
    mock_server = MagicMock()
    mock_server.info.vendor_version = ["OpenLDAP 2.6"]
    return mock_server, mock_conn


def test_ldap_successful_bind():
    mock_server, mock_conn = _make_ldap_mocks(bind_result=True)

    with patch("monitor_exporter.exporter.Server", return_value=mock_server), \
         patch("monitor_exporter.exporter.Connection", return_value=mock_conn):
        is_up, resp_ms, error, version = check_ldap(TARGET)

    assert is_up is True
    assert resp_ms >= 0
    assert error == ""


def test_ldap_response_time_is_measured():
    mock_server, mock_conn = _make_ldap_mocks()

    with patch("monitor_exporter.exporter.Server", return_value=mock_server), \
         patch("monitor_exporter.exporter.Connection", return_value=mock_conn):
        _, resp_ms, _, _ = check_ldap(TARGET)

    assert resp_ms >= 0


# ---------------------------------------------------------------------------
# check_ldap — LDAPBindError = UP (key invariant)
# ---------------------------------------------------------------------------

def test_ldap_bind_error_counts_as_up():
    """
    LDAPBindError means auth was rejected — but the server is reachable.
    This MUST return is_up=True, not False.
    """
    mock_server, mock_conn = _make_ldap_mocks()
    mock_conn.bind.side_effect = LDAPBindError("invalidCredentials")

    with patch("monitor_exporter.exporter.Server", return_value=mock_server), \
         patch("monitor_exporter.exporter.Connection", return_value=mock_conn):
        is_up, resp_ms, error, version = check_ldap(TARGET)

    assert is_up is True, "LDAPBindError must be treated as UP — server responded"
    assert resp_ms >= 0


# ---------------------------------------------------------------------------
# check_ldap — network errors = DOWN
# ---------------------------------------------------------------------------

def test_ldap_socket_open_error_is_down():
    mock_server, mock_conn = _make_ldap_mocks()
    mock_conn.bind.side_effect = LDAPSocketOpenError("Connection refused")

    with patch("monitor_exporter.exporter.Server", return_value=mock_server), \
         patch("monitor_exporter.exporter.Connection", return_value=mock_conn):
        is_up, resp_ms, error, version = check_ldap(TARGET)

    assert is_up is False
    assert "Connection refused" in error
    assert version == "unknown"


def test_ldap_socket_receive_error_is_down():
    mock_server, mock_conn = _make_ldap_mocks()
    mock_conn.bind.side_effect = LDAPSocketReceiveError("recv failed")

    with patch("monitor_exporter.exporter.Server", return_value=mock_server), \
         patch("monitor_exporter.exporter.Connection", return_value=mock_conn):
        is_up, _, _, _ = check_ldap(TARGET)

    assert is_up is False


def test_ldap_session_terminated_is_down():
    mock_server, mock_conn = _make_ldap_mocks()
    mock_conn.bind.side_effect = LDAPSessionTerminatedByServerError("server reset")

    with patch("monitor_exporter.exporter.Server", return_value=mock_server), \
         patch("monitor_exporter.exporter.Connection", return_value=mock_conn):
        is_up, _, _, _ = check_ldap(TARGET)

    assert is_up is False


def test_ldap_generic_ldap_exception_is_down():
    mock_server, mock_conn = _make_ldap_mocks()
    mock_conn.bind.side_effect = LDAPException("unexpected error")

    with patch("monitor_exporter.exporter.Server", return_value=mock_server), \
         patch("monitor_exporter.exporter.Connection", return_value=mock_conn):
        is_up, _, _, _ = check_ldap(TARGET)

    assert is_up is False


def test_ldap_unexpected_exception_is_down():
    mock_server, mock_conn = _make_ldap_mocks()
    mock_conn.bind.side_effect = RuntimeError("something unexpected")

    with patch("monitor_exporter.exporter.Server", return_value=mock_server), \
         patch("monitor_exporter.exporter.Connection", return_value=mock_conn):
        is_up, _, error, _ = check_ldap(TARGET)

    assert is_up is False
    assert "unexpected" in error

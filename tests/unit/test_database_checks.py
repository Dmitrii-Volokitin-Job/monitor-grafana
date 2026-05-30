"""
Unit tests for MariaDB/MySQL greeting packet parsing.

No credentials needed — the MySQL wire protocol sends the version string
in the initial handshake before authentication.
"""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from monitor_exporter.exporter import extract_mysql_version_from_greeting


def make_mysql_greeting(version_str: str) -> bytes:
    """Build a minimal valid MySQL/MariaDB server greeting packet."""
    # packet body: protocol version byte (0x0a) + null-terminated version string + padding
    body = b'\x0a' + version_str.encode('utf-8') + b'\x00' + b'\x00' * 20
    # packet header: 3 bytes length (little-endian) + 1 byte sequence id
    length = len(body).to_bytes(3, 'little')
    seq = b'\x00'
    return length + seq + body


def _mock_socket(recv_data: bytes):
    """Return a context-manager-compatible mock socket."""
    sock = MagicMock()
    sock.recv.return_value = recv_data
    return sock


# ---------------------------------------------------------------------------
# Happy path — version correctly parsed
# ---------------------------------------------------------------------------

def test_db_parses_mariadb_version():
    data = make_mysql_greeting("10.6.17-MariaDB")
    with patch("monitor_exporter.exporter.socket.create_connection",
               return_value=_mock_socket(data)):
        is_up, resp_ms, version, error = extract_mysql_version_from_greeting(
            "db.example.com", 3306, 5)

    assert is_up is True
    assert version == "10.6.17-MariaDB"
    assert error == ""


def test_db_parses_plain_mysql_version():
    data = make_mysql_greeting("8.0.36")
    with patch("monitor_exporter.exporter.socket.create_connection",
               return_value=_mock_socket(data)):
        is_up, _, version, _ = extract_mysql_version_from_greeting("h", 3306, 5)

    assert is_up is True
    assert version == "8.0.36"


def test_db_response_time_is_measured():
    data = make_mysql_greeting("10.6.0")
    with patch("monitor_exporter.exporter.socket.create_connection",
               return_value=_mock_socket(data)):
        _, resp_ms, _, _ = extract_mysql_version_from_greeting("h", 3306, 5)

    assert resp_ms >= 0


# ---------------------------------------------------------------------------
# Edge cases — short / malformed packets
# ---------------------------------------------------------------------------

def test_db_short_packet_returns_unknown_but_up():
    """Less than 5 bytes — can't parse version but connection succeeded."""
    with patch("monitor_exporter.exporter.socket.create_connection",
               return_value=_mock_socket(b'\x00\x00\x00\x00')):
        is_up, _, version, _ = extract_mysql_version_from_greeting("h", 3306, 5)

    assert is_up is True
    assert version == "unknown"


def test_db_non_ascii_version_does_not_crash():
    """Bytes that aren't valid UTF-8 should not raise — use replace mode."""
    body = b'\x0a' + b'\xff\xfe' + b'\x00' + b'\x00' * 20
    header = len(body).to_bytes(3, 'little') + b'\x00'
    data = header + body
    with patch("monitor_exporter.exporter.socket.create_connection",
               return_value=_mock_socket(data)):
        is_up, _, version, _ = extract_mysql_version_from_greeting("h", 3306, 5)
    # Should not raise — result can be anything but must return cleanly
    assert isinstance(version, str)


# ---------------------------------------------------------------------------
# Network failures → DOWN
# ---------------------------------------------------------------------------

def test_db_connection_refused_is_down():
    with patch("monitor_exporter.exporter.socket.create_connection",
               side_effect=ConnectionRefusedError("Connection refused")):
        is_up, resp_ms, version, error = extract_mysql_version_from_greeting(
            "db.example.com", 3306, 5)

    assert is_up is False
    assert version == "unknown"
    assert resp_ms >= 0


def test_db_timeout_is_down():
    import socket
    with patch("monitor_exporter.exporter.socket.create_connection",
               side_effect=socket.timeout("timed out")):
        is_up, _, _, error = extract_mysql_version_from_greeting("h", 3306, 5)

    assert is_up is False
    assert "timed out" in error


def test_db_os_error_is_down():
    with patch("monitor_exporter.exporter.socket.create_connection",
               side_effect=OSError("network unreachable")):
        is_up, _, _, error = extract_mysql_version_from_greeting("h", 3306, 5)

    assert is_up is False

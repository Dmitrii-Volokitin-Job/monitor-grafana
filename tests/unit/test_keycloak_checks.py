"""
Unit tests for Keycloak check logic.

Critical invariant: realm_valid=False does NOT mean DOWN.
The system can be UP (reachable) but with a misconfigured realm name.
Only HTTP errors / connection failures = DOWN.
"""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock
import requests as req

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from monitor_exporter.exporter import check_keycloak


TARGET = {
    "system_id": "test-kc",
    "display_name": "Test Keycloak",
    "system_group": "TEST",
    "base_url": "https://kc.example.com",
    "realm_path": "/auth/realms/master",
    "timeout_seconds": 5,
}


def _mock_get(status_code=200, json_data=None, headers=None, raise_exc=None):
    resp = MagicMock(spec=req.Response)
    resp.status_code = status_code
    resp.headers = headers or {}
    if raise_exc:
        resp.json.side_effect = raise_exc
    else:
        resp.json.return_value = json_data or {}
    return resp


# ---------------------------------------------------------------------------
# Happy path — 200 with valid realm
# ---------------------------------------------------------------------------

def test_keycloak_200_valid_realm():
    resp = _mock_get(json_data={"realm": "master", "public_key": "abc"})
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        is_up, resp_ms, realm_valid, version, error = check_keycloak(TARGET)

    assert is_up is True
    assert realm_valid is True
    assert error == ""
    assert resp_ms >= 0


def test_keycloak_response_time_measured():
    resp = _mock_get(json_data={"realm": "master"})
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        _, resp_ms, _, _, _ = check_keycloak(TARGET)
    assert resp_ms >= 0


# ---------------------------------------------------------------------------
# realm_valid=False but still UP
# ---------------------------------------------------------------------------

def test_keycloak_200_wrong_realm_name_is_up_realm_invalid():
    """
    Server returns 200 but realm name doesn't match path.
    System is UP but realm_valid=False — different alert, not an outage.
    """
    resp = _mock_get(json_data={"realm": "different-realm"})
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        is_up, _, realm_valid, _, _ = check_keycloak(TARGET)

    assert is_up is True
    assert realm_valid is False


def test_keycloak_200_invalid_json_is_up_realm_invalid():
    """200 OK but body is not valid JSON → UP (server responded) but realm_valid=False."""
    resp = _mock_get(status_code=200, raise_exc=ValueError("not JSON"))
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        is_up, _, realm_valid, _, error = check_keycloak(TARGET)

    assert is_up is True
    assert realm_valid is False
    assert "JSON" in error or error != ""


# ---------------------------------------------------------------------------
# HTTP errors → DOWN
# ---------------------------------------------------------------------------

def test_keycloak_401_is_down():
    resp = _mock_get(status_code=401)
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        is_up, _, _, _, error = check_keycloak(TARGET)

    assert is_up is False
    assert "401" in error


def test_keycloak_503_is_down():
    resp = _mock_get(status_code=503)
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        is_up, _, _, _, _ = check_keycloak(TARGET)
    assert is_up is False


# ---------------------------------------------------------------------------
# Network failures → DOWN
# ---------------------------------------------------------------------------

def test_keycloak_connection_error_is_down():
    with patch("monitor_exporter.exporter.requests.get",
               side_effect=req.exceptions.ConnectionError("refused")):
        is_up, _, _, _, error = check_keycloak(TARGET)

    assert is_up is False
    assert error != ""


def test_keycloak_timeout_is_down():
    with patch("monitor_exporter.exporter.requests.get",
               side_effect=req.exceptions.Timeout("timed out")):
        is_up, _, _, _, error = check_keycloak(TARGET)

    assert is_up is False
    assert "timed out" in error


# ---------------------------------------------------------------------------
# Version extraction
# ---------------------------------------------------------------------------

def test_keycloak_version_from_x_keycloak_version_header():
    resp = _mock_get(
        json_data={"realm": "master"},
        headers={"X-Keycloak-Version": "22.0.1"},
    )
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        _, _, _, version, _ = check_keycloak(TARGET)

    assert version == "22.0.1"


def test_keycloak_version_from_server_header():
    resp = _mock_get(
        json_data={"realm": "master"},
        headers={"Server": "Keycloak/21.1.2"},
    )
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        _, _, _, version, _ = check_keycloak(TARGET)

    assert version == "21.1.2"


def test_keycloak_version_unknown_when_no_version_header():
    resp = _mock_get(json_data={"realm": "master"}, headers={})
    with patch("monitor_exporter.exporter.requests.get", return_value=resp), \
         patch("monitor_exporter.exporter.try_keycloak_version_from_wellknown",
               return_value="unknown"):
        _, _, _, version, _ = check_keycloak(TARGET)

    assert version == "unknown"

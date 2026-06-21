"""
Unit tests for all VERSION_STRATEGIES extractors.

Note: json_version maps to extract_version_camunda (same {"version": "..."} format).
"""
import sys
import os
import pytest
from unittest.mock import patch, MagicMock
import requests as req

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from monitor_exporter.exporter import (
    VERSION_STRATEGIES,
    extract_version_spring_actuator,
    extract_version_openapi,
    extract_version_gateway,
    extract_version_kubernetes,
    extract_version_camunda,
    _fetch_version_json,
    _VERSION_USER_AGENT,
)


def _mock_get(status_code=200, json_data=None, raise_exc=None):
    resp = MagicMock(spec=req.Response)
    resp.status_code = status_code
    if raise_exc:
        resp.json.side_effect = raise_exc
    else:
        resp.json.return_value = json_data or {}
    return resp


URL = "https://app.example.com/endpoint"
TIMEOUT = 5


# ---------------------------------------------------------------------------
# spring_actuator
# ---------------------------------------------------------------------------

def test_spring_actuator_build_version():
    resp = _mock_get(json_data={"build": {"version": "2.3.1", "name": "app"}})
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        assert extract_version_spring_actuator(URL, TIMEOUT) == "2.3.1"


def test_spring_actuator_app_version_fallback():
    resp = _mock_get(json_data={"app": {"version": "1.0.0"}})
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        assert extract_version_spring_actuator(URL, TIMEOUT) == "1.0.0"


def test_spring_actuator_top_level_version_fallback():
    resp = _mock_get(json_data={"version": "3.0.0"})
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        assert extract_version_spring_actuator(URL, TIMEOUT) == "3.0.0"


def test_spring_actuator_no_version_returns_unknown():
    resp = _mock_get(json_data={"status": "UP"})
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        assert extract_version_spring_actuator(URL, TIMEOUT) == "unknown"


def test_spring_actuator_http_error_returns_unknown():
    resp = _mock_get(status_code=404)
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        assert extract_version_spring_actuator(URL, TIMEOUT) == "unknown"


def test_spring_actuator_connection_error_returns_unknown():
    with patch("monitor_exporter.exporter.requests.get",
               side_effect=req.exceptions.ConnectionError()):
        assert extract_version_spring_actuator(URL, TIMEOUT) == "unknown"


# ---------------------------------------------------------------------------
# openapi
# ---------------------------------------------------------------------------

def test_openapi_info_version():
    resp = _mock_get(json_data={"openapi": "3.0.1", "info": {"version": "1.2.3"}})
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        assert extract_version_openapi(URL, TIMEOUT) == "1.2.3"


def test_openapi_missing_info_returns_unknown():
    resp = _mock_get(json_data={"openapi": "3.0.1"})
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        assert extract_version_openapi(URL, TIMEOUT) == "unknown"


def test_openapi_http_error_returns_unknown():
    resp = _mock_get(status_code=401)
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        assert extract_version_openapi(URL, TIMEOUT) == "unknown"


# ---------------------------------------------------------------------------
# gateway_version
# ---------------------------------------------------------------------------

def test_gateway_server_version():
    resp = _mock_get(json_data={"serverVersion": "2.3.3", "apiVersion": "V1"})
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        assert extract_version_gateway(URL, TIMEOUT) == "2.3.3"


def test_gateway_version_field_fallback():
    resp = _mock_get(json_data={"version": "2.3.3"})
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        assert extract_version_gateway(URL, TIMEOUT) == "2.3.3"


def test_gateway_no_version_returns_unknown():
    resp = _mock_get(json_data={"apiVersion": "V1"})
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        assert extract_version_gateway(URL, TIMEOUT) == "unknown"


# ---------------------------------------------------------------------------
# kubernetes
# ---------------------------------------------------------------------------

def test_kubernetes_git_version():
    resp = _mock_get(json_data={"gitVersion": "v1.28.2+k3s1", "major": "1", "minor": "28"})
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        assert extract_version_kubernetes(URL, TIMEOUT) == "v1.28.2+k3s1"


def test_kubernetes_major_minor_fallback():
    resp = _mock_get(json_data={"major": "1", "minor": "28"})
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        assert extract_version_kubernetes(URL, TIMEOUT) == "v1.28"


def test_kubernetes_http_error_returns_unknown():
    resp = _mock_get(status_code=403)
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        assert extract_version_kubernetes(URL, TIMEOUT) == "unknown"


# ---------------------------------------------------------------------------
# json_version / camunda (same extractor)
# ---------------------------------------------------------------------------

def test_json_version_generic():
    resp = _mock_get(json_data={"version": "1.0.0"})
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        assert extract_version_camunda(URL, TIMEOUT) == "1.0.0"


def test_camunda_version_field():
    resp = _mock_get(json_data={"version": "7.20.0"})
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        assert extract_version_camunda(URL, TIMEOUT) == "7.20.0"


# ---------------------------------------------------------------------------
# VERSION_STRATEGIES dict integrity
# ---------------------------------------------------------------------------

def test_all_strategies_are_callable():
    for name, fn in VERSION_STRATEGIES.items():
        assert callable(fn), f"Strategy '{name}' is not callable"


def test_known_strategies_present():
    expected = {"spring_actuator", "camunda", "openapi", "gateway_version",
                "kubernetes", "monitor_version", "json_version"}
    assert expected.issubset(set(VERSION_STRATEGIES.keys()))


def test_json_version_maps_to_camunda_extractor():
    """json_version reuses extract_version_camunda — verify they're the same function."""
    assert VERSION_STRATEGIES["json_version"] is VERSION_STRATEGIES["camunda"]


# ---------------------------------------------------------------------------
# _fetch_version_json — the shared helper that all six extract_version_*
# strategies use. Covered only indirectly above; pin its contract directly.
# ---------------------------------------------------------------------------

def test_fetch_version_json_returns_dict_on_200():
    resp = _mock_get(json_data={"version": "1.2.3"})
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        assert _fetch_version_json(URL, TIMEOUT, "Test") == {"version": "1.2.3"}


def test_fetch_version_json_returns_none_on_non_200():
    resp = _mock_get(status_code=503)
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        assert _fetch_version_json(URL, TIMEOUT, "Test") is None


def test_fetch_version_json_returns_none_on_request_exception():
    with patch("monitor_exporter.exporter.requests.get",
               side_effect=req.ConnectionError("DNS fail")):
        assert _fetch_version_json(URL, TIMEOUT, "Test") is None


def test_fetch_version_json_returns_none_on_bad_json():
    resp = _mock_get(raise_exc=ValueError("not JSON"))
    with patch("monitor_exporter.exporter.requests.get", return_value=resp):
        assert _fetch_version_json(URL, TIMEOUT, "Test") is None


def test_fetch_version_json_uses_canonical_user_agent():
    """All strategies share the same UA via _VERSION_USER_AGENT — verify the
    helper actually sends it (the constant must not silently drift)."""
    captured = {}
    def fake_get(url, timeout=None, verify=None, headers=None):
        captured.update({"url": url, "headers": headers})
        return _mock_get(json_data={})
    with patch("monitor_exporter.exporter.requests.get", side_effect=fake_get):
        _fetch_version_json(URL, TIMEOUT, "Test")
    assert captured["headers"]["User-Agent"] == _VERSION_USER_AGENT
    assert captured["url"] == URL

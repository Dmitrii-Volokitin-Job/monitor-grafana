"""Unit tests for admin_ui's require_grafana_auth decorator."""
import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "monitor_exporter"))

import admin_ui  # noqa: E402


@pytest.fixture(autouse=True)
def clear_auth_cache():
    admin_ui._auth_cache.clear()
    yield
    admin_ui._auth_cache.clear()


@pytest.fixture
def app():
    from flask import Flask
    a = Flask(__name__)
    a.secret_key = "test"

    @a.get("/protected-viewer")
    @admin_ui.require_grafana_auth(min_role="Viewer")
    def viewer():
        return "ok-viewer"

    @a.get("/protected-editor")
    @admin_ui.require_grafana_auth(min_role="Editor")
    def editor():
        return "ok-editor"

    return a


def _grafana_response(status: int, body: dict | None = None):
    m = MagicMock()
    m.status_code = status
    m.json.return_value = body or {}
    return m


def test_no_cookie_redirects_to_grafana_login(app):
    client = app.test_client()
    r = client.get("/protected-viewer")
    assert r.status_code == 302
    assert "/login" in r.location


def test_valid_session_with_viewer_role_passes_viewer_endpoint(app):
    client = app.test_client()
    client.set_cookie("grafana_session", "abc")
    with patch.object(admin_ui.httpx, "get",
                      return_value=_grafana_response(200, {"login": "u", "orgRole": "Viewer"})):
        r = client.get("/protected-viewer")
    assert r.status_code == 200
    assert r.data == b"ok-viewer"


def test_viewer_role_blocked_from_editor_endpoint(app):
    client = app.test_client()
    client.set_cookie("grafana_session", "viewer-session")
    with patch.object(admin_ui.httpx, "get",
                      return_value=_grafana_response(200, {"login": "u", "orgRole": "Viewer"})):
        r = client.get("/protected-editor")
    assert r.status_code == 403


def test_editor_role_passes_editor_endpoint(app):
    client = app.test_client()
    client.set_cookie("grafana_session", "editor-session")
    with patch.object(admin_ui.httpx, "get",
                      return_value=_grafana_response(200, {"login": "ed", "orgRole": "Editor"})):
        r = client.get("/protected-editor")
    assert r.status_code == 200


def test_admin_role_passes_editor_endpoint(app):
    client = app.test_client()
    client.set_cookie("grafana_session", "admin-session")
    with patch.object(admin_ui.httpx, "get",
                      return_value=_grafana_response(200, {"login": "a", "isGrafanaAdmin": True})):
        r = client.get("/protected-editor")
    assert r.status_code == 200


def test_invalid_session_redirects(app):
    client = app.test_client()
    client.set_cookie("grafana_session", "bad")
    with patch.object(admin_ui.httpx, "get", return_value=_grafana_response(401)):
        r = client.get("/protected-viewer")
    assert r.status_code == 302


def test_auth_decision_is_cached(app):
    client = app.test_client()
    client.set_cookie("grafana_session", "cached")
    with patch.object(admin_ui.httpx, "get",
                      return_value=_grafana_response(200, {"login": "u", "orgRole": "Viewer"})) as m:
        client.get("/protected-viewer")
        client.get("/protected-viewer")
    assert m.call_count == 1  # second call served from cache

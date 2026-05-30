"""Unit tests for the lab CRUD routes in admin_ui."""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "monitor_exporter"))

import admin_ui  # noqa: E402
import db as _db  # noqa: E402

DB_CONFIG = {"enabled": True, "host": "x", "port": 0, "database": "x", "user": "x", "password": "x"}


@pytest.fixture(autouse=True)
def clear_auth_cache():
    admin_ui._auth_cache.clear()
    yield
    admin_ui._auth_cache.clear()


@pytest.fixture
def authed_client():
    """A Flask test client that has a 'logged-in' Grafana session as an Editor."""
    from flask import Flask

    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(admin_ui.__file__), "templates"))
    app.secret_key = "test"
    app.register_blueprint(admin_ui.create_blueprint(DB_CONFIG))

    grafana_response = MagicMock()
    grafana_response.status_code = 200
    grafana_response.json.return_value = {"login": "ed", "orgRole": "Editor"}

    with patch.object(admin_ui.httpx, "get", return_value=grafana_response):
        client = app.test_client()
        client.set_cookie("grafana_session", "valid-session")
        yield client


def _patch_list(rows):
    return patch.object(admin_ui, "_list_labs", return_value=rows)

def _patch_get(row):
    return patch.object(admin_ui, "_get_lab", return_value=row)


def test_list_labs_renders(authed_client):
    rows = [
        {"id": 1, "name": "demo-lab-a", "display_name": "Demo Lab A", "description": "", "is_enable": 1, "system_count": 9},
        {"id": 2, "name": "demo-lab-b", "display_name": "Demo Lab B", "description": "", "is_enable": 1, "system_count": 9},
    ]
    with _patch_list(rows):
        r = authed_client.get("/admin/labs")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "demo-lab-a" in body and "demo-lab-b" in body
    assert "9" in body   # system_count badge


def test_new_lab_form_renders(authed_client):
    r = authed_client.get("/admin/labs/new")
    assert r.status_code == 200
    assert b'name="name"' in r.data
    assert b'name="display_name"' in r.data


def test_create_lab_requires_name(authed_client):
    r = authed_client.post("/admin/labs", data={"name": "", "display_name": "x"}, follow_redirects=False)
    assert r.status_code == 400
    assert b"Name is required" in r.data


def test_create_lab_success(authed_client):
    with patch.object(admin_ui, "_insert_lab") as m:
        r = authed_client.post("/admin/labs",
                               data={"name": "demo-c", "display_name": "Demo C", "description": "Third demo"},
                               follow_redirects=False)
    assert r.status_code == 302
    m.assert_called_once_with(DB_CONFIG, "demo-c", "Demo C", "Third demo")


def test_create_lab_duplicate_returns_409(authed_client):
    err = _db.IntegrityError("duplicate key value violates unique constraint \"lab_name_key\"")
    with patch.object(admin_ui, "_insert_lab", side_effect=err):
        r = authed_client.post("/admin/labs",
                               data={"name": "demo-c", "display_name": "Demo C"},
                               follow_redirects=False)
    assert r.status_code == 409
    assert b"already exists" in r.data


def test_edit_lab_not_found(authed_client):
    with _patch_get(None):
        r = authed_client.get("/admin/labs/999/edit")
    assert r.status_code == 404


def test_edit_lab_renders(authed_client):
    row = {"id": 1, "name": "demo-lab-a", "display_name": "Demo Lab A",
           "description": "x", "is_enable": 1}
    with _patch_get(row):
        r = authed_client.get("/admin/labs/1/edit")
    assert r.status_code == 200
    assert b"demo-lab-a" in r.data


def test_update_lab_success(authed_client):
    with patch.object(admin_ui, "_update_lab") as m:
        r = authed_client.post("/admin/labs/1",
                               data={"display_name": "Renamed", "description": "new desc", "is_enable": "1"},
                               follow_redirects=False)
    assert r.status_code == 302
    m.assert_called_once_with(DB_CONFIG, 1, "Renamed", "new desc", 1)


def test_update_lab_requires_display_name(authed_client):
    with patch.object(admin_ui, "_update_lab") as m:
        r = authed_client.post("/admin/labs/1",
                               data={"display_name": "", "description": "x"},
                               follow_redirects=False)
    assert r.status_code == 302   # redirects back to edit form with a flash
    m.assert_not_called()


def test_delete_lab_refuses_when_systems_attached(authed_client):
    with patch.object(admin_ui, "_delete_lab", return_value=(False, "Lab 'demo-lab-a' is still referenced by 9 system(s)")):
        r = authed_client.post("/admin/labs/1/delete", follow_redirects=False)
    assert r.status_code == 302   # all delete attempts redirect; the flash carries the error


def test_delete_lab_success(authed_client):
    with patch.object(admin_ui, "_delete_lab", return_value=(True, "")):
        r = authed_client.post("/admin/labs/1/delete", follow_redirects=False)
    assert r.status_code == 302

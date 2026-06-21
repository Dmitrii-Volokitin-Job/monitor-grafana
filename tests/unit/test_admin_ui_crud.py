"""Unit tests for admin_ui CRUD validation logic (no DB)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "monitor_exporter"))

import admin_ui  # noqa: E402


def test_validate_http_missing_url():
    errors = admin_ui._validate({
        "system_type": "HTTP", "system_id": "x", "display_name": "X",
        "system_group": "G", "blackbox_module": "http_2xx",
    })
    assert any("url" in e for e in errors)


def test_validate_http_complete():
    assert admin_ui._validate({
        "system_type": "HTTP", "system_id": "x", "display_name": "X",
        "system_group": "G", "url": "https://x/", "blackbox_module": "http_2xx",
    }) == []


def test_validate_keycloak_needs_realm_path():
    errors = admin_ui._validate({
        "system_type": "KEYCLOAK", "system_id": "k", "display_name": "K",
        "system_group": "G", "url": "https://k/",
    })
    assert any("realm_path" in e for e in errors)


def test_validate_database_needs_host_and_port():
    errors = admin_ui._validate({
        "system_type": "DATABASE", "system_id": "d", "display_name": "D",
        "system_group": "G",
    })
    assert any("db_host" in e for e in errors)
    assert any("db_port" in e for e in errors)


def test_validate_version_needs_strategy():
    errors = admin_ui._validate({
        "system_type": "VERSION", "system_id": "v", "display_name": "V",
        "system_group": "G", "url": "https://v/",
    })
    assert any("version_strategy" in e for e in errors)


def test_validate_unknown_type_fails():
    errors = admin_ui._validate({"system_type": "BOGUS"})
    assert errors
    assert "Unknown" in errors[0]


def test_coerce_int_fields():
    assert admin_ui._coerce("timeout_seconds", "30") == 30
    assert admin_ui._coerce("db_port", "3306") == 3306
    assert admin_ui._coerce("expected_status_code", "200") == 200


def test_coerce_empty_returns_none():
    assert admin_ui._coerce("timeout_seconds", "") is None
    assert admin_ui._coerce("display_name", None) is None


def test_coerce_invalid_int_raises_value_error():
    # Old behaviour silently returned None — that conflated "left blank"
    # with "typed garbage" and let admin-UI submits store rows with NULL
    # required values. New contract: raise so the form validator can surface
    # a clear per-field error.
    import pytest
    with pytest.raises(ValueError):
        admin_ui._coerce("db_port", "not-a-number")


def test_validate_reports_invalid_int_field():
    """_validate() must surface unparseable numeric fields as a clear error
    rather than letting the form save with a NULL column."""
    errors = admin_ui._validate({
        "system_type": "DATABASE",
        "system_id": "x", "display_name": "X", "system_group": "g",
        "db_host": "h", "db_port": "not-a-number",
    })
    assert any("db_port" in e and "integer" in e for e in errors), errors


def test_form_to_row_includes_all_fields():
    row = admin_ui._form_to_row({"system_id": "x", "display_name": "X"})
    # All ALL_FIELDS should be keys; ones not in form should be None
    assert set(row.keys()) == set(admin_ui.ALL_FIELDS)
    assert row["system_id"] == "x"
    assert row["display_name"] == "X"
    assert row["url"] is None

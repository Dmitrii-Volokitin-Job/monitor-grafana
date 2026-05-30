"""
Unit tests for exporter._shape_target — the row → check_*-target dict mapper
extracted from `_load_db_targets` during the REFACTORING slot.

Direct coverage matters because the function is the single place that decides
which check_* function gets which row, and a regression here silently drops
targets from monitoring (the SD endpoint would still expose them, but the
exporter's in-process LDAP/Keycloak/DB/version checks would never run).
"""
from monitor_exporter.exporter import (
    _shape_target,
    _DEFAULT_TARGET_TIMEOUT_S,
    _KEYCLOAK_DEFAULT_REALM_PATH,
    _DEFAULT_VERSION_STRATEGY,
)


# A row with every column populated, used as the happy-path baseline.
_FULL_ROW = {
    "system_id":        "demo-a-x",
    "display_name":     "Demo X",
    "system_group":     "demo-lab-a",
    "url":              "ldaps://ldap.example.com:636",
    "realm_path":       "/auth/realms/staging",
    "db_host":          "db.example.com",
    "db_port":          5432,
    "version_strategy": "openapi",
    "timeout_seconds":  12,
}


# --- url-only types (LDAP, ELASTICSEARCH) -----------------------------------

def test_url_only_types_pass_url_through():
    for stype in ("LDAP", "ELASTICSEARCH"):
        t = _shape_target(_FULL_ROW, stype)
        assert t == {
            "system_id":       "demo-a-x",
            "display_name":    "Demo X",
            "system_group":    "demo-lab-a",
            "timeout_seconds": 12,
            "url":             "ldaps://ldap.example.com:636",
        }


def test_url_only_types_drop_row_when_url_missing():
    row = {**_FULL_ROW, "url": None}
    assert _shape_target(row, "LDAP") is None
    assert _shape_target(row, "ELASTICSEARCH") is None


# --- KEYCLOAK ----------------------------------------------------------------

def test_keycloak_renames_url_to_base_url_and_keeps_realm():
    t = _shape_target(_FULL_ROW, "KEYCLOAK")
    assert t["base_url"]   == "ldaps://ldap.example.com:636"
    assert t["realm_path"] == "/auth/realms/staging"
    assert "url" not in t, "KEYCLOAK targets use base_url, not url"


def test_keycloak_falls_back_to_default_realm_when_null():
    row = {**_FULL_ROW, "realm_path": None}
    assert _shape_target(row, "KEYCLOAK")["realm_path"] == _KEYCLOAK_DEFAULT_REALM_PATH


def test_keycloak_drops_row_when_url_missing():
    assert _shape_target({**_FULL_ROW, "url": None}, "KEYCLOAK") is None


# --- host/port types (DATABASE, POSTGRES, REDIS, MONGODB) -------------------

def test_host_port_types_pass_host_and_port():
    for stype in ("DATABASE", "POSTGRES", "REDIS", "MONGODB"):
        t = _shape_target(_FULL_ROW, stype)
        assert t["host"] == "db.example.com"
        assert t["port"] == 5432
        assert "url" not in t


def test_host_port_types_drop_row_when_either_field_missing():
    for missing in ("db_host", "db_port"):
        row = {**_FULL_ROW, missing: None}
        for stype in ("DATABASE", "POSTGRES", "REDIS", "MONGODB"):
            assert _shape_target(row, stype) is None, \
                f"{stype} with {missing}=None should be dropped"


# --- VERSION -----------------------------------------------------------------

def test_version_keeps_url_and_strategy():
    t = _shape_target(_FULL_ROW, "VERSION")
    assert t["url"]      == "ldaps://ldap.example.com:636"
    assert t["strategy"] == "openapi"


def test_version_falls_back_to_default_strategy_when_null():
    row = {**_FULL_ROW, "version_strategy": None}
    assert _shape_target(row, "VERSION")["strategy"] == _DEFAULT_VERSION_STRATEGY


# --- timeout default --------------------------------------------------------

def test_timeout_defaults_when_column_null():
    row = {**_FULL_ROW, "timeout_seconds": None}
    assert _shape_target(row, "LDAP")["timeout_seconds"] == _DEFAULT_TARGET_TIMEOUT_S


def test_timeout_defaults_when_column_zero():
    """Postgres can return 0 for a NOT NULL timeout column; treat falsy as default."""
    row = {**_FULL_ROW, "timeout_seconds": 0}
    assert _shape_target(row, "LDAP")["timeout_seconds"] == _DEFAULT_TARGET_TIMEOUT_S


# --- unknown system_type -----------------------------------------------------

def test_unknown_system_type_returns_none():
    """Defensive: an unknown system_type should not produce a target."""
    assert _shape_target(_FULL_ROW, "QUANTUM_FOO") is None

"""
Unit tests for monitor_exporter/db.py — the central DB connection helper.

The resolver functions implement the env-var override precedence:
    POSTGRES_<key> env var > cfg dict value > hard-coded default

This is load-bearing: every module routes its connections through here.
A silent regression in the precedence order would either leak the wrong
credentials or quietly fall back to the default DB on a configured stack.
"""
import os
from unittest.mock import patch

import db as _db


ENV_VARS = ("POSTGRES_HOST", "POSTGRES_PORT", "POSTGRES_DB",
            "POSTGRES_USER", "POSTGRES_PASSWORD")


def _scrubbed_env() -> dict:
    """Return os.environ with every POSTGRES_* var removed so tests can
    cleanly assert env-var precedence without surprise inheritance."""
    return {k: v for k, v in os.environ.items() if k not in ENV_VARS}


# ---------------------------------------------------------------------------
# Defaults — neither env var nor cfg provided
# ---------------------------------------------------------------------------

def test_resolve_host_default():
    with patch.dict(os.environ, _scrubbed_env(), clear=True):
        assert _db._resolve_host({}) == "localhost"


def test_resolve_port_default():
    with patch.dict(os.environ, _scrubbed_env(), clear=True):
        assert _db._resolve_port({}) == 5432


def test_resolve_db_default():
    with patch.dict(os.environ, _scrubbed_env(), clear=True):
        assert _db._resolve_db({}) == "monitoring"


def test_resolve_user_default():
    with patch.dict(os.environ, _scrubbed_env(), clear=True):
        assert _db._resolve_user({}) == "monitoring"


def test_resolve_password_default():
    with patch.dict(os.environ, _scrubbed_env(), clear=True):
        assert _db._resolve_password({}) == "monitoring"


# ---------------------------------------------------------------------------
# cfg dict overrides defaults
# ---------------------------------------------------------------------------

def test_cfg_overrides_default_host():
    with patch.dict(os.environ, _scrubbed_env(), clear=True):
        assert _db._resolve_host({"host": "db.example.com"}) == "db.example.com"


def test_cfg_overrides_default_port_and_coerces_int():
    with patch.dict(os.environ, _scrubbed_env(), clear=True):
        # YAML may load the port as either int or str — both must coerce
        assert _db._resolve_port({"port": 6543}) == 6543
        assert _db._resolve_port({"port": "6543"}) == 6543


def test_cfg_overrides_default_db():
    with patch.dict(os.environ, _scrubbed_env(), clear=True):
        assert _db._resolve_db({"database": "mydb"}) == "mydb"


def test_cfg_overrides_default_user_and_password():
    with patch.dict(os.environ, _scrubbed_env(), clear=True):
        assert _db._resolve_user({"user": "alice"}) == "alice"
        assert _db._resolve_password({"password": "s3cr3t"}) == "s3cr3t"


# ---------------------------------------------------------------------------
# Env var overrides cfg — the load-bearing rule for K8s secret injection
# ---------------------------------------------------------------------------

def test_env_var_overrides_cfg_for_every_field():
    cfg = {
        "host": "from-cfg", "port": 1, "database": "from-cfg",
        "user": "from-cfg", "password": "from-cfg",
    }
    env = _scrubbed_env() | {
        "POSTGRES_HOST": "from-env",
        "POSTGRES_PORT": "9999",
        "POSTGRES_DB": "from-env",
        "POSTGRES_USER": "from-env",
        "POSTGRES_PASSWORD": "from-env",
    }
    with patch.dict(os.environ, env, clear=True):
        assert _db._resolve_host(cfg) == "from-env"
        assert _db._resolve_port(cfg) == 9999
        assert _db._resolve_db(cfg) == "from-env"
        assert _db._resolve_user(cfg) == "from-env"
        assert _db._resolve_password(cfg) == "from-env"


# ---------------------------------------------------------------------------
# Edge: empty-string env var must NOT count as set (it would silently break
# K8s deployments where a missing Secret renders as empty string).
# ---------------------------------------------------------------------------

def test_empty_env_var_does_not_shadow_cfg():
    """`os.environ.get(...) or cfg.get(...)` correctly skips empty strings."""
    cfg = {"host": "db.example.com"}
    env = _scrubbed_env() | {"POSTGRES_HOST": ""}
    with patch.dict(os.environ, env, clear=True):
        assert _db._resolve_host(cfg) == "db.example.com", (
            "empty POSTGRES_HOST shouldn't override cfg.host"
        )


# ---------------------------------------------------------------------------
# Driver exception re-exports — admin_ui catches `_db.IntegrityError`
# ---------------------------------------------------------------------------

def test_integrity_error_is_psycopg_subclass():
    import psycopg.errors
    assert issubclass(_db.IntegrityError, psycopg.errors.IntegrityError)


def test_database_error_is_psycopg_subclass():
    import psycopg
    assert _db.DatabaseError is psycopg.DatabaseError

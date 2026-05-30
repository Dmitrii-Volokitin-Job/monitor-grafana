"""Single point of DB connectivity for the monitor exporter.

All other modules import `connect()` from here so the underlying driver
(psycopg 3) can be swapped without touching the call sites.
"""
import os
from typing import Any, Mapping

import psycopg
from psycopg.rows import dict_row


# Re-exported so callers don't need to know the driver.
IntegrityError = psycopg.errors.IntegrityError
DatabaseError = psycopg.DatabaseError


def _resolve_host(cfg: Mapping[str, Any]) -> str:
    return os.environ.get("POSTGRES_HOST") or cfg.get("host") or "localhost"


def _resolve_port(cfg: Mapping[str, Any]) -> int:
    return int(os.environ.get("POSTGRES_PORT") or cfg.get("port") or 5432)


def _resolve_db(cfg: Mapping[str, Any]) -> str:
    return os.environ.get("POSTGRES_DB") or cfg.get("database") or "monitoring"


def _resolve_user(cfg: Mapping[str, Any]) -> str:
    return os.environ.get("POSTGRES_USER") or cfg.get("user") or "monitoring"


def _resolve_password(cfg: Mapping[str, Any]) -> str:
    return os.environ.get("POSTGRES_PASSWORD") or cfg.get("password") or "monitoring"


def connect(cfg: Mapping[str, Any] | None = None) -> psycopg.Connection:
    """Open a Postgres connection with dict rows + autocommit.

    `cfg` is the `postgres` section of config.yml. Env vars
    POSTGRES_HOST/PORT/DB/USER/PASSWORD always override the YAML values.
    """
    cfg = cfg or {}
    return psycopg.connect(
        host=_resolve_host(cfg),
        port=_resolve_port(cfg),
        dbname=_resolve_db(cfg),
        user=_resolve_user(cfg),
        password=_resolve_password(cfg),
        connect_timeout=5,
        autocommit=True,
        row_factory=dict_row,
    )

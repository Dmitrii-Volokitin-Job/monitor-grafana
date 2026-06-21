"""
sd_endpoints.py — Prometheus HTTP-SD service.

Exposes GET /sd/<type> endpoints returning Prometheus HTTP-SD JSON built from
the monitored_system table. Replaces the file_sd_configs path: instead of
Prometheus reading config/targets/*.yml off disk, it polls these endpoints
(refresh_interval: 30s) and discovers targets directly from the DB.

Response shape (Prometheus HTTP-SD):
    [
      {"targets": ["host:port"], "labels": {"system_id": "...", ...}},
      ...
    ]

Types served:
    /sd/http   — HTTP probes (Blackbox)        labels: system_id, display_name, system_group, __param_module
    /sd/tcp    — TCP probes (Blackbox)         same shape
    /sd/icmp   — ICMP pings (Blackbox)         labels: node_id, node_name, lab_group, node_type
    /sd/ssl    — SSL certs (ssl_exporter)      labels: cert_alias, cert_description

Each handler caches its result for SD_CACHE_TTL_S seconds to absorb scrape bursts.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable

try:
    import db as _db
except ImportError:
    from monitor_exporter import db as _db
from flask import Blueprint, Flask, jsonify

logger = logging.getLogger("sd_endpoints")

SD_CACHE_TTL_S = 10

# Module-level cache: {sd_type: (expires_at, payload)}
_cache: dict[str, tuple[float, list[dict]]] = {}
_cache_lock = threading.Lock()


def _connect(db_config: dict):
    return _db.connect(db_config)


# --- per-type row → HTTP-SD entry mappers --------------------------------------

def _http(row: dict) -> dict:
    return {
        "targets": [row["url"]] if row.get("url") else [],
        "labels": {
            "system_id": row["system_id"],
            "display_name": row.get("display_name") or "",
            "system_group": row.get("system_group") or "",
            "system_type": "HTTP",
            "__param_module": row.get("blackbox_module") or "http_2xx",
        },
    }


def _tcp(row: dict) -> dict:
    return {
        "targets": [row["url"]] if row.get("url") else [],
        "labels": {
            "system_id": row["system_id"],
            "display_name": row.get("display_name") or "",
            "system_group": row.get("system_group") or "",
            "system_type": "DATABASE",
            "__param_module": row.get("blackbox_module") or "tcp_connect",
        },
    }


def _icmp(row: dict) -> dict:
    nid = row.get("node_id") or row["system_id"]
    return {
        "targets": [row["url"]] if row.get("url") else [],
        "labels": {
            "node_id": nid,
            "node_name": row.get("node_name") or "",
            "lab_group": row.get("lab_group") or row.get("system_group") or "",
            "node_type": row.get("node_type") or "",
        },
    }


def _ssl(row: dict) -> dict:
    return {
        "targets": [row["url"]] if row.get("url") else [],
        "labels": {
            "cert_alias": row.get("cert_alias") or row["system_id"],
            "cert_description": row.get("cert_description") or row.get("display_name") or "",
        },
    }


def _grpc(row: dict) -> dict:
    return {
        "targets": [row["url"]] if row.get("url") else [],
        "labels": {
            "system_id": row["system_id"],
            "display_name": row.get("display_name") or "",
            "system_group": row.get("system_group") or "",
            "system_type": "GRPC",
            "__param_module": row.get("blackbox_module") or "grpc",
        },
    }


def _dns(row: dict) -> dict:
    return {
        "targets": [row["url"]] if row.get("url") else [],
        "labels": {
            "system_id": row["system_id"],
            "display_name": row.get("display_name") or "",
            "system_group": row.get("system_group") or "",
            "system_type": "DNS",
            "__param_module": row.get("blackbox_module") or "dns_udp",
        },
    }


_MAPPERS: dict[str, tuple[str, Callable[[dict], dict]]] = {
    "http": ("HTTP", _http),
    "tcp":  ("TCP",  _tcp),
    "icmp": ("ICMP", _icmp),
    "ssl":  ("SSL",  _ssl),
    "grpc": ("GRPC", _grpc),
    "dns":  ("DNS",  _dns),
}


def fetch(sd_type: str, db_config: dict) -> list[dict]:
    """Read enabled rows of the requested type from the DB and shape them."""
    system_type, mapper = _MAPPERS[sd_type]
    conn = _connect(db_config)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT system_id, display_name, system_group, url, "
                "       blackbox_module, node_id, node_name, lab_group, node_type, "
                "       cert_alias, cert_description "
                "FROM monitored_system "
                "WHERE system_type = %s AND is_enable = 1",
                (system_type,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [mapper(r) for r in rows if r.get("url")]


def cached_fetch(sd_type: str, db_config: dict) -> list[dict]:
    """fetch() with a per-type TTL cache."""
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(sd_type)
        if entry and entry[0] > now:
            return entry[1]
    # compute outside the lock so concurrent types don't serialize on the DB
    payload = fetch(sd_type, db_config)
    with _cache_lock:
        _cache[sd_type] = (now + SD_CACHE_TTL_S, payload)
    return payload


def create_blueprint(db_config: dict) -> Blueprint:
    bp = Blueprint("sd_endpoints", __name__)

    @bp.get("/sd/<sd_type>")
    def sd(sd_type: str):
        if sd_type not in _MAPPERS:
            return jsonify({"error": f"unknown sd type {sd_type!r}"}), 404
        try:
            payload = cached_fetch(sd_type, db_config)
        except Exception:
            logger.exception("SD fetch failed for %s", sd_type)
            return jsonify({"error": "internal"}), 500
        return jsonify(payload)

    @bp.get("/sd/healthz")
    def healthz():
        return {"ok": True}

    return bp


def start_sd_endpoints(config: dict, port: int = 9119) -> threading.Thread | None:
    """Start a Flask app exposing /sd/* in a daemon thread.

    If admin_ui is also enabled it will register its own Blueprint on the same
    app — see exporter.py main() for the composition order. When called
    standalone (admin UI disabled) this serves only the SD endpoints.
    """
    db_config = dict(config.get("postgres") or {})
    if env_host := os.environ.get("POSTGRES_HOST"):
        db_config["host"] = env_host
    if env_pw := os.environ.get("POSTGRES_PASSWORD"):
        db_config["password"] = env_pw
    if not db_config.get("enabled", False):
        logger.warning("Postgres disabled — SD endpoints will not start")
        return None

    app = Flask("sd_endpoints")
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    app.register_blueprint(create_blueprint(db_config))

    def run():
        logger.info("SD endpoints listening on 0.0.0.0:%d", port)
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)

    t = threading.Thread(target=run, daemon=True, name="sd-endpoints")
    t.start()
    return t

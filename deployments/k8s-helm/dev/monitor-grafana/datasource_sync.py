"""
datasource_sync.py — keep Grafana's datasources in lockstep with the
`datasource` table in Postgres.

Once a minute (configurable) the syncer:
  1. Reads enabled rows from the `datasource` table.
  2. Reads existing datasources from Grafana via /api/datasources.
  3. For each table row missing in Grafana → POST it (create).
  4. For each table row present but with changed url/type/user → PUT it.
  5. Disabled rows are NOT removed from Grafana (safer default — flipping
     is_enable in the admin UI just hides them from new dashboards; an
     explicit delete in the admin UI is needed to actually remove from
     Grafana).

Passwords are read from the environment variable named in `password_env`
on each row. Grafana itself stores them encrypted; we just hand them over.

Auth: uses GF_SECURITY_ADMIN_USER / GF_SECURITY_ADMIN_PASSWORD (the same
admin creds the human uses to log in). For prod you should provision a
service-account token and pass it via GRAFANA_SA_TOKEN — preferred when set.
"""
from __future__ import annotations

import logging
import os
import threading
import time

import httpx
try:
    import db as _db
except ImportError:
    from monitor_exporter import db as _db

logger = logging.getLogger("datasource_sync")

SYNC_INTERVAL_S = 60


def _connect(db_config: dict):
    return _db.connect(db_config)


def _grafana_client(internal_url: str) -> httpx.Client:
    token = os.environ.get("GRAFANA_SA_TOKEN")
    if token:
        return httpx.Client(base_url=internal_url, timeout=5.0,
                            headers={"Authorization": f"Bearer {token}"})
    user = os.environ.get("GF_SECURITY_ADMIN_USER", "admin")
    pw = os.environ.get("GF_SECURITY_ADMIN_PASSWORD", "admin")
    return httpx.Client(base_url=internal_url, timeout=5.0, auth=(user, pw))


def _to_grafana_payload(row: dict) -> dict:
    """Translate our table row to a Grafana /api/datasources payload."""
    payload = {
        "name": row["name"],
        "uid": row["name"],          # keep them identical
        "type": row["type"],
        "url": row["url"] if row["url"].startswith(("http://", "https://")) else f"http://{row['url']}",
        "access": "proxy",
        "database": row.get("database_name") or "",
        "user": row.get("db_user") or "",
        "isDefault": False,
        "jsonData": {},
    }
    # Drivers that talk SQL directly (mysql, postgres) want host:port in `url`
    # WITHOUT the http:// prefix that Grafana otherwise expects.
    if row["type"] in ("mysql", "postgres"):
        payload["url"] = row["url"]
    pw_env = row.get("password_env")
    if pw_env and (pw := os.environ.get(pw_env)):
        payload["secureJsonData"] = {"password": pw}
    return payload


def _list_table(db_config) -> list[dict]:
    conn = _connect(db_config)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM datasource WHERE is_enable = 1")
            return cur.fetchall()
    finally:
        conn.close()


def _diff(payload: dict, existing: dict) -> bool:
    """True if the Grafana entry should be PUT-updated to match `payload`."""
    for k in ("type", "url", "database", "user"):
        if payload.get(k, "") != existing.get(k, ""):
            return True
    return False


def sync_once(db_config: dict, internal_url: str) -> None:
    rows = _list_table(db_config)
    if not rows:
        return
    with _grafana_client(internal_url) as gf:
        try:
            r = gf.get("/api/datasources")
            if r.status_code != 200:
                logger.warning("Grafana /api/datasources returned %d; skipping cycle",
                               r.status_code)
                return
            existing = {ds["name"]: ds for ds in r.json()}
        except httpx.RequestError as e:
            logger.debug("Grafana unreachable, skipping sync: %s", e)
            return

        for row in rows:
            payload = _to_grafana_payload(row)
            if row["name"] not in existing:
                resp = gf.post("/api/datasources", json=payload)
                if resp.status_code in (200, 201):
                    logger.info("Created datasource %s", row["name"])
                else:
                    logger.warning("Create datasource %s failed: %d %s",
                                   row["name"], resp.status_code, resp.text[:200])
                continue
            ex = existing[row["name"]]
            if _diff(payload, ex):
                resp = gf.put(f"/api/datasources/uid/{row['name']}", json=payload)
                if resp.status_code == 200:
                    logger.info("Updated datasource %s", row["name"])
                else:
                    logger.warning("Update datasource %s failed: %d %s",
                                   row["name"], resp.status_code, resp.text[:200])


def start_datasource_sync(config: dict,
                          interval_s: int = SYNC_INTERVAL_S) -> threading.Thread | None:
    db_config = dict(config.get("postgres") or {})
    if env_host := os.environ.get("POSTGRES_HOST"):
        db_config["host"] = env_host
    if env_pw := os.environ.get("POSTGRES_PASSWORD"):
        db_config["password"] = env_pw
    if not db_config.get("enabled", False):
        return None
    internal_url = os.environ.get("GRAFANA_INTERNAL_URL", "http://grafana:3000")

    def loop():
        # Stagger initial run so we don't race Grafana's startup.
        time.sleep(15)
        while True:
            try:
                sync_once(db_config, internal_url)
            except Exception:
                logger.exception("datasource sync cycle failed")
            time.sleep(interval_s)

    t = threading.Thread(target=loop, daemon=True, name="datasource-sync")
    t.start()
    logger.info("datasource_sync started (interval=%ds, grafana=%s)", interval_s, internal_url)
    return t

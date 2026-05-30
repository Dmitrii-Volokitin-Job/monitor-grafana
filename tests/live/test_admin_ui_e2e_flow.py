"""
End-to-end live test: prove the admin UI → DB → HTTP-SD → Prometheus flow works.

Run with the docker compose stack up:
    docker compose up -d
    pytest tests/live/test_admin_ui_e2e_flow.py --live -v

What this test does (in order):
    1.  Log in to Grafana, capture the session cookie.
    2.  Read the current URL of `demo-a-api` via the admin UI's edit page.
    3.  POST a new URL through the admin UI form (real HTTP form, same as a browser).
    4.  Verify Postgres has the new URL row.
    5.  Verify the /sd/http endpoint serves the new URL.
    6.  Wait up to 60 s for Prometheus to refresh HTTP-SD and serve the new
        instance URL via its /api/v1/targets endpoint.
    7.  Restore the original URL so the test is repeatable.

If any step fails, the test fails — proving the change pipeline is broken end-to-end.
"""
import os
import time

import psycopg
import pytest
import requests
from psycopg.rows import dict_row


GRAFANA_URL  = os.environ.get("GRAFANA_URL", "http://localhost:3030")
GRAFANA_USER = os.environ.get("GRAFANA_USER", "admin")
GRAFANA_PW   = os.environ.get("GRAFANA_PW",   "admin")
ADMIN_URL    = os.environ.get("ADMIN_URL",   "http://localhost:9119")
PROM_URL     = os.environ.get("PROM_URL",    "http://localhost:9091")
PG_DSN = dict(
    host=os.environ.get("POSTGRES_HOST", "localhost"),
    port=int(os.environ.get("POSTGRES_PORT", "5433")),
    dbname="monitoring", user="monitoring", password="monitoring",
)

TEST_SYSTEM_ID = "demo-a-api"
NEW_URL = "https://httpbin.org/status/204"   # a different valid URL to swap to


pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def grafana_session():
    """Log into Grafana and return a requests.Session with the auth cookie."""
    s = requests.Session()
    r = s.post(
        f"{GRAFANA_URL}/login",
        json={"user": GRAFANA_USER, "password": GRAFANA_PW},
        timeout=5,
    )
    assert r.status_code == 200, f"Grafana login failed: {r.status_code} {r.text[:200]}"
    assert "grafana_session" in s.cookies, "no session cookie returned"
    return s


@pytest.fixture(scope="module")
def db_conn():
    conn = psycopg.connect(autocommit=True, row_factory=dict_row, **PG_DSN)
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def original_url(db_conn):
    """Capture the original URL up front so the test can restore it at teardown."""
    with db_conn.cursor() as cur:
        cur.execute("SELECT url FROM monitored_system WHERE system_id=%s", (TEST_SYSTEM_ID,))
        row = cur.fetchone()
    assert row, f"seed system {TEST_SYSTEM_ID} missing — bring up `docker compose up -d` first"
    return row["url"]


def _get_pk(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM monitored_system WHERE system_id=%s", (TEST_SYSTEM_ID,))
        return cur.fetchone()["id"]


def _form_row(db_conn) -> dict:
    """Read all the current values so we can POST a complete form (validation expects all required fields)."""
    with db_conn.cursor() as cur:
        cur.execute("SELECT * FROM monitored_system WHERE system_id=%s", (TEST_SYSTEM_ID,))
        return cur.fetchone()


def test_step_1_grafana_login_works(grafana_session):
    """Pre-flight: confirm the Grafana cookie actually authenticates."""
    r = grafana_session.get(f"{GRAFANA_URL}/api/user", timeout=5)
    assert r.status_code == 200, r.text
    assert r.json().get("login") == GRAFANA_USER


def test_step_2_admin_ui_reachable_with_session(grafana_session):
    """The admin UI must trust the Grafana session cookie for read access."""
    r = grafana_session.get(f"{ADMIN_URL}/admin/", timeout=5, allow_redirects=False)
    assert r.status_code == 200, (
        f"admin UI didn't accept the Grafana cookie: status={r.status_code} "
        f"location={r.headers.get('Location')}"
    )
    assert TEST_SYSTEM_ID in r.text, "systems list didn't render"


def test_step_3_can_edit_system_url_via_admin_ui(grafana_session, db_conn, original_url):
    """POST a form change through the admin UI exactly the way a browser would."""
    pk = _get_pk(db_conn)
    row = _form_row(db_conn)

    # Build the form payload — same field names as the Jinja form template
    payload = {
        "system_id":       row["system_id"],
        "display_name":    row["display_name"],
        "system_group":    row["system_group"],
        "system_type":     row["system_type"],
        "url":             NEW_URL,                  # ← the change
        "blackbox_module": row.get("blackbox_module") or "http_2xx",
        "timeout_seconds": str(row.get("timeout_seconds") or 10),
        "is_enable":       "1",
    }
    r = grafana_session.post(
        f"{ADMIN_URL}/admin/systems/{pk}",
        data=payload,
        timeout=10,
        allow_redirects=False,
    )
    assert r.status_code in (200, 302), (
        f"admin POST failed: {r.status_code}\n"
        f"body: {r.text[:500]}"
    )

    # DB must reflect the new URL
    with db_conn.cursor() as cur:
        cur.execute("SELECT url FROM monitored_system WHERE id=%s", (pk,))
        new = cur.fetchone()["url"]
    assert new == NEW_URL, f"DB URL didn't change — saw {new!r}"


def test_step_4_sd_endpoint_serves_new_url(grafana_session):
    """Prometheus HTTP-SD endpoint must serve the new URL on the next request.

    sd_endpoints.py caches responses for SD_CACHE_TTL_S = 10 seconds to absorb
    scrape bursts. We poll for up to 15 s to ride past that window.
    """
    # /sd/http is unauthenticated by design (Prometheus polls it)
    deadline = time.time() + 15
    targets = []
    while time.time() < deadline:
        r = requests.get(f"{ADMIN_URL}/sd/http", timeout=5)
        assert r.status_code == 200, r.text
        targets = [t for entry in r.json() for t in entry["targets"]]
        if NEW_URL in targets:
            return
        time.sleep(2)
    pytest.fail(f"new URL not in /sd/http after 15 s. Saw: {targets}")


def test_step_5_prometheus_picks_up_new_target():
    """Wait for Prometheus to refresh HTTP-SD (refresh_interval: 30s) and confirm
    the target URL is being scraped at the new URL."""
    deadline = time.time() + 90      # 30s HTTP-SD refresh + 60s slack
    last_seen = None
    while time.time() < deadline:
        r = requests.get(f"{PROM_URL}/api/v1/targets", timeout=5)
        r.raise_for_status()
        instances = [
            t.get("labels", {}).get("instance")
            for t in r.json().get("data", {}).get("activeTargets", [])
            if t.get("labels", {}).get("system_id") == TEST_SYSTEM_ID
        ]
        last_seen = instances
        if NEW_URL in instances:
            return       # success
        time.sleep(3)
    pytest.fail(
        f"Prometheus never saw the new URL within 90 s. "
        f"Last targets for {TEST_SYSTEM_ID}: {last_seen}"
    )


def test_step_6_restore_original_url(grafana_session, db_conn, original_url):
    """Teardown: put the original URL back so the test is idempotent."""
    pk = _get_pk(db_conn)
    row = _form_row(db_conn)
    payload = {
        "system_id":       row["system_id"],
        "display_name":    row["display_name"],
        "system_group":    row["system_group"],
        "system_type":     row["system_type"],
        "url":             original_url,
        "blackbox_module": row.get("blackbox_module") or "http_2xx",
        "timeout_seconds": str(row.get("timeout_seconds") or 10),
        "is_enable":       "1",
    }
    r = grafana_session.post(
        f"{ADMIN_URL}/admin/systems/{pk}",
        data=payload, timeout=10, allow_redirects=False,
    )
    assert r.status_code in (200, 302)
    with db_conn.cursor() as cur:
        cur.execute("SELECT url FROM monitored_system WHERE id=%s", (pk,))
        assert cur.fetchone()["url"] == original_url, "restore failed"

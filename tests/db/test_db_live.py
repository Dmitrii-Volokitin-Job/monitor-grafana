"""
Live Postgres tests — require --live flag and running Docker Compose stack.

These tests verify the REAL database state: schema integrity, FK constraints,
actual health_check_history rows written by the exporter, and that the data
Grafana queries match what was stored.

Run with: pytest tests/db/test_db_live.py --live
"""
import pytest
from datetime import datetime, timedelta

pytestmark = pytest.mark.live


# ---------------------------------------------------------------------------
# Schema integrity — verify tables exist with correct structure
# ---------------------------------------------------------------------------

def _fetch_columns(conn, table):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = %s "
            "ORDER BY ordinal_position",
            (table,)
        )
        return {row[0]: {"type": row[1], "nullable": row[2]} for row in cur.fetchall()}


def test_live_monitored_system_table_exists(live_postgres):
    cols = _fetch_columns(live_postgres, "monitored_system")
    assert cols, "monitored_system table does not exist or has no columns"
    assert "system_id" in cols
    assert "display_name" in cols
    assert "system_group" in cols
    assert "system_type" in cols


def test_live_health_check_history_table_exists(live_postgres):
    cols = _fetch_columns(live_postgres, "health_check_history")
    assert cols, "health_check_history table does not exist"
    assert "system_id" in cols
    assert "check_timestamp" in cols
    assert "status" in cols
    assert "response_time_ms" in cols
    assert "error_message" in cols


def test_live_status_column_allows_up_and_down(live_postgres):
    """Verify status values in the table are only UP or DOWN."""
    with live_postgres.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT status FROM health_check_history WHERE status NOT IN ('UP', 'DOWN')"
        )
        bad_rows = cur.fetchall()
    assert not bad_rows, \
        f"health_check_history contains invalid status values: {bad_rows}"


def test_live_monitored_system_has_rows(live_postgres):
    """Exporter sync_systems() should have populated monitored_system on startup."""
    with live_postgres.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM monitored_system")
        count = cur.fetchone()[0]
    assert count > 0, \
        "monitored_system is empty — exporter may not have run sync_systems() yet"


def test_live_all_system_ids_are_unique(live_postgres):
    with live_postgres.cursor() as cur:
        cur.execute(
            "SELECT system_id, COUNT(*) AS cnt FROM monitored_system "
            "GROUP BY system_id HAVING COUNT(*) > 1"
        )
        dupes = cur.fetchall()
    assert not dupes, f"Duplicate system_ids in monitored_system: {dupes}"


# ---------------------------------------------------------------------------
# Health check history — verify exporter is writing data
# ---------------------------------------------------------------------------

def test_live_health_check_history_has_recent_rows(live_postgres):
    """Exporter runs every 5 min — there should be rows within the last 15 minutes."""
    with live_postgres.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM health_check_history "
            "WHERE check_timestamp >= NOW() - INTERVAL '15 minutes'"
        )
        count = cur.fetchone()[0]
    assert count > 0, (
        "No health_check_history rows in the last 15 minutes. "
        "The exporter may not be running or DB logging is disabled."
    )


def test_live_health_check_history_fk_integrity(live_postgres):
    """All health_check_history.system_id values must exist in monitored_system."""
    with live_postgres.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM health_check_history hch "
            "LEFT JOIN monitored_system ms ON hch.system_id = ms.id "
            "WHERE ms.id IS NULL"
        )
        orphans = cur.fetchone()[0]
    assert orphans == 0, \
        f"{orphans} health_check_history rows have orphaned system_id FK"


# Types that the monitor_exporter writes to health_check_history (via _record_check
# or log_check_batch). Other types (DNS/GRPC/SSL/VERSION) are probed by
# blackbox-exporter / ssl-exporter and flow straight into Prometheus, so they
# legitimately have zero rows in health_check_history.
EXPORTER_LOGGED_TYPES = (
    "HTTP", "LDAP", "KEYCLOAK", "DATABASE", "POSTGRES", "MONGODB",
    "REDIS", "ELASTICSEARCH", "ICMP", "TCP",
)


def test_live_every_exporter_logged_type_has_recent_check(live_postgres):
    """
    Every system *type* the exporter logs should have at least one row in
    health_check_history within the last hour — proves the logging path works.

    Per-system coverage is NOT asserted: the seed data includes ~250 demo rows
    that are never probed; only one or two representative systems per type are
    actually monitored end-to-end.
    """
    with live_postgres.cursor() as cur:
        cur.execute(
            "SELECT t.system_type "
            "FROM (VALUES " + ", ".join(["(%s)"] * len(EXPORTER_LOGGED_TYPES)) + ") "
            "  AS t(system_type) "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM monitored_system ms "
            "  JOIN health_check_history hch ON hch.system_id = ms.id "
            "  WHERE ms.system_type = t.system_type "
            "  AND ms.is_enable = 1 "
            "  AND hch.check_timestamp >= NOW() - INTERVAL '1 hour'"
            ")",
            EXPORTER_LOGGED_TYPES,
        )
        missing = [row[0] for row in cur.fetchall()]

    if missing:
        pytest.fail(
            f"{len(missing)} exporter-logged type(s) have NO recent health "
            f"check in the last hour — exporter may have stopped writing for "
            f"these types: {missing}"
        )


def test_live_response_times_are_positive(live_postgres):
    """All logged response times should be > 0 ms."""
    with live_postgres.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM health_check_history "
            "WHERE response_time_ms IS NOT NULL AND response_time_ms <= 0"
        )
        bad = cur.fetchone()[0]
    assert bad == 0, f"{bad} rows have non-positive response_time_ms"


# ---------------------------------------------------------------------------
# Status counts — compare DB with expected monitoring reality
# ---------------------------------------------------------------------------

def test_live_status_distribution(live_postgres):
    """Print UP/DOWN distribution for last check cycle (informational)."""
    with live_postgres.cursor() as cur:
        cur.execute(
            "SELECT ms.system_group, hch.status, COUNT(*) AS cnt "
            "FROM health_check_history hch "
            "JOIN monitored_system ms ON hch.system_id = ms.id "
            "WHERE hch.check_timestamp = ("
            "  SELECT MAX(check_timestamp) FROM health_check_history hch2 "
            "  WHERE hch2.system_id = hch.system_id"
            ") "
            "GROUP BY ms.system_group, hch.status "
            "ORDER BY ms.system_group, hch.status"
        )
        rows = cur.fetchall()

    print("\n\nLatest status per system group:")
    print(f"{'Group':<20} {'Status':<8} {'Count':>5}")
    print("-" * 38)
    for group, status, cnt in rows:
        print(f"{group:<20} {status:<8} {cnt:>5}")

    assert rows, "No status distribution data found"


def test_live_no_excessive_error_messages(live_postgres):
    """Error messages should not be excessively long (indicates truncation working)."""
    with live_postgres.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM health_check_history "
            "WHERE error_message IS NOT NULL AND LENGTH(error_message) > 500"
        )
        too_long = cur.fetchone()[0]
    assert too_long == 0, \
        f"{too_long} rows have error_message > 500 chars (truncation not working)"


# ---------------------------------------------------------------------------
# Write a test row and read it back — end-to-end DB flow
# ---------------------------------------------------------------------------

def test_live_write_and_read_health_check_row(live_postgres):
    """
    Insert a test health_check_history row and verify it's readable.
    Confirms the full write→read path that Grafana uses for history panels.
    Cleans up after itself.
    """
    # Find any existing system to use as FK
    with live_postgres.cursor() as cur:
        cur.execute("SELECT id, system_id FROM monitored_system LIMIT 1")
        row = cur.fetchone()
    if not row:
        pytest.skip("No systems in monitored_system — cannot test write/read")

    pk, system_id = row
    test_note = "TEST_ROW_pytest"

    try:
        # Write
        with live_postgres.cursor() as cur:
            cur.execute(
                "INSERT INTO health_check_history "
                "(system_id, check_timestamp, status, response_time_ms, error_message) "
                "VALUES (%s, NOW(), 'UP', 42, %s) RETURNING id",
                (pk, test_note)
            )
            inserted_id = cur.fetchone()[0]

        # Read back
        with live_postgres.cursor() as cur:
            cur.execute(
                "SELECT status, response_time_ms, error_message "
                "FROM health_check_history WHERE id = %s",
                (inserted_id,)
            )
            result = cur.fetchone()

        assert result is not None, "Inserted row not found"
        assert result[0] == "UP"
        assert result[1] == 42
        assert result[2] == test_note

    finally:
        # Cleanup
        with live_postgres.cursor() as cur:
            cur.execute("DELETE FROM health_check_history WHERE error_message = %s",
                        (test_note,))

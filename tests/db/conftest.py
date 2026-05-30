"""DB test fixtures: in-memory SQLite (unit) + live Postgres (--live)."""
import os

import pytest
import sqlite3


@pytest.fixture
def sqlite_db():
    """In-memory SQLite with schema matching the Postgres tables we care about.

    SQLite isn't a Postgres replica — it's a fast fixture for tests that only
    need basic CRUD against `monitored_system`, `health_check_history`, and
    `alert_state`. Tests that need Postgres-specific syntax should target the
    live DB via the `live_postgres` fixture.
    """
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE monitored_system (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            system_id TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            system_group TEXT NOT NULL,
            system_type TEXT DEFAULT 'HTTP',
            url TEXT,
            is_enable INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE health_check_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            system_id INTEGER NOT NULL,
            check_timestamp DATETIME NOT NULL,
            status TEXT NOT NULL,
            http_status_code INTEGER,
            response_time_ms INTEGER,
            error_message TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE alert_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            system_id INTEGER NOT NULL,
            current_status TEXT NOT NULL DEFAULT 'UP',
            current_severity TEXT,
            down_since DATETIME,
            last_status_change DATETIME DEFAULT CURRENT_TIMESTAMP,
            alert_count INTEGER DEFAULT 0
        );
    """)
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def live_postgres(request):
    """Real Postgres connection — requires --live flag and running Docker stack."""
    if not request.config.getoption("--live"):
        pytest.skip("Requires --live flag")
    import psycopg
    host = os.environ.get("POSTGRES_HOST") or request.config.getoption("--postgres-host", default="127.0.0.1")
    port = int(os.environ.get("POSTGRES_PORT") or request.config.getoption("--postgres-port", default=5433))
    conn = psycopg.connect(
        host=host, port=port, dbname="monitoring",
        user="monitoring", password="monitoring",
        autocommit=True, connect_timeout=10,
    )
    yield conn
    conn.close()

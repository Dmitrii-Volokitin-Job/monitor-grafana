"""
Parse 01-schema.sql and assert structural expectations.
These tests run without a database — they validate the DDL file itself.
"""
import os
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
SCHEMA_FILE = os.path.join(PROJECT_ROOT, "docker", "init-db", "01-schema.sql")


@pytest.fixture(scope="module")
def schema_sql():
    with open(SCHEMA_FILE) as f:
        return f.read()


def test_schema_file_exists():
    assert os.path.exists(SCHEMA_FILE), f"Schema file not found: {SCHEMA_FILE}"


def test_monitored_system_table_defined(schema_sql):
    assert "CREATE TABLE IF NOT EXISTS monitored_system" in schema_sql


def test_health_check_history_table_defined(schema_sql):
    assert "CREATE TABLE IF NOT EXISTS health_check_history" in schema_sql


def test_alert_state_table_defined(schema_sql):
    assert "CREATE TABLE IF NOT EXISTS alert_state" in schema_sql


def test_email_log_table_defined(schema_sql):
    assert "CREATE TABLE IF NOT EXISTS email_log" in schema_sql


def test_monitored_system_has_unique_system_id(schema_sql):
    # Postgres: inline UNIQUE on the column
    assert "system_id VARCHAR(100) NOT NULL UNIQUE" in schema_sql


def test_health_check_history_fk_to_monitored_system(schema_sql):
    # Postgres: inline REFERENCES on the column declaration
    assert "system_id BIGINT NOT NULL REFERENCES monitored_system(id)" in schema_sql


def test_health_check_history_status_column(schema_sql):
    # status column must exist and be VARCHAR type
    assert "status VARCHAR" in schema_sql


def test_response_time_column_is_bigint(schema_sql):
    assert "response_time_ms BIGINT" in schema_sql


def test_error_message_is_text_type(schema_sql):
    assert "error_message TEXT" in schema_sql


def test_check_timestamp_index_defined(schema_sql):
    assert "idx_hch_check_ts" in schema_sql


def test_system_id_index_on_history(schema_sql):
    assert "idx_hch_system_id" in schema_sql


# ---------------------------------------------------------------------------
# Seed-data regression — every `monitored_system` row must point at a REAL
# target (or a bundled `demo-*-target` container hostname). The previous demo
# seed used `example.com`, `192.0.2.x` (RFC 5737), and `10.0.0.x` (RFC 1918)
# placeholders — dashboards then showed flat-DOWN tiles on first boot. Locking
# this contract means a future PR can't quietly regress.
# ---------------------------------------------------------------------------

_MONITORED_SEED_FILES = [
    "docker/init-db/07-seed-systems.sql",
    "docker/init-db/09-seed-new-types-and-datasources.sql",
]

# Substrings that prove a row points at a non-routable placeholder. Kept
# narrow so legitimate uses elsewhere in the file (datasource templates,
# email recipients) aren't flagged.
_PLACEHOLDER_HOSTS = ("example.com:", "//example.com/", "192.0.2.", "10.0.0.")


def _monitored_system_insert_block(sql_text: str) -> str:
    """Slice out the `INSERT INTO monitored_system … ON CONFLICT` block.
    Other INSERTs (lab, datasource, email_log) are intentionally allowed to
    keep example.com / placeholder addresses — they're templates, not probes."""
    start_marker = "INSERT INTO monitored_system"
    start = sql_text.find(start_marker)
    if start == -1:
        return ""
    end = sql_text.find("ON CONFLICT", start)
    return sql_text[start:end] if end != -1 else sql_text[start:]


@pytest.mark.parametrize("rel_path", _MONITORED_SEED_FILES)
def test_monitored_system_seed_has_no_placeholder_hosts(rel_path):
    abs_path = os.path.join(PROJECT_ROOT, rel_path)
    with open(abs_path) as f:
        block = _monitored_system_insert_block(f.read())
    assert block, f"{rel_path}: no INSERT INTO monitored_system block found"
    offenders = [marker for marker in _PLACEHOLDER_HOSTS if marker in block]
    assert not offenders, (
        f"{rel_path}: monitored_system seed contains placeholder host(s) "
        f"{offenders}. Real public services or bundled `demo-*-target` "
        "hostnames are required so dashboards show live data on first boot. "
        "If a row genuinely has no public service, point it at a bundled "
        "container (see docker-compose `profiles: ['full']`)."
    )


# ---------------------------------------------------------------------------
# Cross-contract: every name in admin_ui.ALL_FIELDS must be an actual column
# on the `monitored_system` table. Drift would cause the admin UI form to
# generate INSERTs with missing columns (form save 500s), or — worse — to
# silently store form fields nowhere. The form-side test in
# tests/unit/test_admin_ui_crud.py already checks form↔ALL_FIELDS; this
# checks ALL_FIELDS↔DDL.
# ---------------------------------------------------------------------------

def _ddl_columns_of_monitored_system(ddl_text: str) -> set[str]:
    """Parse 01-schema.sql + 06-extend-monitored-system.sql; return the
    set of column names declared for the monitored_system table."""
    import re
    cols: set[str] = set()
    m = re.search(r"CREATE TABLE IF NOT EXISTS monitored_system\s*\((.*?)\);",
                  ddl_text, re.S)
    if m:
        for line in m.group(1).split("\n"):
            line = line.strip().rstrip(",")
            if not line or line.upper().startswith(
                ("PRIMARY", "FOREIGN", "UNIQUE", "CONSTRAINT", "CHECK")
            ):
                continue
            tok = line.split()[0] if line.split() else ""
            if tok and tok.replace("_", "").isalnum():
                cols.add(tok)
    for m2 in re.finditer(r"ADD COLUMN(?:\s+IF NOT EXISTS)?\s+(\w+)",
                          ddl_text, re.IGNORECASE):
        cols.add(m2.group(1))
    return cols


def test_all_fields_subset_of_ddl_columns():
    """Read ALL_FIELDS via text parse (avoids importing admin_ui, which would
    require psycopg in the test env). Assert every name exists as a real
    column in the monitored_system DDL."""
    import re
    src = open(os.path.join(PROJECT_ROOT, "monitor_exporter", "admin_ui.py")).read()
    block = src.split("ALL_FIELDS = [", 1)[1].split("]", 1)[0]
    all_fields = set(re.findall(r'"([a-z_]+)"', block))
    ddl_text = (
        open(os.path.join(PROJECT_ROOT, "docker", "init-db", "01-schema.sql")).read()
        + open(os.path.join(PROJECT_ROOT, "docker", "init-db",
                            "06-extend-monitored-system.sql")).read()
    )
    cols = _ddl_columns_of_monitored_system(ddl_text)
    missing = all_fields - cols
    assert not missing, (
        f"admin_ui.ALL_FIELDS names columns that do not exist in the "
        f"monitored_system DDL: {sorted(missing)}. Either drop them from "
        "ALL_FIELDS or add an ADD COLUMN migration."
    )


def test_seed_system_types_are_in_python_allowlist():
    """Every `system_type` literal in the SQL seed INSERTs must be a valid
    type per admin_ui.SYSTEM_TYPES. A typo (`DATABSE`) here would let the
    seed load but the row would never match a probe function — silent break."""
    import re
    src = open(os.path.join(PROJECT_ROOT, "monitor_exporter", "admin_ui.py")).read()
    req_block = src.split("REQUIRED_FIELDS: dict[str, list[str]] = {", 1)[1].split("}", 1)[0]
    allowed_types = set(re.findall(r'"([A-Z][A-Z_]+)":', req_block))
    assert allowed_types, "could not parse SYSTEM_TYPES from admin_ui.py"

    # `node_type` (SERVER/MASTER/WORKER/...) also appears as a quoted ALL-CAPS
    # literal in the seed for ICMP rows. Subtract its allowlist so we don't
    # false-positive on it.
    node_block = src.split("NODE_TYPES = [", 1)[1].split("]", 1)[0]
    node_types = set(re.findall(r'"([A-Z][A-Z_]+)"', node_block))

    used = set()
    for rel in _MONITORED_SEED_FILES:
        text = open(os.path.join(PROJECT_ROOT, rel)).read()
        block = _monitored_system_insert_block(text)
        for tok in re.findall(r"'([A-Z][A-Z_]+)'", block):
            used.add(tok)

    unknown = used - allowed_types - node_types
    assert not unknown, (
        f"seed uses system_type value(s) not in admin_ui.SYSTEM_TYPES: "
        f"{sorted(unknown)}. Either fix the seed typo or add the new type "
        f"to REQUIRED_FIELDS. Allowed: {sorted(allowed_types)}"
    )


def test_helm_chart_schema_matches_canonical_columns():
    """The Helm chart re-embeds 01-schema.sql + 06-extend-monitored-system.sql
    in templates/monitor-db-init.yaml. The two copies MUST declare the same
    set of monitored_system columns or K8s installs diverge from compose."""
    canonical = _ddl_columns_of_monitored_system(
        open(os.path.join(PROJECT_ROOT, "docker", "init-db", "01-schema.sql")).read()
        + open(os.path.join(PROJECT_ROOT, "docker", "init-db",
                            "06-extend-monitored-system.sql")).read()
    )
    chart = _ddl_columns_of_monitored_system(open(os.path.join(
        PROJECT_ROOT, "deployments", "k8s-helm", "dev", "monitor-grafana",
        "templates", "monitor-db-init.yaml")).read())
    only_in_canonical = canonical - chart
    only_in_chart = chart - canonical
    assert not (only_in_canonical or only_in_chart), (
        f"chart vs canonical schema drift — "
        f"canonical-only: {sorted(only_in_canonical)}, "
        f"chart-only: {sorted(only_in_chart)}. "
        "Mirror docker/init-db/*.sql into templates/monitor-db-init.yaml."
    )

"""Load all dashboard JSONs and provisioned datasource UIDs."""
import json
import os
import re
import pytest
import yaml

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
DASHBOARDS_DIR = os.path.join(PROJECT_ROOT, "dashboards")

EXPECTED_DASHBOARDS = [
    "alert-history.json",
    "historical-data.json",
    "ssl-certificates.json",
    "system-health-overview.json",
    "uptime-statistics.json",
]

# UIDs from datasources.yml + built-in Grafana types
PROVISIONED_DS_UIDS = {
    "monitor-prometheus",
    "monitor-postgres",
    "monitor-duplex-loki",
    "grafana",
    "__expr__",
}

# Dashboard-variable datasources like ${DS_MARIADB} or ${db} are also valid.
# Grafana variable names may use any case (canonical convention is UPPER for
# datasource-type vars, lowercase for query-type vars).
VARIABLE_DS_RE = re.compile(r"^\$\{[A-Za-z][A-Za-z0-9_]*\}$")


def iter_panels(panels):
    """Recursively yield all panels, including those nested inside rows."""
    for panel in panels:
        yield panel
        for sub in panel.get("panels", []):
            yield sub


@pytest.fixture(scope="session")
def all_dashboards():
    result = {}
    for fname in EXPECTED_DASHBOARDS:
        path = os.path.join(DASHBOARDS_DIR, fname)
        with open(path) as f:
            result[fname] = json.load(f)
    return result


@pytest.fixture(scope="session", params=EXPECTED_DASHBOARDS)
def dashboard(request, all_dashboards):
    """Parametrized fixture — one test instance per dashboard file."""
    return request.param, all_dashboards[request.param]

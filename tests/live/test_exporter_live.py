"""
Live tests for the Monitor Exporter (:9116/metrics).

Verifies that all expected metric families are present and have valid values.
"""
import re
import pytest
import requests

pytestmark = pytest.mark.live


def parse_metrics(text: str) -> dict:
    """Parse Prometheus text exposition into {metric_name: [{labels, value}]}."""
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # metric_name{labels} value or metric_name value
        match = re.match(r'^([a-zA-Z_:][a-zA-Z0-9_:]*?)(\{[^}]*\})?\s+([\d.eE+\-]+|NaN)$', line)
        if match:
            name, labels_str, value = match.groups()
            if name not in result:
                result[name] = []
            result[name].append({"labels": labels_str or "", "value": value})
    return result


@pytest.fixture(scope="module")
def metrics_text(exporter_url):
    resp = requests.get(f"{exporter_url}/metrics", timeout=15)
    assert resp.status_code == 200, f"Exporter /metrics returned {resp.status_code}"
    return resp.text


@pytest.fixture(scope="module")
def metrics(metrics_text):
    return parse_metrics(metrics_text)


# ---------------------------------------------------------------------------
# Endpoint reachability
# ---------------------------------------------------------------------------

def test_exporter_metrics_endpoint_reachable(exporter_url):
    resp = requests.get(f"{exporter_url}/metrics", timeout=15)
    assert resp.status_code == 200


def test_exporter_response_is_text_plain(exporter_url):
    resp = requests.get(f"{exporter_url}/metrics", timeout=15)
    assert "text/plain" in resp.headers.get("Content-Type", "")


# ---------------------------------------------------------------------------
# Required metric families present
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("metric_name", [
    "monitor_ldap_up",
    "monitor_ldap_response_time_ms",
    "monitor_keycloak_up",
    "monitor_keycloak_response_time_ms",
    "monitor_keycloak_realm_valid",
    "monitor_database_up",
    "monitor_database_response_time_ms",
    "monitor_check_result_info",
])
def test_required_metric_family_present(metrics, metric_name):
    assert metric_name in metrics, \
        f"Metric '{metric_name}' missing from /metrics output"


# ---------------------------------------------------------------------------
# Value constraints — all UP/DOWN gauges must be 0 or 1
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("gauge_name", [
    "monitor_ldap_up",
    "monitor_keycloak_up",
    "monitor_database_up",
    "monitor_keycloak_realm_valid",
])
def test_gauge_values_are_binary(metrics, gauge_name):
    series = metrics.get(gauge_name, [])
    assert series, f"No time series for {gauge_name}"
    bad = [s for s in series if s["value"] not in ("0.0", "1.0", "0", "1")]
    assert not bad, \
        f"{gauge_name} has non-binary values: {[s['value'] for s in bad]}"


def test_response_times_are_non_negative(metrics):
    for metric in ("monitor_ldap_response_time_ms", "monitor_keycloak_response_time_ms",
                   "monitor_database_response_time_ms"):
        for series in metrics.get(metric, []):
            assert float(series["value"]) >= 0, \
                f"{metric} has negative response time: {series}"


# ---------------------------------------------------------------------------
# Target count verification
# ---------------------------------------------------------------------------

def test_ldap_metric_count_matches_config(metrics, exporter_config_live):
    expected = len(exporter_config_live.get("ldap_targets", []))
    actual = len(metrics.get("monitor_ldap_up", []))
    assert actual == expected, \
        f"Expected {expected} LDAP series in monitor_ldap_up, got {actual}"


def test_keycloak_metric_count_matches_config(metrics, exporter_config_live):
    expected = len(exporter_config_live.get("keycloak_targets", []))
    actual = len(metrics.get("monitor_keycloak_up", []))
    assert actual == expected, \
        f"Expected {expected} Keycloak series in monitor_keycloak_up, got {actual}"


def test_database_metric_count_matches_config(metrics, exporter_config_live):
    # config.yml is no longer the only source — the exporter also reads
    # DATABASE-type rows from monitored_system. So require AT LEAST the
    # configured count; the actual count may be larger because of DB rows.
    expected_min = len(exporter_config_live.get("database_targets", []))
    actual = len(metrics.get("monitor_database_up", []))
    assert actual >= expected_min, \
        f"Expected ≥{expected_min} DB series in monitor_database_up, got {actual}"

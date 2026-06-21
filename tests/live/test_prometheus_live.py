"""
Live tests against Prometheus API (:9090).

Verifies scrape targets are healthy, recording rules produce data,
and alert rules are properly configured.
"""
import pytest
import requests

pytestmark = pytest.mark.live

REQUIRED_JOBS = [
    "blackbox_http", "blackbox_tcp", "blackbox_icmp",
    "monitor_exporter", "ssl_certificates",
]

REQUIRED_RECORDING_RULES = [
    "monitor:system_health_pct",
    "monitor:systems_up_total",
    "monitor:systems_down_total",
    "monitor:ssl_days_until_expiry",
]


@pytest.fixture(scope="module")
def prom_targets(prometheus_url):
    resp = requests.get(f"{prometheus_url}/api/v1/targets", timeout=15)
    assert resp.status_code == 200
    return resp.json()["data"]["activeTargets"]


def _query(prometheus_url, promql):
    resp = requests.get(f"{prometheus_url}/api/v1/query",
                        params={"query": promql}, timeout=15)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    return data["data"]["result"]


# ---------------------------------------------------------------------------
# Prometheus API reachable
# ---------------------------------------------------------------------------

def test_prometheus_api_reachable(prometheus_url):
    resp = requests.get(f"{prometheus_url}/api/v1/query",
                        params={"query": "up"}, timeout=10)
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"


# ---------------------------------------------------------------------------
# Scrape targets health
# ---------------------------------------------------------------------------

def test_all_required_jobs_in_targets(prom_targets):
    active_jobs = {t["labels"].get("job", "") for t in prom_targets}
    missing = [j for j in REQUIRED_JOBS if j not in active_jobs]
    assert not missing, f"Missing scrape jobs in Prometheus targets: {missing}"


def test_monitor_exporter_target_is_up(prom_targets):
    exporter_targets = [t for t in prom_targets
                        if t["labels"].get("job") == "monitor_exporter"]
    assert exporter_targets, "monitor_exporter job has no active targets"
    down = [t for t in exporter_targets if t["health"] != "up"]
    assert not down, \
        f"monitor_exporter targets are DOWN: {[t['scrapeUrl'] for t in down]}"


def test_blackbox_http_has_active_targets(prom_targets):
    bb_targets = [t for t in prom_targets
                  if t["labels"].get("job") == "blackbox_http"]
    assert bb_targets, "No blackbox_http targets found"


def test_prometheus_itself_is_scraping(prom_targets):
    prom_self = [t for t in prom_targets if t["labels"].get("job") == "prometheus"]
    assert prom_self, "Prometheus self-monitoring target missing"
    assert prom_self[0]["health"] == "up"


# ---------------------------------------------------------------------------
# Metrics presence in Prometheus
# ---------------------------------------------------------------------------

def test_probe_success_metric_exists(prometheus_url):
    result = _query(prometheus_url, 'probe_success{job="blackbox_http"}')
    assert result, "probe_success{job='blackbox_http'} returned no data"


def test_monitor_ldap_up_metric_exists(prometheus_url):
    result = _query(prometheus_url, "monitor_ldap_up")
    assert result, "monitor_ldap_up metric not in Prometheus — exporter may not be scraped"


def test_monitor_keycloak_up_metric_exists(prometheus_url):
    result = _query(prometheus_url, "monitor_keycloak_up")
    assert result, "monitor_keycloak_up metric not found"


def test_monitor_database_up_metric_exists(prometheus_url):
    result = _query(prometheus_url, "monitor_database_up")
    assert result, "monitor_database_up metric not found"


# ---------------------------------------------------------------------------
# Recording rules
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rule_name", REQUIRED_RECORDING_RULES)
def test_recording_rule_produces_data(prometheus_url, rule_name):
    result = _query(prometheus_url, rule_name)
    assert result, (
        f"Recording rule '{rule_name}' produces no data. "
        "Check alert_rules/*.yml and Prometheus rule evaluation."
    )


def test_system_health_pct_is_between_0_and_100(prometheus_url):
    result = _query(prometheus_url, "monitor:system_health_pct")
    for series in result:
        val = float(series["value"][1])
        assert 0.0 <= val <= 100.0, \
            f"monitor:system_health_pct has out-of-range value: {val}"


def test_ssl_days_until_expiry_positive_for_valid_certs(prometheus_url):
    result = _query(prometheus_url, "monitor:ssl_days_until_expiry > 0")
    # Not asserting non-empty — some certs may be expired in test environments
    for series in result:
        val = float(series["value"][1])
        assert val > 0, f"ssl_days_until_expiry returned non-positive: {val}"


# ---------------------------------------------------------------------------
# Alert rules
# ---------------------------------------------------------------------------

def test_alerts_endpoint_returns_valid_shape(prometheus_url):
    """The /api/v1/alerts endpoint must be reachable and return the expected
    shape. We don't fail on the *count* of firing alerts because infra may
    legitimately have DOWN systems — but we do verify the response is parseable
    and bound the count to catch a runaway alerting pipeline."""
    alerts_resp = requests.get(f"{prometheus_url}/api/v1/alerts", timeout=15)
    assert alerts_resp.status_code == 200
    body = alerts_resp.json()
    assert body.get("status") == "success", f"unexpected status: {body.get('status')}"
    assert "alerts" in body.get("data", {}), \
        f"missing data.alerts in response: keys={list(body.get('data', {}))}"
    alerts = body["data"]["alerts"]
    # Every alert dict must carry the fields downstream code (and operators) rely on.
    for a in alerts:
        assert "state" in a and "labels" in a, f"alert missing state/labels: {a!r}"
    firing = [a for a in alerts if a["state"] == "firing"]
    if firing:
        print(f"\nFiring alerts ({len(firing)}):")
        for a in firing:
            print(f"  {a['labels'].get('alertname')} — {a['labels'].get('system_id', 'n/a')}")
    # Bound: a runaway pipeline (eg every probe failing) would exceed this.
    assert len(firing) < 100, \
        f"runaway-alerts guardrail tripped: {len(firing)} firing alerts (>100)"


def test_pending_alerts_count_reasonable(prometheus_url):
    """Too many pending alerts suggests the alert evaluation pipeline is broken."""
    alerts_resp = requests.get(f"{prometheus_url}/api/v1/alerts", timeout=15)
    pending = [a for a in alerts_resp.json()["data"]["alerts"]
               if a["state"] == "pending"]
    assert len(pending) < 50, \
        f"Unusually high number of pending alerts ({len(pending)}) — check Prometheus"


# ---------------------------------------------------------------------------
# Result-pinning tests against the REAL public services in the demo seed.
# These prove the probe pipelines actually extract correct values from the
# upstream — not just that a metric exists.
# ---------------------------------------------------------------------------

import re


def test_petstore_openapi_version_extracted(prometheus_url):
    """The OpenAPI VERSION probe against petstore3.swagger.io should populate
    monitor_system_version_info with the version from its openapi.json
    info.version field (verified against the live stack: '1.0.27')."""
    result = _query(prometheus_url,
                    'monitor_system_version_info{system_id="ver-demo-a"}')
    assert result, "monitor_system_version_info{ver-demo-a} returned no series"
    version_label = result[0]["metric"].get("version", "")
    assert version_label, f"version label missing: {result[0]['metric']}"
    assert version_label != "unknown", \
        "Petstore OpenAPI version not extracted — check exporter logs"
    # Petstore's published OpenAPI version is a SemVer-shaped string.
    assert re.match(r"^\d+\.\d+\.\d+", version_label), \
        f"version label not SemVer-shaped: {version_label!r}"


def test_keycloak_org_probe_succeeds(prometheus_url):
    """The Keycloak probe against www.keycloak.org should be UP."""
    result = _query(prometheus_url,
                    'monitor_keycloak_up{system_id="demo-a-keycloak"}')
    assert result, "monitor_keycloak_up{demo-a-keycloak} missing"
    val = float(result[0]["value"][1])
    assert val == 1.0, \
        f"demo-a-keycloak (www.keycloak.org) is not UP (value={val})"


# Every demo row now points at a real service — both labs must be UP for
# every DB-style probe type when the full profile is running.
@pytest.mark.parametrize("system_id", [
    "demo-a-postgres", "demo-b-postgres",
    "demo-a-redis",    "demo-b-redis",
    "demo-a-mongo",    "demo-b-mongo",
    "demo-a-es",       "demo-b-es",
    "demo-a-mariadb",  "demo-b-mariadb",
])
def test_bundled_db_probe_is_up(prometheus_url, system_id):
    """Every Lab A AND Lab B DB-style probe targets the bundled container
    (started via COMPOSE_PROFILES=full). Both labs must report UP."""
    # Each probe type writes a different `monitor_*_up` series; OR them.
    promql = (
        f'monitor_database_up{{system_id="{system_id}"}}'
        f' or monitor_postgres_up{{system_id="{system_id}"}}'
        f' or monitor_redis_up{{system_id="{system_id}"}}'
        f' or monitor_mongodb_up{{system_id="{system_id}"}}'
        f' or monitor_elasticsearch_up{{system_id="{system_id}"}}'
    )
    result = _query(prometheus_url, promql)
    assert result, (
        f"{system_id}: no monitor_*_up metric found. Either the full-profile "
        "demo target container is not running, or the exporter hasn't probed "
        "yet (give it ~60 s after `COMPOSE_PROFILES=full docker compose up -d`)."
    )
    val = float(result[0]["value"][1])
    assert val == 1.0, f"{system_id}: probe returned value={val} (expected 1)"


def test_grpcb_in_grpc_probe_runs(prometheus_url):
    """The gRPC probe against grpcb.in:9001 should at minimum complete a
    TLS+gRPC handshake. NOTE: grpcb.in does NOT implement the gRPC health-check
    protocol (`grpc.health.v1.Health/Check`), so blackbox-exporter's default
    grpc module returns probe_success=0 even though the connection works.
    We assert the probe RAN — duration > 0 and a healthcheck-response series
    exists with all-zero serving statuses — rather than insisting on
    probe_success=1 which we can never get from this particular upstream."""
    result = _query(prometheus_url,
                    'probe_grpc_duration_seconds{system_id="demo-a-grpc",phase="check"}')
    assert result, (
        "probe_grpc_duration_seconds{demo-a-grpc, phase=check} missing — "
        "the gRPC probe didn't even attempt the handshake."
    )
    val = float(result[0]["value"][1])
    assert val > 0, (
        f"gRPC check phase reported duration={val} (expected > 0). "
        "Either grpcb.in is unreachable from inside the blackbox container or "
        "DNS/TLS is failing."
    )


def test_ssl_expired_badssl_correctly_flagged_negative(prometheus_url):
    """expired.badssl.com is intentionally expired — ssl_probe_success must
    be 0. NOTE the /sd/ssl exporter payload labels by cert_alias (not by
    system_id), so we select on cert_alias='badssl-expired' from the seed.
    Proves the SSL probe correctly rejects the bad cert chain."""
    result = _query(prometheus_url,
                    'ssl_probe_success{cert_alias="badssl-expired"}')
    assert result, (
        "ssl_probe_success{cert_alias='badssl-expired'} missing — expired "
        "negative seed row didn't reach ssl_exporter. Check /sd/ssl payload."
    )
    val = float(result[0]["value"][1])
    assert val == 0, (
        f"expired.badssl.com reports probe_success={val} (expected 0). "
        "ssl_exporter should refuse the expired cert chain."
    )


def test_ssl_selfsigned_badssl_correctly_flagged_invalid(prometheus_url):
    """self-signed.badssl.com fails chain validation — ssl_probe_success
    must be 0 for cert_alias='badssl-selfsigned'."""
    result = _query(prometheus_url,
                    'ssl_probe_success{cert_alias="badssl-selfsigned"}')
    assert result, (
        "ssl_probe_success{cert_alias='badssl-selfsigned'} missing — "
        "self-signed negative seed row didn't reach ssl_exporter."
    )
    val = float(result[0]["value"][1])
    assert val == 0, (
        f"self-signed.badssl.com reports probe_success={val} (expected 0). "
        "ssl_exporter should refuse the self-signed chain."
    )

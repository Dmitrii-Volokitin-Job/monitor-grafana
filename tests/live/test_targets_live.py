"""
Live per-target connectivity tests — one test per system_id.

Tests always PASS (just report UP/DOWN) unless --assert-up is passed.
This gives a per-target status report in CI output — useful as an ops audit.

Run: pytest tests/live/test_targets_live.py --live -v -s
Fail on DOWN: pytest tests/live/test_targets_live.py --live --assert-up
"""
import sys
import os
import pytest
import requests
import yaml

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))

# Targets were previously read from config/targets/*.yml. After the HTTP-SD
# migration those files were removed; Prometheus discovers targets from the
# exporter's /sd/<type> endpoints, which return the same JSON shape
# ([{"labels": {...}, "targets": [...]}]) — so we point the loader there.
SD_BASE = os.environ.get("MONITOR_SD_BASE", "http://localhost:9119")

pytestmark = pytest.mark.live


def _load(sd_type):
    """Fetch HTTP-SD payload for sd_type (e.g. 'http', 'tcp', 'icmp').
    Returns [] if the SD endpoint is unreachable so test collection still works."""
    try:
        resp = requests.get(f"{SD_BASE}/sd/{sd_type}", timeout=5)
        resp.raise_for_status()
        return resp.json() or []
    except (requests.RequestException, ValueError):
        return []


def _http_params():
    """Build pytest params from /sd/http, one per system_id."""
    params = []
    for entry in _load("http"):
        labels = entry.get("labels", {})
        sid = labels.get("system_id", "unknown")
        params.append(pytest.param(
            entry.get("targets", [""])[0],
            sid,
            labels.get("display_name", sid),
            labels.get("__param_module", "http_2xx"),
            id=sid,
        ))
    return params


def _tcp_params():
    params = []
    for entry in _load("tcp"):
        labels = entry.get("labels", {})
        sid = labels.get("system_id", "unknown")
        params.append(pytest.param(
            entry.get("targets", [""])[0],
            sid,
            labels.get("display_name", sid),
            id=sid,
        ))
    return params


def _icmp_params():
    params = []
    for entry in _load("icmp"):
        labels = entry.get("labels", {})
        nid = labels.get("node_id", "unknown")
        params.append(pytest.param(
            entry.get("targets", [""])[0],
            nid,
            labels.get("node_name", nid),
            id=nid,
        ))
    return params


def _probe_via_blackbox(blackbox_url, target, module, timeout=40):
    """Call Blackbox Exporter directly to probe a target. Returns probe_success value."""
    resp = requests.get(
        f"{blackbox_url}/probe",
        params={"target": target, "module": module},
        timeout=timeout,
    )
    assert resp.status_code == 200
    for line in resp.text.splitlines():
        if line.startswith("probe_success "):
            return float(line.split()[-1])
    return None


# ---------------------------------------------------------------------------
# HTTP targets — probe via Blackbox Exporter
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("target_url,system_id,display_name,module", _http_params())
def test_http_target_probe(target_url, system_id, display_name, module,
                           assert_up, request):
    """
    Probes each HTTP target via Blackbox Exporter with the configured module.
    Reports UP/DOWN per target. Fails on DOWN only if --assert-up is passed.
    """
    blackbox_url = "http://localhost:9115"
    probe_success = _probe_via_blackbox(blackbox_url, target_url, module)

    assert probe_success is not None, \
        f"probe_success metric missing in Blackbox response for {system_id}"

    status = "UP" if probe_success == 1.0 else "DOWN"
    print(f"\n  {display_name} ({system_id}): {status}")

    if assert_up:
        assert probe_success == 1.0, \
            f"{display_name} ({system_id}) is DOWN — target: {target_url}, module: {module}"


# ---------------------------------------------------------------------------
# TCP targets — probe via Blackbox Exporter
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("target,system_id,display_name", _tcp_params())
def test_tcp_target_probe(target, system_id, display_name, assert_up):
    """Probes each TCP target (database ports) via Blackbox Exporter."""
    blackbox_url = "http://localhost:9115"
    probe_success = _probe_via_blackbox(blackbox_url, target, "tcp_connect", timeout=20)

    assert probe_success is not None, \
        f"probe_success missing for TCP target {system_id}"

    status = "UP" if probe_success == 1.0 else "DOWN"
    print(f"\n  {display_name} ({system_id}): {status}")

    if assert_up:
        assert probe_success == 1.0, \
            f"TCP target {display_name} ({system_id}) is DOWN — {target}"


# ---------------------------------------------------------------------------
# LDAP targets — call check_ldap() directly
# ---------------------------------------------------------------------------

def _ldap_params():
    with open(os.path.join(PROJECT_ROOT, "monitor_exporter", "config.yml")) as f:
        cfg = yaml.safe_load(f)
    return [
        pytest.param(t, id=t["system_id"])
        for t in cfg.get("ldap_targets", [])
    ]


@pytest.mark.parametrize("target", _ldap_params())
def test_ldap_target_connectivity(target, assert_up):
    """
    Calls check_ldap() directly to verify LDAP server reachability.
    LDAPBindError = UP (auth rejected but server responded).
    """
    from monitor_exporter.exporter import check_ldap
    is_up, resp_ms, error, version = check_ldap(target)

    status = "UP" if is_up else "DOWN"
    print(f"\n  {target['display_name']} ({target['system_id']}): "
          f"{status} ({resp_ms:.0f}ms) version={version}"
          f"{' error=' + error if error else ''}")

    if assert_up:
        assert is_up, \
            f"LDAP {target['display_name']} ({target['system_id']}) is DOWN: {error}"


# ---------------------------------------------------------------------------
# Keycloak targets — call check_keycloak() directly
# ---------------------------------------------------------------------------

def _keycloak_params():
    with open(os.path.join(PROJECT_ROOT, "monitor_exporter", "config.yml")) as f:
        cfg = yaml.safe_load(f)
    return [
        pytest.param(t, id=t["system_id"])
        for t in cfg.get("keycloak_targets", [])
    ]


@pytest.mark.parametrize("target", _keycloak_params())
def test_keycloak_target_connectivity(target, assert_up):
    """
    Calls check_keycloak() directly. Reports UP/DOWN + realm validity.
    realm_valid=False with is_up=True means server is UP but realm is misconfigured.
    """
    from monitor_exporter.exporter import check_keycloak
    is_up, resp_ms, realm_valid, version, error = check_keycloak(target)

    status = "UP" if is_up else "DOWN"
    realm_str = "realm_valid" if realm_valid else "realm_INVALID"
    print(f"\n  {target['display_name']} ({target['system_id']}): "
          f"{status} {realm_str} ({resp_ms:.0f}ms) version={version}"
          f"{' error=' + error if error else ''}")

    if assert_up:
        assert is_up, \
            f"Keycloak {target['display_name']} is DOWN: {error}"


# ---------------------------------------------------------------------------
# Database targets — call extract_mysql_version_from_greeting() directly
# ---------------------------------------------------------------------------

def _db_params():
    with open(os.path.join(PROJECT_ROOT, "monitor_exporter", "config.yml")) as f:
        cfg = yaml.safe_load(f)
    return [
        pytest.param(t, id=t["system_id"])
        for t in cfg.get("database_targets", [])
    ]


@pytest.mark.parametrize("target", _db_params())
def test_database_target_connectivity(target, assert_up):
    """
    Connects to each MariaDB target and reads the server greeting.
    No credentials needed — version is in the handshake packet.
    """
    from monitor_exporter.exporter import extract_mysql_version_from_greeting
    is_up, resp_ms, version, error = extract_mysql_version_from_greeting(
        target["host"], target["port"], target.get("timeout_seconds", 10)
    )

    status = "UP" if is_up else "DOWN"
    print(f"\n  {target['display_name']} ({target['system_id']}): "
          f"{status} ({resp_ms:.0f}ms) version={version}"
          f"{' error=' + error if error else ''}")

    if assert_up:
        assert is_up, \
            f"Database {target['display_name']} is DOWN: {error}"

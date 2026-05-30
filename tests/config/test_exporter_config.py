"""Validate monitor_exporter/config.yml structure."""
import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from monitor_exporter.exporter import VERSION_STRATEGIES


# ---------------------------------------------------------------------------
# Exporter core settings
# ---------------------------------------------------------------------------

def test_exporter_port_is_9116(exporter_config):
    assert exporter_config["exporter"]["port"] == 9116


def test_exporter_check_interval_positive(exporter_config):
    assert exporter_config["exporter"]["check_interval_seconds"] > 0


def test_postgres_required_keys(exporter_config):
    db = exporter_config.get("postgres") or exporter_config.get("mariadb") or {}
    for key in ("host", "port", "database", "user", "password"):
        assert key in db, f"postgres config missing '{key}'"


def test_prometheus_url_configured(exporter_config):
    assert exporter_config.get("prometheus", {}).get("url"), \
        "prometheus.url must be set"


# ---------------------------------------------------------------------------
# LDAP targets
# ---------------------------------------------------------------------------

def test_ldap_targets_not_empty(exporter_config):
    assert exporter_config.get("ldap_targets"), "ldap_targets must not be empty"


def test_ldap_targets_have_required_keys(exporter_config):
    required = {"system_id", "display_name", "system_group", "url", "timeout_seconds"}
    for target in exporter_config.get("ldap_targets", []):
        missing = required - set(target.keys())
        assert not missing, \
            f"LDAP target '{target.get('system_id')}' missing keys: {missing}"


def test_ldap_target_urls_use_ldap_scheme(exporter_config):
    for target in exporter_config.get("ldap_targets", []):
        url = target.get("url", "")
        assert url.startswith("ldap://") or url.startswith("ldaps://"), \
            f"LDAP target '{target.get('system_id')}' URL must start with ldap:// or ldaps://"


# ---------------------------------------------------------------------------
# Keycloak targets
# ---------------------------------------------------------------------------

def test_keycloak_targets_not_empty(exporter_config):
    assert exporter_config.get("keycloak_targets")


def test_keycloak_targets_have_required_keys(exporter_config):
    required = {"system_id", "display_name", "system_group", "base_url", "realm_path"}
    for target in exporter_config.get("keycloak_targets", []):
        missing = required - set(target.keys())
        assert not missing, \
            f"Keycloak target '{target.get('system_id')}' missing keys: {missing}"


# ---------------------------------------------------------------------------
# Database targets
# ---------------------------------------------------------------------------

def test_database_targets_have_host_and_port(exporter_config):
    for target in exporter_config.get("database_targets", []):
        assert "host" in target, f"DB target '{target.get('system_id')}' missing host"
        assert isinstance(target.get("port"), int), \
            f"DB target '{target.get('system_id')}' port must be an integer"


# ---------------------------------------------------------------------------
# Version targets
# ---------------------------------------------------------------------------

def test_version_targets_use_known_strategies(exporter_config):
    known = set(VERSION_STRATEGIES.keys())
    for target in exporter_config.get("version_targets", []):
        strategy = target.get("strategy", "")
        assert strategy in known, \
            f"Version target '{target.get('system_id')}' uses unknown strategy '{strategy}'"


# ---------------------------------------------------------------------------
# System ID uniqueness across all custom target types
# ---------------------------------------------------------------------------

def test_system_ids_unique_across_ldap_keycloak_db(exporter_config):
    ids = []
    for section in ("ldap_targets", "keycloak_targets", "database_targets"):
        ids.extend(t["system_id"] for t in exporter_config.get(section, []))
    dupes = [i for i in ids if ids.count(i) > 1]
    assert not dupes, f"Duplicate system_ids across custom targets: {dupes}"


# ---------------------------------------------------------------------------
# Cross-config consistency: every blackbox_module referenced from the SQL seed
# MUST be declared in config/blackbox.yml. A typo (e.g. `htttp_2xx`) would
# silently make blackbox-exporter return probe_success=0 for that target with
# no clear error.
# ---------------------------------------------------------------------------

import re

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
SEED_FILES = [
    os.path.join(PROJECT_ROOT, "docker", "init-db", "07-seed-systems.sql"),
    os.path.join(PROJECT_ROOT, "docker", "init-db", "09-seed-new-types-and-datasources.sql"),
]


def _seed_module_names() -> set[str]:
    """Pull every non-NULL blackbox_module literal out of the seed INSERTs."""
    names = set()
    for path in SEED_FILES:
        with open(path) as f:
            text = f.read()
        # `,         'http_2xx',    NULL,` shape — capture quoted strings that
        # appear in a position commonly used by the blackbox_module column.
        # Permissive but bounded to alphanumeric + underscore (real module names).
        for m in re.findall(r"'([a-z][a-z0-9_]+)'", text):
            if m in ("http_2xx", "http_2xx_or_401", "http_302", "http_401",
                    "tcp_connect", "icmp_ping", "grpc", "grpc_plain",
                    "dns_udp", "dns_tcp"):
                names.add(m)
    return names


def test_every_seed_blackbox_module_exists_in_blackbox_yml(blackbox_config):
    declared = set((blackbox_config.get("modules") or {}).keys())
    used = _seed_module_names()
    missing = used - declared
    assert not missing, (
        f"Seed references blackbox modules not declared in config/blackbox.yml: "
        f"{sorted(missing)}. Declared modules: {sorted(declared)}"
    )


# ---------------------------------------------------------------------------
# Deploy-path parity: the bundled demo target containers (Postgres / MySQL /
# Redis / Mongo / Elasticsearch) exist in BOTH docker-compose.yml (under
# `profiles: ["full"]`) and the Helm chart's templates/demo-targets.yaml.
# Image versions must stay in lockstep — otherwise the demo behaves
# differently on K8s than under docker-compose for the same seed rows.
# ---------------------------------------------------------------------------

import yaml as _yaml

_DEMO_TARGET_NAMES = {
    "demo-postgres-target", "demo-mysql-target", "demo-redis-target",
    "demo-mongo-target", "demo-es-target",
}


def _compose_demo_target_images() -> dict:
    """{container_name: image} for each `profiles: ["full"]` demo container."""
    with open(os.path.join(PROJECT_ROOT, "docker-compose.yml")) as f:
        compose = _yaml.safe_load(f)
    out = {}
    for svc in (compose.get("services") or {}).values():
        if "full" in (svc.get("profiles") or []):
            name = svc.get("container_name") or svc.get("hostname") or ""
            if name in _DEMO_TARGET_NAMES:
                out[name] = svc["image"]
    return out


def _chart_demo_target_images() -> dict:
    """{container_name: image} parsed out of templates/demo-targets.yaml.
    The file is a multi-doc Helm template with `{{- /* comment */ }}`
    block comments and `{{- if .Values.demoTargets.enabled }}` guards.
    Strip both before yaml.safe_load_all() runs."""
    import re
    path = os.path.join(
        PROJECT_ROOT, "deployments", "k8s-helm", "dev", "monitor-grafana",
        "templates", "demo-targets.yaml",
    )
    with open(path) as f:
        text = f.read()
    # Strip Helm block comments {{- /* ... */ -}} (across multiple lines).
    text = re.sub(r"\{\{-?\s*/\*.*?\*/\s*-?\}\}", "", text, flags=re.DOTALL)
    # Strip any remaining single-line {{ … }} / {{- … }} / {{ … -}} directives.
    text = re.sub(r"\{\{-?.*?-?\}\}", "", text)
    out = {}
    for doc in _yaml.safe_load_all(text):
        if not isinstance(doc, dict) or doc.get("kind") != "Deployment":
            continue
        meta_name = ((doc.get("metadata") or {}).get("name")) or ""
        if meta_name not in _DEMO_TARGET_NAMES:
            continue
        containers = (((doc.get("spec") or {}).get("template") or {})
                      .get("spec") or {}).get("containers") or []
        if containers:
            out[meta_name] = containers[0].get("image", "")
    return out


def test_demo_target_images_match_between_compose_and_chart():
    compose = _compose_demo_target_images()
    chart = _chart_demo_target_images()
    assert set(compose) == _DEMO_TARGET_NAMES, (
        f"docker-compose missing some `profiles: ['full']` demo target containers. "
        f"Found: {sorted(compose)}; expected: {sorted(_DEMO_TARGET_NAMES)}"
    )
    assert set(chart) == _DEMO_TARGET_NAMES, (
        f"Helm demo-targets.yaml missing some Deployments. "
        f"Found: {sorted(chart)}; expected: {sorted(_DEMO_TARGET_NAMES)}"
    )
    mismatches = {n: (compose[n], chart[n]) for n in _DEMO_TARGET_NAMES
                  if compose[n] != chart[n]}
    assert not mismatches, (
        "Bundled demo target image version drift between docker-compose and "
        f"Helm chart: {mismatches}. Bumping one without the other makes the "
        "demo behave differently on K8s than on docker-compose for the same "
        "seed rows. Mirror the bump into both files."
    )

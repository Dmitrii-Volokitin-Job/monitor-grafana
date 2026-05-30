"""Load all config YAML files as session-scoped fixtures."""
import os
import pytest
import yaml

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))


def _load(path):
    with open(path, "r") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def prometheus_config():
    return _load(os.path.join(PROJECT_ROOT, "config", "prometheus.yml"))


@pytest.fixture(scope="session")
def blackbox_config():
    return _load(os.path.join(PROJECT_ROOT, "config", "blackbox.yml"))


@pytest.fixture(scope="session")
def exporter_config():
    return _load(os.path.join(PROJECT_ROOT, "monitor_exporter", "config.yml"))


@pytest.fixture(scope="session")
def health_check_rules():
    return _load(os.path.join(PROJECT_ROOT, "config", "alert_rules", "health_check_rules.yml"))


@pytest.fixture(scope="session")
def ssl_rules():
    return _load(os.path.join(PROJECT_ROOT, "config", "alert_rules", "ssl_rules.yml"))


@pytest.fixture(scope="session")
def alerting_config():
    return _load(os.path.join(
        PROJECT_ROOT, "config", "provisioning", "alerting", "alerting.yml"))


# Target lists previously loaded from `config/targets/*.yml` were removed
# along with the directory itself (see CLAUDE.md — targets now live in the
# `monitored_system` Postgres table). Tests that need the live target catalog
# should hit `/sd/<type>` on the exporter instead.

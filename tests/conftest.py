"""Root conftest: CLI flags, pytest marks, shared session fixtures."""
import os
import sys
import pytest

# Make the exporter importable without installing.
# Both the project root (for `import monitor_exporter.exporter`) and the
# package directory (so the bare `from admin_ui import …` / `from db import …`
# inside exporter.py resolve) must be on sys.path.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "monitor_exporter"))


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", default=False,
                     help="Run live connectivity tests against real infrastructure")
    parser.addoption("--assert-up", action="store_true", default=False,
                     help="Fail live target tests when probe_success=0")
    parser.addoption("--exporter-url", default="http://localhost:9116")
    parser.addoption("--prometheus-url", default="http://localhost:9091")
    parser.addoption("--grafana-url", default="http://localhost:3030")
    parser.addoption("--grafana-user", default="admin")
    parser.addoption("--grafana-password", default="admin")
    parser.addoption("--postgres-host", default="localhost")
    parser.addoption("--postgres-port", type=int, default=5433)


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--live"):
        skip_live = pytest.mark.skip(reason="Pass --live to run against real infrastructure")
        for item in items:
            if "live" in item.keywords:
                item.add_marker(skip_live)


@pytest.fixture(scope="session")
def project_root():
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def exporter_url(request):
    return request.config.getoption("--exporter-url")


@pytest.fixture(scope="session")
def prometheus_url(request):
    return request.config.getoption("--prometheus-url")


@pytest.fixture(scope="session")
def grafana_url(request):
    return request.config.getoption("--grafana-url")


@pytest.fixture(scope="session")
def grafana_auth(request):
    return (request.config.getoption("--grafana-user"),
            request.config.getoption("--grafana-password"))


@pytest.fixture(scope="session")
def assert_up(request):
    return request.config.getoption("--assert-up")

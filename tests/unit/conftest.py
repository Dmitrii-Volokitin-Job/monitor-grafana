"""Unit-level fixtures: mock factories and minimal config."""
import pytest
from unittest.mock import MagicMock


@pytest.fixture
def minimal_config():
    return {
        "exporter": {"port": 9116, "check_interval_seconds": 300},
        "mariadb": {
            "enabled": True, "host": "localhost", "port": 3306,
            "database": "monitoring", "user": "root", "password": "x",
            "retention_days": 90, "cleanup_interval_hours": 24,
        },
        "prometheus": {"url": "http://localhost:9090"},
        "blackbox_target_files": {},
        "ldap_targets": [
            {"system_id": "test-ldap", "display_name": "Test LDAP",
             "system_group": "TEST", "url": "ldaps://ldap.example.com:636",
             "timeout_seconds": 5}
        ],
        "keycloak_targets": [
            {"system_id": "test-kc", "display_name": "Test Keycloak",
             "system_group": "TEST", "base_url": "https://kc.example.com",
             "realm_path": "/auth/realms/master", "timeout_seconds": 5}
        ],
        "database_targets": [
            {"system_id": "test-db", "display_name": "Test DB",
             "system_group": "TEST", "host": "db.example.com",
             "port": 3306, "timeout_seconds": 5}
        ],
        "version_targets": [
            {"system_id": "test-spring", "display_name": "Test Spring",
             "system_group": "TEST",
             "url": "https://app.example.com/management/info",
             "strategy": "spring_actuator", "timeout_seconds": 5}
        ],
    }


@pytest.fixture
def mock_response():
    """Factory: returns a callable that builds mock requests.Response objects."""
    import requests as req

    def _make(status_code=200, json_data=None, headers=None, raise_exc=None):
        resp = MagicMock(spec=req.Response)
        resp.status_code = status_code
        resp.headers = headers or {}
        if raise_exc:
            resp.json.side_effect = raise_exc
        else:
            resp.json.return_value = json_data or {}
        return resp

    return _make

"""
Monitor Monitor Exporter for Prometheus

Handles three types of checks that Blackbox Exporter cannot do natively:

1. LDAP Connectivity
   - Anonymous bind to each LDAP target
   - LDAPBindError (auth rejected but server responded) = UP
   - Connection failure = DOWN
   - Replicates HealthCheckServiceImpl.performLdapCheck()

2. Keycloak Health Check
   - GET /auth/realms/master (public, no auth) — checks realm availability
   - Parses JSON response for realm name validation
   - Extracts Keycloak version from response headers (X-Keycloak-Version)
     or from /auth/.well-known/openid-configuration

3. System Version Detection
   - Spring Boot Actuator: GET /management/info → build.version
   - Camunda BPM: GET /engine-rest/version → version field
   - OpenAPI: GET /v3/api-docs → info.version
   - Keycloak: extracted from realm endpoint headers

Exposes on port 9116:
  - monitor_ldap_up, monitor_ldap_response_time_ms
  - monitor_keycloak_up, monitor_keycloak_response_time_ms, monitor_keycloak_realm_valid
  - monitor_database_up, monitor_database_response_time_ms
  - monitor_check_result_info (status + error details per check)
  - monitor_system_version_info (info metric with version label)
"""

import json
import logging
import os
import re
import socket
import ssl
import struct
import time
import threading
from urllib.parse import urlparse

try:
    import db as _db
except ImportError:
    from monitor_exporter import db as _db
import requests
import urllib3
import yaml
from ldap3 import Server, Connection, Tls, ANONYMOUS, ALL
from ldap3.core.exceptions import (
    LDAPBindError,
    LDAPSocketOpenError,
    LDAPSocketReceiveError,
    LDAPSessionTerminatedByServerError,
    LDAPException,
)
from prometheus_client import Gauge, Info, start_http_server
from admin_ui import start_admin_ui
from datasource_sync import start_datasource_sync

# Suppress InsecureRequestWarning for self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("monitor_exporter")

# ============================================================================
# Prometheus Metrics
# ============================================================================

# LDAP metrics
LDAP_UP = Gauge(
    "monitor_ldap_up",
    "Whether the LDAP server is reachable (1=UP, 0=DOWN)",
    ["system_id", "display_name", "system_group", "system_type"],
)
LDAP_RESPONSE_TIME = Gauge(
    "monitor_ldap_response_time_ms",
    "LDAP connection response time in milliseconds",
    ["system_id", "display_name", "system_group", "system_type"],
)

# Keycloak metrics
KEYCLOAK_UP = Gauge(
    "monitor_keycloak_up",
    "Whether the Keycloak server is reachable (1=UP, 0=DOWN)",
    ["system_id", "display_name", "system_group", "system_type"],
)
KEYCLOAK_RESPONSE_TIME = Gauge(
    "monitor_keycloak_response_time_ms",
    "Keycloak health check response time in milliseconds",
    ["system_id", "display_name", "system_group", "system_type"],
)
KEYCLOAK_REALM_VALID = Gauge(
    "monitor_keycloak_realm_valid",
    "Whether the Keycloak realm response is valid JSON with expected fields (1=valid, 0=invalid)",
    ["system_id", "display_name", "system_group", "system_type"],
)

# System version info metric (labels carry the version string)
SYSTEM_VERSION = Info(
    "monitor_system_version",
    "Version information for monitored systems",
    ["system_id", "display_name", "system_group"],
)

# Database metrics
DB_UP = Gauge(
    "monitor_database_up",
    "Whether the database server is reachable (1=UP, 0=DOWN)",
    ["system_id", "display_name", "system_group", "system_type"],
)
DB_RESPONSE_TIME = Gauge(
    "monitor_database_response_time_ms",
    "Database connection response time in milliseconds",
    ["system_id", "display_name", "system_group", "system_type"],
)

# Check result info metric (carries status + error as labels)
CHECK_RESULT = Gauge(
    "monitor_check_result_info",
    "Last check result with error details",
    ["system_id", "display_name", "system_group", "check_type", "status", "error"],
)

# Exporter metadata
EXPORTER_INFO = Info(
    "monitor_exporter",
    "Monitor Monitor Exporter metadata",
)


def load_config(config_path: str) -> dict:
    """Load configuration from YAML file."""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ============================================================================
# Postgres Health Check Logger
# ============================================================================

class HealthCheckLogger:
    """Writes check results to Postgres for the Grafana Health Check Logs panel."""

    def __init__(self, db_config: dict):
        self.host = db_config.get("host", "localhost")
        self.port = db_config.get("port", 5432)
        self.database = db_config.get("database", "monitoring")
        self.user = db_config.get("user", "monitoring")
        # No password default — must be supplied via POSTGRES_PASSWORD env var
        # or db_config. Empty string lets psycopg fail fast with a clear auth
        # error rather than silently succeeding against a misconfigured DB.
        self.password = db_config.get("password", "")
        self.retention_days = db_config.get("retention_days", 90)
        self._system_id_cache: dict[str, int] = {}
        self._last_cleanup = 0.0
        self._cleanup_interval = db_config.get("cleanup_interval_hours", 24) * 3600

    def _connect(self):
        return _db.connect({
            "host": self.host, "port": self.port, "database": self.database,
            "user": self.user, "password": self.password,
        })

    def _get_system_pk(self, conn, system_id: str) -> int | None:
        """Get the auto-increment PK for a system_id, with caching."""
        if system_id in self._system_id_cache:
            return self._system_id_cache[system_id]
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM monitored_system WHERE system_id = %s", (system_id,))
            row = cur.fetchone()
            if row:
                pk = row["id"]
                self._system_id_cache[system_id] = pk
                return pk
        return None

    def log_check(self, system_id: str, is_up: bool, response_time_ms: float,
                  error: str = "", http_status_code: int | None = None):
        """Write a single check result row to health_check_history."""
        try:
            conn = self._connect()
            pk = self._get_system_pk(conn, system_id)
            if pk is None:
                conn.close()
                return
            status = "UP" if is_up else "DOWN"
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO health_check_history "
                    "(system_id, check_timestamp, status, http_status_code, response_time_ms, error_message) "
                    "VALUES (%s, NOW(), %s, %s, %s, %s)",
                    (pk, status, http_status_code, max(1, round(response_time_ms)), error[:500] if error else None),
                )
            conn.close()
        except Exception:
            logger.debug("Failed to log check result for %s", system_id, exc_info=True)

    def log_check_batch(self, results: list[tuple]):
        """Insert multiple check results in one connection.

        Each tuple: (system_id_str, is_up, response_time_ms, error, http_status_code)
        """
        if not results:
            return
        try:
            conn = self._connect()
            rows = []
            for system_id, is_up, response_time_ms, error, http_status_code in results:
                pk = self._get_system_pk(conn, system_id)
                if pk is None:
                    continue
                status = "UP" if is_up else "DOWN"
                rows.append((pk, status, http_status_code,
                             max(1, round(response_time_ms)), error[:500] if error else None))
            if rows:
                with conn.cursor() as cur:
                    cur.executemany(
                        "INSERT INTO health_check_history "
                        "(system_id, check_timestamp, status, http_status_code, response_time_ms, error_message) "
                        "VALUES (%s, NOW(), %s, %s, %s, %s)",
                        rows,
                    )
            conn.close()
            logger.debug("Batch-logged %d blackbox check results", len(rows))
        except Exception:
            logger.debug("Failed to batch-log check results", exc_info=True)

    def run_cleanup(self):
        """Delete entries older than retention_days. Runs at most once per cleanup_interval."""
        now = time.time()
        if now - self._last_cleanup < self._cleanup_interval:
            return
        self._last_cleanup = now
        try:
            conn = self._connect()
            with conn.cursor() as cur:
                # Postgres requires the unit to live inside the interval literal;
                # `INTERVAL '%s days'` does NOT parameterize cleanly via psycopg
                # (the quotes around %s become part of the SQL string), so we
                # cast a placeholder integer to an interval instead.
                cur.execute(
                    "DELETE FROM health_check_history "
                    "WHERE check_timestamp < NOW() - (%s || ' days')::interval",
                    (self.retention_days,),
                )
                deleted = cur.rowcount
            conn.close()
            if deleted > 0:
                logger.info("Retention cleanup: deleted %d rows older than %d days", deleted, self.retention_days)
        except Exception:
            logger.warning("Retention cleanup failed", exc_info=True)


# Global instance, set in main() if Postgres is enabled
_db_logger: HealthCheckLogger | None = None


# ============================================================================
# Check Result Tracking
# ============================================================================

_previous_check_labels: dict[tuple[str, str], tuple[str, ...]] = {}


def _set_check_result(system_id, display_name, system_group, check_type, is_up, error,
                      response_time_ms=0.0, http_status_code=None):
    """Record check result as a Prometheus info metric and log to Postgres."""
    status = "UP" if is_up else "DOWN"
    safe_error = error[:200].replace("\n", " ") if error else ""
    # Write to Postgres
    if _db_logger is not None:
        _db_logger.log_check(system_id, is_up, response_time_ms, safe_error, http_status_code)
    key = (system_id, check_type)
    new_labels = (system_id, display_name, system_group, check_type, status, safe_error)
    old_labels = _previous_check_labels.get(key)
    if old_labels and old_labels != new_labels:
        try:
            CHECK_RESULT.remove(*old_labels)
        except KeyError:
            pass
    CHECK_RESULT.labels(*new_labels).set(1)
    _previous_check_labels[key] = new_labels


# ============================================================================
# LDAP Checks
# ============================================================================

def parse_ldap_url(url: str) -> tuple[str, int, bool]:
    parsed = urlparse(url)
    use_ssl = parsed.scheme == "ldaps"
    host = parsed.hostname
    port = parsed.port or (636 if use_ssl else 389)
    return host, port, use_ssl


def extract_ldap_version(server) -> str:
    """Extract version information from LDAP server root DSE."""
    try:
        if server.info:
            # Try vendorVersion first (most specific)
            vendor_version = getattr(server.info, 'vendor_version', None)
            if vendor_version:
                return str(vendor_version[0]) if isinstance(vendor_version, list) else str(vendor_version)
            # Try vendorName
            vendor_name = getattr(server.info, 'vendor_name', None)
            if vendor_name:
                return str(vendor_name[0]) if isinstance(vendor_name, list) else str(vendor_name)
            # Try supportedLDAPVersion
            ldap_versions = getattr(server.info, 'supported_ldap_version', None)
            if ldap_versions:
                versions = ldap_versions if isinstance(ldap_versions, list) else [ldap_versions]
                return f"LDAPv{max(int(v) for v in versions)}"
            # Try raw DSE attributes
            if hasattr(server.info, 'raw') and server.info.raw:
                for attr in ['vendorVersion', 'vendorName', 'isGlobalCatalogReady']:
                    val = server.info.raw.get(attr)
                    if val:
                        return val[0].decode() if isinstance(val[0], bytes) else str(val[0])
    except Exception as e:
        logger.debug("Failed to extract LDAP version: %s", e)
    return "unknown"


def check_ldap(target: dict) -> tuple[bool, float, str, str]:
    """
    Perform LDAP connectivity check using anonymous bind.
    Mirrors HealthCheckServiceImpl.performLdapCheck().
    Returns: (is_up, response_time_ms, error_msg, version)
    """
    url = target["url"]
    timeout = target.get("timeout_seconds", 30)
    host, port, use_ssl = parse_ldap_url(url)

    start_time = time.time()
    try:
        tls_config = None
        if use_ssl:
            tls_config = Tls(validate=ssl.CERT_NONE)

        server = Server(
            host, port=port, use_ssl=use_ssl, tls=tls_config,
            get_info=ALL, connect_timeout=timeout,
        )
        conn = Connection(
            server, authentication=ANONYMOUS,
            read_only=True, receive_timeout=timeout,
        )

        result = conn.bind()
        elapsed_ms = (time.time() - start_time) * 1000
        version = extract_ldap_version(server)
        conn.unbind()
        # Successful bind or failed auth = server is reachable = UP
        return True, elapsed_ms, "", version

    except LDAPBindError:
        # Auth rejected but server responded = UP
        elapsed_ms = (time.time() - start_time) * 1000
        version = extract_ldap_version(server)
        return True, elapsed_ms, "", version

    except (LDAPSocketOpenError, LDAPSocketReceiveError,
            LDAPSessionTerminatedByServerError) as e:
        elapsed_ms = (time.time() - start_time) * 1000
        return False, elapsed_ms, str(e)[:2000], "unknown"

    except (LDAPException, Exception) as e:
        elapsed_ms = (time.time() - start_time) * 1000
        return False, elapsed_ms, str(e)[:2000], "unknown"


def run_ldap_checks(targets: list[dict]):
    for target in targets:
        sid = target["system_id"]
        labels = [sid, target["display_name"], target["system_group"], "LDAP"]

        logger.info("LDAP check: %s (%s)", sid, target["url"])
        is_up, resp_time, error, version = check_ldap(target)

        LDAP_UP.labels(*labels).set(1 if is_up else 0)
        LDAP_RESPONSE_TIME.labels(*labels).set(resp_time)
        _set_check_result(sid, target["display_name"], target["system_group"], "ldap", is_up, error,
                          response_time_ms=resp_time)

        # Set LDAP version as info metric
        if version and version != "unknown":
            SYSTEM_VERSION.labels(*labels[:3]).info({"version": version, "type": "ldap"})

        status = "UP" if is_up else "DOWN"
        logger.info("  %s: %s (%.1fms) version=%s%s", sid, status, resp_time, version,
                     f" error={error}" if error else "")


# ============================================================================
# Keycloak Health Checks
# ============================================================================

def _extract_keycloak_version(resp) -> str:
    """Return the best-effort Keycloak version from the response, or 'unknown'.

    Tries in order:
      1. `X-Keycloak-Version` response header (older Keycloak versions only).
      2. `Server: Keycloak/<ver>` response header.

    Both are no-ops on Keycloak 20+; version detection then falls back to
    the openid-configuration well-known doc (handled elsewhere).
    """
    if v := resp.headers.get("X-Keycloak-Version"):
        return v
    if m := re.search(r"Keycloak[/ ]([\d.]+)",
                     resp.headers.get("Server", ""), re.IGNORECASE):
        return m.group(1)
    return "unknown"


def check_keycloak(target: dict) -> tuple[bool, float, bool, str, str]:
    """Check Keycloak health via the public realm endpoint.

    Returns: (is_up, response_time_ms, realm_valid, version, error_msg).
    """
    base_url = target["base_url"]
    realm_path = target.get("realm_path", "/auth/realms/master")
    timeout = target.get("timeout_seconds", 30)
    url = f"{base_url}{realm_path}"

    start_time = time.time()
    try:
        resp = requests.get(
            url, timeout=timeout, verify=False,
            headers={"User-Agent": "Monitor-Monitor/2.0-Grafana"},
        )
    except requests.exceptions.Timeout:
        return False, (time.time() - start_time) * 1000, False, "unknown", "Connection timed out"
    except Exception as e:
        return False, (time.time() - start_time) * 1000, False, "unknown", str(e)[:500]

    elapsed_ms = (time.time() - start_time) * 1000
    version = _extract_keycloak_version(resp)

    if resp.status_code != 200:
        return False, elapsed_ms, False, version, f"HTTP {resp.status_code}"
    try:
        data = resp.json()
    except (json.JSONDecodeError, ValueError):
        return True, elapsed_ms, False, version, "Invalid JSON response"
    expected_realm = realm_path.rstrip("/").split("/")[-1]
    return True, elapsed_ms, data.get("realm") == expected_realm, version, ""


def try_keycloak_version_from_wellknown(target: dict) -> str:
    """
    Fallback: try to extract Keycloak version from the well-known OpenID config.
    Some Keycloak versions expose version in the issuer URL or other fields.
    """
    base_url = target["base_url"]
    timeout = target.get("timeout_seconds", 10)
    url = f"{base_url}/auth/realms/master/.well-known/openid-configuration"

    try:
        resp = requests.get(url, timeout=timeout, verify=False,
                           headers={"User-Agent": "Monitor-Monitor/2.0-Grafana"})
        if resp.status_code == 200:
            data = resp.json()
            # The "issuer" field usually just has the realm URL, not the version.
            # But we check authorization_endpoint and token_endpoint for version patterns
            for field in ["issuer", "authorization_endpoint", "token_endpoint"]:
                val = data.get(field, "")
                match = re.search(r"auth/(v[\d.]+)/", val)
                if match:
                    return match.group(1)
    except Exception:
        pass
    return "unknown"


def run_keycloak_checks(targets: list[dict]):
    for target in targets:
        sid = target["system_id"]
        labels = [sid, target["display_name"], target["system_group"], "KEYCLOAK"]

        logger.info("Keycloak check: %s (%s)", sid, target["base_url"])
        is_up, resp_time, realm_valid, version, error = check_keycloak(target)

        # If version still unknown, try well-known endpoint
        if version == "unknown" and is_up:
            version = try_keycloak_version_from_wellknown(target)

        KEYCLOAK_UP.labels(*labels).set(1 if is_up else 0)
        KEYCLOAK_RESPONSE_TIME.labels(*labels).set(resp_time)
        KEYCLOAK_REALM_VALID.labels(*labels).set(1 if realm_valid else 0)
        _set_check_result(sid, target["display_name"], target["system_group"], "keycloak", is_up, error,
                          response_time_ms=resp_time)

        # Set version as info metric
        if version != "unknown":
            SYSTEM_VERSION.labels(*labels[:3]).info({"version": version, "type": "keycloak"})

        status = "UP" if is_up else "DOWN"
        logger.info("  %s: %s (%.1fms) realm_valid=%s version=%s%s",
                     sid, status, resp_time, realm_valid, version,
                     f" error={error}" if error else "")


# ============================================================================
# System Version Detection
# ============================================================================

def extract_version_spring_actuator(url: str, timeout: int) -> str:
    """
    Extract version from Spring Boot Actuator /info endpoint.
    Response format: {"build": {"version": "1.2.3", "name": "...", ...}}
    """
    try:
        resp = requests.get(url, timeout=timeout, verify=False,
                           headers={"User-Agent": "Monitor-Monitor/2.0-Grafana"})
        if resp.status_code == 200:
            data = resp.json()
            # Try build.version first (standard Spring Boot Actuator)
            build_info = data.get("build", {})
            if isinstance(build_info, dict):
                version = build_info.get("version", "")
                if version:
                    return version
            # Try app.version
            app_info = data.get("app", {})
            if isinstance(app_info, dict):
                version = app_info.get("version", "")
                if version:
                    return version
            # Try top-level version field (custom endpoints like /management/gateway/version)
            version = data.get("version", "")
            if version:
                return version
    except Exception as e:
        logger.debug("Spring actuator version check failed for %s: %s", url, e)
    return "unknown"


def extract_version_camunda(url: str, timeout: int) -> str:
    """
    Extract version from Camunda BPM /engine-rest/version endpoint.
    Response format: {"version": "7.20.0"}
    """
    try:
        resp = requests.get(url, timeout=timeout, verify=False,
                           headers={"User-Agent": "Monitor-Monitor/2.0-Grafana"})
        if resp.status_code == 200:
            data = resp.json()
            return data.get("version", "unknown")
    except Exception as e:
        logger.debug("Camunda version check failed for %s: %s", url, e)
    return "unknown"


def extract_version_openapi(url: str, timeout: int) -> str:
    """
    Extract version from OpenAPI /v3/api-docs endpoint.
    Response format: {"openapi": "3.0.1", "info": {"title": "...", "version": "1.2.3"}}
    """
    try:
        resp = requests.get(url, timeout=timeout, verify=False,
                           headers={"User-Agent": "Monitor-Monitor/2.0-Grafana"})
        if resp.status_code == 200:
            data = resp.json()
            info = data.get("info", {})
            if isinstance(info, dict):
                return info.get("version", "unknown")
    except Exception as e:
        logger.debug("OpenAPI version check failed for %s: %s", url, e)
    return "unknown"


def extract_version_gateway(url: str, timeout: int) -> str:
    """
    Extract version from Monitor API Gateway /gateway/version endpoint.
    Response format: {"apiVersion": "V1", "serverVersion": "2.3.3"}
    """
    try:
        resp = requests.get(url, timeout=timeout, verify=False,
                           headers={"User-Agent": "Monitor-Monitor/2.0-Grafana"})
        if resp.status_code == 200:
            data = resp.json()
            version = data.get("serverVersion", "")
            if version:
                return version
            # Fallback to version field
            version = data.get("version", "")
            if version:
                return version
    except Exception as e:
        logger.debug("Gateway version check failed for %s: %s", url, e)
    return "unknown"


def extract_version_kubernetes(url: str, timeout: int) -> str:
    """
    Extract version from Kubernetes API /version endpoint.
    Response format: {"major": "1", "minor": "28", "gitVersion": "v1.28.2+k3s1", ...}
    """
    try:
        resp = requests.get(url, timeout=timeout, verify=False,
                           headers={"User-Agent": "Monitor-Monitor/2.0-Grafana"})
        if resp.status_code == 200:
            data = resp.json()
            git_version = data.get("gitVersion", "")
            if git_version:
                return git_version
            # Fallback to major.minor
            major = data.get("major", "")
            minor = data.get("minor", "")
            if major and minor:
                return f"v{major}.{minor}"
    except Exception as e:
        logger.debug("Kubernetes version check failed for %s: %s", url, e)
    return "unknown"


def extract_version_generic_json(url: str, timeout: int) -> str:
    """
    Extract version from Monitor API /api/v1/versions/current endpoint.
    Response format: {"versionNumber": "1.2.0", "versionName": "...", "isCurrent": true, ...}
    """
    try:
        resp = requests.get(url, timeout=timeout, verify=False,
                           headers={"User-Agent": "Monitor-Monitor/2.0-Grafana"})
        if resp.status_code == 200:
            data = resp.json()
            version = data.get("versionNumber", "")
            if version:
                return version
    except Exception as e:
        logger.debug("Monitor version check failed for %s: %s", url, e)
    return "unknown"


VERSION_STRATEGIES = {
    "spring_actuator": extract_version_spring_actuator,
    "camunda": extract_version_camunda,
    "openapi": extract_version_openapi,
    "gateway_version": extract_version_gateway,
    "kubernetes": extract_version_kubernetes,
    "monitor_version": extract_version_generic_json,
    "json_version": extract_version_camunda,  # generic {"version": "..."} format
}


def run_version_checks(targets: list[dict]):
    for target in targets:
        sid = target["system_id"]
        labels = [sid, target["display_name"], target["system_group"]]
        strategy = target.get("strategy", "spring_actuator")
        url = target["url"]
        timeout = target.get("timeout_seconds", 10)

        logger.info("Version check: %s (%s, strategy=%s)", sid, url, strategy)

        extractor = VERSION_STRATEGIES.get(strategy)
        if not extractor:
            logger.warning("  Unknown strategy: %s", strategy)
            continue

        version = extractor(url, timeout)
        if version and version != "unknown":
            SYSTEM_VERSION.labels(*labels).info({"version": version, "type": strategy})
            logger.info("  %s: version=%s", sid, version)
        else:
            logger.info("  %s: version not available", sid)


# ============================================================================
# Database Version Detection (MariaDB/MySQL)
# ============================================================================

def extract_mysql_version_from_greeting(host: str, port: int, timeout: int) -> tuple[bool, float, str, str]:
    """
    Connect to MySQL/MariaDB and read the server greeting packet.
    The greeting packet contains the server version as a null-terminated string
    starting at byte 5, no authentication required.

    Returns: (is_up, response_time_ms, version, error)
    """
    start_time = time.time()
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        elapsed_ms = (time.time() - start_time) * 1000

        # Read the greeting packet (at least 128 bytes is enough)
        data = sock.recv(256)
        sock.close()

        if len(data) < 5:
            return True, elapsed_ms, "unknown", ""

        # MySQL protocol: first 4 bytes = packet length + sequence id
        # byte 5 = protocol version (0x0a for MySQL 3.21.0+)
        # Then comes the null-terminated server version string
        version_start = 4 + 1  # skip packet header (3 bytes length + 1 byte seq) + protocol version
        version_end = data.index(b'\x00', version_start)
        version = data[version_start:version_end].decode('utf-8', errors='replace')

        return True, elapsed_ms, version, ""

    except socket.timeout:
        elapsed_ms = (time.time() - start_time) * 1000
        return False, elapsed_ms, "unknown", "Connection timed out"

    except (ConnectionRefusedError, OSError) as e:
        elapsed_ms = (time.time() - start_time) * 1000
        logger.debug("Database connection failed for %s:%d: %s", host, port, e)
        return False, elapsed_ms, "unknown", str(e)[:500]

    except Exception as e:
        elapsed_ms = (time.time() - start_time) * 1000
        logger.debug("Database version check failed for %s:%d: %s", host, port, e)
        return False, elapsed_ms, "unknown", str(e)[:500]


def run_database_checks(targets: list[dict]):
    for target in targets:
        sid = target["system_id"]
        labels = [sid, target["display_name"], target["system_group"], "DATABASE"]
        host = target["host"]
        port = target.get("port", 3306)
        timeout = target.get("timeout_seconds", 10)

        logger.info("Database check: %s (%s:%d)", sid, host, port)
        is_up, resp_time, version, error = extract_mysql_version_from_greeting(host, port, timeout)

        DB_UP.labels(*labels).set(1 if is_up else 0)
        DB_RESPONSE_TIME.labels(*labels).set(resp_time)
        _set_check_result(sid, target["display_name"], target["system_group"], "database", is_up, error,
                          response_time_ms=resp_time)

        if version and version != "unknown":
            SYSTEM_VERSION.labels(*labels[:3]).info({"version": version, "type": "database"})

        status = "UP" if is_up else "DOWN"
        logger.info("  %s: %s (%.1fms) version=%s%s", sid, status, resp_time, version,
                     f" error={error}" if error else "")


# ============================================================================
# Postgres / Redis / MongoDB / Elasticsearch protocol checks
# ============================================================================
#
# Each function returns: (is_up, response_time_ms, error_msg)
# and reports the result through the same DB_UP / DB_RESPONSE_TIME gauges
# (the labels carry system_type so dashboards can split them).

def check_postgres(host: str, port: int, timeout: int) -> tuple[bool, float, str]:
    """Speak the Postgres startup protocol just far enough to know the server
    is responsive. Sends a StartupMessage for a bogus user; any reply (auth
    request, error) means the server is alive. No psycopg2 dep.
    """
    start_time = time.time()
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        # StartupMessage:
        #   int32 length, int32 protocol=196608, "user\0probe\0\0"
        body = b"user\x00probe\x00\x00"
        length = 4 + 4 + len(body)
        msg = struct.pack("!II", length, 196608) + body
        sock.sendall(msg)
        reply = sock.recv(1)
        sock.close()
        elapsed_ms = (time.time() - start_time) * 1000
        if not reply:
            return False, elapsed_ms, "Empty response"
        # 'R' = AuthRequest, 'E' = ErrorResponse, 'N' = NoticeResponse — all mean server is up
        if reply[:1] in (b'R', b'E', b'N'):
            return True, elapsed_ms, ""
        return False, elapsed_ms, f"Unexpected reply byte 0x{reply.hex()}"
    except socket.timeout:
        return False, (time.time() - start_time) * 1000, "Connection timed out"
    except (ConnectionRefusedError, OSError) as e:
        return False, (time.time() - start_time) * 1000, str(e)[:500]
    except Exception as e:
        return False, (time.time() - start_time) * 1000, str(e)[:500]


def check_redis(host: str, port: int, timeout: int) -> tuple[bool, float, str]:
    """Send `PING\\r\\n` (inline command) and expect `+PONG\\r\\n`."""
    start_time = time.time()
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.sendall(b"PING\r\n")
        reply = sock.recv(64)
        sock.close()
        elapsed_ms = (time.time() - start_time) * 1000
        if reply.startswith(b"+PONG"):
            return True, elapsed_ms, ""
        # NOAUTH errors are still proof the server is up.
        if reply.startswith(b"-NOAUTH"):
            return True, elapsed_ms, ""
        return False, elapsed_ms, f"Unexpected reply: {reply[:64]!r}"
    except socket.timeout:
        return False, (time.time() - start_time) * 1000, "Connection timed out"
    except (ConnectionRefusedError, OSError) as e:
        return False, (time.time() - start_time) * 1000, str(e)[:500]
    except Exception as e:
        return False, (time.time() - start_time) * 1000, str(e)[:500]


def check_mongodb(host: str, port: int, timeout: int) -> tuple[bool, float, str]:
    """Minimal TCP probe — the wire protocol handshake costs more than it's
    worth here; a successful TCP connection to the configured port is the same
    signal pymongo would use to mark the server reachable."""
    start_time = time.time()
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True, (time.time() - start_time) * 1000, ""
    except socket.timeout:
        return False, (time.time() - start_time) * 1000, "Connection timed out"
    except (ConnectionRefusedError, OSError) as e:
        return False, (time.time() - start_time) * 1000, str(e)[:500]
    except Exception as e:
        return False, (time.time() - start_time) * 1000, str(e)[:500]


def check_elasticsearch(url: str, timeout: int) -> tuple[bool, float, str, str]:
    """GET <url>/_cluster/health — extract `status` (green/yellow/red) and `cluster_name`."""
    start_time = time.time()
    health_url = url.rstrip("/") + "/_cluster/health"
    try:
        resp = requests.get(health_url, timeout=timeout, verify=False,
                            headers={"User-Agent": "monitor/2.2"})
        elapsed_ms = (time.time() - start_time) * 1000
        if resp.status_code != 200:
            return False, elapsed_ms, "unknown", f"HTTP {resp.status_code}"
        data = resp.json()
        status = data.get("status", "unknown")
        # Green/yellow = up; red = the cluster has unassigned primaries (still up but unhealthy)
        return status in ("green", "yellow", "red"), elapsed_ms, status, ""
    except requests.exceptions.RequestException as e:
        return False, (time.time() - start_time) * 1000, "unknown", str(e)[:500]


def run_postgres_checks(targets: list[dict]):
    for t in targets:
        sid = t["system_id"]
        labels = [sid, t["display_name"], t["system_group"], "POSTGRES"]
        host, port = t["host"], int(t.get("port", 5432))
        is_up, ms, err = check_postgres(host, port, t.get("timeout_seconds", 5))
        DB_UP.labels(*labels).set(1 if is_up else 0)
        DB_RESPONSE_TIME.labels(*labels).set(ms)
        _set_check_result(sid, t["display_name"], t["system_group"], "postgres", is_up, err, response_time_ms=ms)
        logger.info("Postgres %s: %s (%.1fms)%s", sid, "UP" if is_up else "DOWN", ms, f" {err}" if err else "")


def run_redis_checks(targets: list[dict]):
    for t in targets:
        sid = t["system_id"]
        labels = [sid, t["display_name"], t["system_group"], "REDIS"]
        host, port = t["host"], int(t.get("port", 6379))
        is_up, ms, err = check_redis(host, port, t.get("timeout_seconds", 5))
        DB_UP.labels(*labels).set(1 if is_up else 0)
        DB_RESPONSE_TIME.labels(*labels).set(ms)
        _set_check_result(sid, t["display_name"], t["system_group"], "redis", is_up, err, response_time_ms=ms)
        logger.info("Redis %s: %s (%.1fms)%s", sid, "UP" if is_up else "DOWN", ms, f" {err}" if err else "")


def run_mongodb_checks(targets: list[dict]):
    for t in targets:
        sid = t["system_id"]
        labels = [sid, t["display_name"], t["system_group"], "MONGODB"]
        host, port = t["host"], int(t.get("port", 27017))
        is_up, ms, err = check_mongodb(host, port, t.get("timeout_seconds", 5))
        DB_UP.labels(*labels).set(1 if is_up else 0)
        DB_RESPONSE_TIME.labels(*labels).set(ms)
        _set_check_result(sid, t["display_name"], t["system_group"], "mongodb", is_up, err, response_time_ms=ms)
        logger.info("MongoDB %s: %s (%.1fms)%s", sid, "UP" if is_up else "DOWN", ms, f" {err}" if err else "")


def run_elasticsearch_checks(targets: list[dict]):
    for t in targets:
        sid = t["system_id"]
        labels = [sid, t["display_name"], t["system_group"], "ELASTICSEARCH"]
        is_up, ms, status, err = check_elasticsearch(t["url"], t.get("timeout_seconds", 10))
        DB_UP.labels(*labels).set(1 if is_up else 0)
        DB_RESPONSE_TIME.labels(*labels).set(ms)
        _set_check_result(sid, t["display_name"], t["system_group"], "elasticsearch",
                          is_up, err or status, response_time_ms=ms)
        if status and status != "unknown":
            SYSTEM_VERSION.labels(*labels[:3]).info({"version": status, "type": "elasticsearch-status"})
        logger.info("Elasticsearch %s: %s status=%s (%.1fms)%s",
                    sid, "UP" if is_up else "DOWN", status, ms, f" {err}" if err else "")


# ============================================================================
# Blackbox Result Logging (Prometheus API → Postgres)
# ============================================================================

def log_blackbox_results(prometheus_url: str):
    """Query Prometheus for Blackbox probe results and log them to Postgres."""
    jobs = "blackbox_http|blackbox_tcp|blackbox_icmp"
    queries = {
        "success": f'probe_success{{job=~"{jobs}"}}',
        "duration": f'probe_duration_seconds{{job=~"{jobs}"}}',
        "http_code": 'probe_http_status_code{job="blackbox_http"}',
    }

    data: dict[tuple[str, str], dict] = {}  # (job, instance) → {success, duration, http_code}

    for key, query in queries.items():
        try:
            resp = requests.get(
                f"{prometheus_url}/api/v1/query",
                params={"query": query},
                timeout=10,
            )
            if resp.status_code != 200:
                logger.warning("Prometheus query failed for %s: HTTP %d", key, resp.status_code)
                continue
            result = resp.json().get("data", {}).get("result", [])
            for item in result:
                metric = item["metric"]
                job = metric.get("job", "")
                instance = metric.get("instance", "")
                val = float(item["value"][1])
                lookup_key = (job, instance)
                if lookup_key not in data:
                    data[lookup_key] = {"labels": metric}
                data[lookup_key][key] = val
        except Exception:
            logger.warning("Failed to query Prometheus for %s", key, exc_info=True)

    if not data:
        return

    batch = []
    for (job, instance), values in data.items():
        success = values.get("success")
        if success is None:
            continue
        is_up = success == 1.0
        duration_s = values.get("duration", 0.0)
        response_time_ms = duration_s * 1000
        http_code = int(values["http_code"]) if "http_code" in values else None
        error = "" if is_up else "probe_failed"

        labels = values.get("labels", {})
        # ICMP targets use node_id, HTTP/TCP use system_id
        system_id = labels.get("system_id") or labels.get("node_id", "")
        if not system_id:
            continue

        batch.append((system_id, is_up, response_time_ms, error, http_code))

    if batch:
        _db_logger.log_check_batch(batch)
        logger.info("Logged %d blackbox probe results to Postgres", len(batch))


# ============================================================================
# Main Loop
# ============================================================================

# ============================================================================
# DB-backed target loaders
# ============================================================================
#
# Targets are no longer read from config.yml. The admin UI writes them into
# monitored_system; each check cycle re-queries the table so changes take
# effect within `check_interval_seconds` of being saved.

# Defaults applied when monitored_system rows leave the relevant column NULL.
_DEFAULT_TARGET_TIMEOUT_S      = 30
_KEYCLOAK_DEFAULT_REALM_PATH   = "/auth/realms/master"
_DEFAULT_VERSION_STRATEGY      = "spring_actuator"

# system_types whose targets are addressed by a (host, port) pair in db_host/db_port.
_HOST_PORT_TYPES = ("DATABASE", "POSTGRES", "REDIS", "MONGODB")

# system_types whose targets are addressed by a single URL.
_URL_ONLY_TYPES  = ("LDAP", "ELASTICSEARCH")


def _base_target(row: dict) -> dict:
    """The fields every check_* function expects, regardless of system_type."""
    return {
        "system_id":       row["system_id"],
        "display_name":    row["display_name"],
        "system_group":    row["system_group"],
        "timeout_seconds": row.get("timeout_seconds") or _DEFAULT_TARGET_TIMEOUT_S,
    }


def _shape_target(row: dict, system_type: str) -> dict | None:
    """Map a raw monitored_system row to the dict shape its check_* function
    expects, returning None when the required fields for that system_type are
    missing (caller filters None out)."""
    if system_type in _URL_ONLY_TYPES:
        if not row.get("url"):
            return None
        return {**_base_target(row), "url": row["url"]}
    if system_type == "KEYCLOAK":
        if not row.get("url"):
            return None
        return {**_base_target(row),
                "base_url":   row["url"],
                "realm_path": row.get("realm_path") or _KEYCLOAK_DEFAULT_REALM_PATH}
    if system_type in _HOST_PORT_TYPES:
        host, port = row.get("db_host"), row.get("db_port")
        if not host or not port:
            return None
        return {**_base_target(row), "host": host, "port": port}
    if system_type == "VERSION":
        if not row.get("url"):
            return None
        return {**_base_target(row),
                "url":      row["url"],
                "strategy": row.get("version_strategy") or _DEFAULT_VERSION_STRATEGY}
    return None


def _load_db_targets(db_config: dict, system_type: str) -> list[dict]:
    """Return enabled rows of the given system_type as plain dicts, normalised
    to the shape the check_* functions expect. Skips rows whose required
    columns are NULL for the requested type."""
    try:
        conn = _db.connect(db_config)
    except Exception:
        logger.warning("Failed to connect to Postgres to load %s targets", system_type, exc_info=True)
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT system_id, display_name, system_group, url, realm_path, "
                "       db_host, db_port, version_strategy, timeout_seconds "
                "FROM monitored_system "
                "WHERE system_type = %s AND is_enable = 1",
                (system_type,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return [t for r in rows if (t := _shape_target(r, system_type)) is not None]


def run_all_checks(config: dict):
    """Run one cycle of LDAP/Keycloak/Database/Version checks.

    Targets come from monitored_system via the DB, not from config.yml. If the
    DB is unreachable we log and skip rather than crash — the next cycle will
    retry.
    """
    db_config = dict(config.get("postgres") or {})
    if env_host := os.environ.get("POSTGRES_HOST"):
        db_config["host"] = env_host
    if env_pw := os.environ.get("POSTGRES_PASSWORD"):
        db_config["password"] = env_pw
    if not db_config.get("enabled", False):
        logger.warning("Postgres disabled in config; no checks to run.")
        return

    ldap_targets     = _load_db_targets(db_config, "LDAP")
    keycloak_targets = _load_db_targets(db_config, "KEYCLOAK")
    database_targets = _load_db_targets(db_config, "DATABASE")
    version_targets  = _load_db_targets(db_config, "VERSION")
    postgres_targets = _load_db_targets(db_config, "POSTGRES")
    redis_targets    = _load_db_targets(db_config, "REDIS")
    mongo_targets    = _load_db_targets(db_config, "MONGODB")
    es_targets       = _load_db_targets(db_config, "ELASTICSEARCH")

    if ldap_targets:     run_ldap_checks(ldap_targets)
    if keycloak_targets: run_keycloak_checks(keycloak_targets)
    if database_targets: run_database_checks(database_targets)
    if version_targets:  run_version_checks(version_targets)
    if postgres_targets: run_postgres_checks(postgres_targets)
    if redis_targets:    run_redis_checks(redis_targets)
    if mongo_targets:    run_mongodb_checks(mongo_targets)
    if es_targets:       run_elasticsearch_checks(es_targets)


def check_loop(config: dict, interval: int):
    # PROMETHEUS_URL env var overrides config — needed for Docker where Prometheus
    # is a separate service (http://prometheus:9090), not localhost
    prometheus_url = (
        os.environ.get("PROMETHEUS_URL")
        or config.get("prometheus", {}).get("url", "http://127.0.0.1:9090")
    )
    while True:
        try:
            run_all_checks(config)
            if _db_logger is not None:
                log_blackbox_results(prometheus_url)
                _db_logger.run_cleanup()
        except Exception:
            logger.exception("Error during check cycle")
        time.sleep(interval)


def main():
    global _db_logger

    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, "config.yml")
    config = load_config(config_path)

    exporter_config = config.get("exporter", {})
    port = exporter_config.get("port", 9116)
    interval = exporter_config.get("check_interval_seconds", 300)

    # Initialize Postgres logger if enabled
    db_config = config.get("postgres") or {}
    if env_host := os.environ.get("POSTGRES_HOST"):
        db_config["host"] = env_host
    if env_pw := os.environ.get("POSTGRES_PASSWORD"):
        db_config["password"] = env_pw
    if db_config.get("enabled", False):
        try:
            _db_logger = HealthCheckLogger(db_config)
            logger.info("Postgres health check logging enabled (%s:%d/%s, retention=%dd)",
                        db_config.get("host"), db_config.get("port"),
                        db_config.get("database"), db_config.get("retention_days", 90))
        except Exception:
            logger.warning("Failed to initialize Postgres logger, continuing without DB logging", exc_info=True)
            _db_logger = None

    # Target counts now live in the DB; query them so EXPORTER_INFO reflects
    # the actual catalog rather than the (now-empty) config.yml lists.
    counts = {"LDAP": 0, "KEYCLOAK": 0, "DATABASE": 0, "VERSION": 0}
    if db_config.get("enabled", False):
        for t in counts:
            counts[t] = len(_load_db_targets(db_config, t))

    EXPORTER_INFO.info({
        "version": "2.2.0",
        "source": "monitor-grafana",
        "check_interval": str(interval),
        "ldap_targets": str(counts["LDAP"]),
        "keycloak_targets": str(counts["KEYCLOAK"]),
        "version_targets": str(counts["VERSION"]),
        "database_targets": str(counts["DATABASE"]),
        "target_source": "monitored_system table (admin UI on :9119)",
    })

    logger.info("Starting Monitor Exporter on port %d", port)
    logger.info("Check interval: %d seconds", interval)
    logger.info("Targets (from DB): %d LDAP, %d Keycloak, %d version, %d database checks",
                counts["LDAP"], counts["KEYCLOAK"], counts["VERSION"], counts["DATABASE"])

    # Run initial checks before starting the HTTP server
    run_all_checks(config)

    # Start Prometheus HTTP server
    start_http_server(port)
    logger.info("Prometheus metrics available at http://localhost:%d/metrics", port)

    # Start periodic check loop
    check_thread = threading.Thread(
        target=check_loop, args=(config, interval), daemon=True
    )
    check_thread.start()




    # Start the admin UI + Prometheus HTTP-SD endpoints on port 9119.
    # The same Flask app serves /admin/* (browser CRUD) and /sd/* (Prometheus
    # discovery) so they share a port and a DB connection pool.
    admin_port = int(os.environ.get("ADMIN_UI_PORT", "9119"))
    start_admin_ui(config, port=admin_port)

    # Background reconciler: keep Grafana datasources in lockstep with the
    # `datasource` table edited through the admin UI.
    start_datasource_sync(config)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down Monitor Monitor Exporter")


if __name__ == "__main__":
    main()

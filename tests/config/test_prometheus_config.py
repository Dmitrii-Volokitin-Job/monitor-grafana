"""Validate prometheus.yml structure and scrape job configuration."""


REQUIRED_JOBS = {
    "blackbox_http", "blackbox_tcp", "blackbox_icmp",
    "monitor_exporter", "ssl_certificates", "prometheus",
}


def _job_names(prometheus_config):
    return {j["job_name"] for j in prometheus_config.get("scrape_configs", [])}


def _get_job(prometheus_config, name):
    for j in prometheus_config["scrape_configs"]:
        if j["job_name"] == name:
            return j
    return None


def _parse_duration_seconds(d: str) -> float:
    """Convert '5m', '30s', '2h' to seconds."""
    if d.endswith("m"):
        return float(d[:-1]) * 60
    elif d.endswith("h"):
        return float(d[:-1]) * 3600
    elif d.endswith("s"):
        return float(d[:-1])
    return float(d)


# ---------------------------------------------------------------------------
# Global settings
# ---------------------------------------------------------------------------

def test_global_scrape_interval_defined(prometheus_config):
    assert "scrape_interval" in prometheus_config.get("global", {})


def test_global_evaluation_interval_defined(prometheus_config):
    assert "evaluation_interval" in prometheus_config.get("global", {})


def test_rule_files_configured(prometheus_config):
    assert prometheus_config.get("rule_files"), "rule_files must be non-empty"


# ---------------------------------------------------------------------------
# Required scrape jobs
# ---------------------------------------------------------------------------

def test_required_jobs_present(prometheus_config):
    found = _job_names(prometheus_config)
    missing = REQUIRED_JOBS - found
    assert not missing, f"Missing scrape jobs: {missing}"


def test_blackbox_http_uses_service_discovery(prometheus_config):
    job = _get_job(prometheus_config, "blackbox_http")
    assert job is not None
    assert any(k in job for k in ("http_sd_configs", "file_sd_configs", "static_configs"))


def test_blackbox_http_relabels_address_to_blackbox(prometheus_config):
    job = _get_job(prometheus_config, "blackbox_http")
    assert job is not None
    relabels = job.get("relabel_configs", [])
    # Must have a relabel that sets __address__ to blackbox exporter
    address_rewrites = [
        r for r in relabels
        if r.get("target_label") == "__address__"
    ]
    assert address_rewrites, "blackbox_http must relabel __address__ to blackbox exporter"


def test_monitor_exporter_targets_port_9116(prometheus_config):
    job = _get_job(prometheus_config, "monitor_exporter")
    assert job is not None
    configs = job.get("static_configs", [])
    all_targets = [t for c in configs for t in c.get("targets", [])]
    assert any("9116" in str(t) for t in all_targets), \
        "monitor_exporter must target port 9116"


def test_ssl_certificates_targets_port_9117(prometheus_config):
    job = _get_job(prometheus_config, "ssl_certificates")
    assert job is not None
    relabels = job.get("relabel_configs", [])
    address_values = [r.get("replacement", "") for r in relabels
                      if r.get("target_label") == "__address__"]
    assert any("9117" in v for v in address_values), \
        "ssl_certificates must relabel __address__ to port 9117"


def test_scrape_timeout_less_than_interval(prometheus_config):
    """scrape_timeout must be less than scrape_interval per job."""
    global_interval = _parse_duration_seconds(
        prometheus_config["global"].get("scrape_interval", "60s"))
    global_timeout = _parse_duration_seconds(
        prometheus_config["global"].get("scrape_timeout", "10s"))
    assert global_timeout < global_interval, \
        "Global scrape_timeout must be less than scrape_interval"

    for job in prometheus_config.get("scrape_configs", []):
        interval = _parse_duration_seconds(
            job.get("scrape_interval", prometheus_config["global"]["scrape_interval"]))
        timeout_str = job.get("scrape_timeout",
                               prometheus_config["global"].get("scrape_timeout", "10s"))
        timeout = _parse_duration_seconds(timeout_str)
        # Prometheus allows timeout == interval; only timeout > interval is invalid
        assert timeout <= interval, \
            f"Job '{job['job_name']}': scrape_timeout ({timeout}s) > scrape_interval ({interval}s)"

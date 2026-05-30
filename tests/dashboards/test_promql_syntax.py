"""
Validate PromQL expressions in dashboard panels.

Syntax errors in PromQL show as silent 'No data' — no Grafana error is shown.
"""
import re
from .conftest import iter_panels

KNOWN_METRICS = {
    "probe_success", "probe_duration_seconds", "probe_ssl_earliest_cert_expiry",
    "probe_http_status_code", "probe_tls_version_info",
    "monitor_ldap_up", "monitor_ldap_response_time_ms",
    "monitor_keycloak_up", "monitor_keycloak_response_time_ms", "monitor_keycloak_realm_valid",
    "monitor_database_up", "monitor_database_response_time_ms",
    "monitor_check_result_info", "monitor_system_version_info",
    "monitor:system_health_pct", "monitor:group_health_pct", "monitor:group_uptime_1h_pct",
    "monitor:systems_up_total", "monitor:systems_down_total",
    "monitor:ssl_days_until_expiry", "monitor:ssl_expiring_30d_count", "monitor:ssl_expired_count",
    "monitor:keycloak_up_total", "monitor:database_up_total", "monitor:ldap_up_total",
    "monitor:keycloak_down_total", "monitor:database_down_total", "monitor:ldap_down_total",
    "up",
}


def _collect_exprs(dashboard):
    """Yield all non-empty PromQL expressions from a dashboard."""
    _, d = dashboard
    for panel in iter_panels(d.get("panels", [])):
        for target in panel.get("targets", []):
            expr = target.get("expr", "").strip()
            if expr:
                yield panel, expr


def test_all_exprs_have_balanced_curly_braces(dashboard):
    fname, _ = dashboard
    bad = []
    for panel, expr in _collect_exprs(dashboard):
        if expr.count("{") != expr.count("}"):
            bad.append((panel.get("title"), expr))
    assert not bad, (
        f"{fname}: PromQL expressions with unbalanced braces:\n"
        + "\n".join(f"  [{t}] {e}" for t, e in bad)
    )


def test_all_exprs_have_balanced_square_brackets(dashboard):
    fname, _ = dashboard
    bad = []
    for panel, expr in _collect_exprs(dashboard):
        if expr.count("[") != expr.count("]"):
            bad.append((panel.get("title"), expr))
    assert not bad, (
        f"{fname}: PromQL expressions with unbalanced brackets:\n"
        + "\n".join(f"  [{t}] {e}" for t, e in bad)
    )


def test_ssl_days_exprs_divide_by_86400(dashboard):
    """
    SSL expiry panels that display DAYS must divide the Unix timestamp diff by 86400.
    Panels that only check expired/not-expired (compare to 0) don't need to divide.
    """
    fname, _ = dashboard
    for panel, expr in _collect_exprs(dashboard):
        if "ssl_earliest_cert_expiry" not in expr or "time()" not in expr:
            continue
        # Only require /86400 if the result is being presented as days (not just <=/>0 checks)
        # Expired-count panels: "... <= 0" or "... > 0" without further computation
        is_count_only = bool(
            re.search(r"\)\s*(<=|>=|<|>)\s*0\b", expr)
            and "/ 86400" not in expr
            and "/86400" not in expr
        )
        if is_count_only:
            continue  # counting expired/valid without showing days — OK
        assert "86400" in expr, (
            f"{fname}: panel '{panel.get('title')}' shows SSL days "
            f"but doesn't divide by 86400: {expr}"
        )


def test_health_pct_exprs_multiply_by_100(dashboard):
    """Uptime/health percentage panels must multiply probe_success by 100."""
    fname, _ = dashboard
    for panel, expr in _collect_exprs(dashboard):
        if "avg_over_time" in expr and "probe_success" in expr:
            assert "* 100" in expr or "*100" in expr, (
                f"{fname}: panel '{panel.get('title')}' computes uptime % but "
                f"doesn't multiply by 100: {expr}"
            )


_PROMQL_KEYWORDS = {
    # boolean / grouping modifiers
    "by", "on", "bool", "group_left", "group_right", "without", "ignoring",
    "offset", "and", "or", "unless",
    # aggregation operators (https://prometheus.io/docs/prometheus/latest/querying/operators/#aggregation-operators)
    "sum", "min", "max", "avg", "count", "stddev", "stdvar", "topk", "bottomk",
    "quantile", "group", "count_values",
    # over_time functions
    "avg_over_time", "count_over_time", "sum_over_time", "min_over_time",
    "max_over_time", "stddev_over_time", "stdvar_over_time", "quantile_over_time",
    "last_over_time", "present_over_time",
    # instant functions
    "rate", "irate", "increase", "delta", "idelta", "deriv", "predict_linear",
    "absent", "absent_over_time", "changes", "resets", "holt_winters",
    "label_replace", "label_join",
    # type conversions / math
    "vector", "scalar", "sort", "sort_desc", "time", "timestamp",
    "round", "floor", "ceil", "abs", "exp", "ln", "log2", "log10", "sqrt",
    "clamp_max", "clamp_min", "clamp",
    # time helpers
    "year", "month", "day_of_month", "day_of_week", "hour", "minute",
    "days_in_month",
    # histogram
    "histogram_quantile", "histogram_count", "histogram_sum",
}


def test_exprs_reference_known_metric_families(dashboard):
    """Warn (not fail) if an expression uses a metric not in our known set.
    New metrics may be added; this catches typos.

    Only the part of the expression OUTSIDE label selectors `{...}` and string
    literals counts as a metric reference — otherwise label keys/values like
    `job="blackbox_http"` get mis-flagged as unknown metrics.
    """
    fname, _ = dashboard
    unknown = []
    for panel, expr in _collect_exprs(dashboard):
        stripped = re.sub(r'\{[^}]*\}', '', expr)
        stripped = re.sub(r'"[^"]*"', '', stripped)
        stripped = re.sub(r'\b(?:by|without|on|ignoring|group_left|group_right)\s*\([^)]*\)',
                          '', stripped)
        candidates = re.findall(r'\b([a-z][a-z0-9_:]+)\b', stripped)
        for c in candidates:
            if len(c) < 5 or c in _PROMQL_KEYWORDS:
                continue
            if c not in KNOWN_METRICS and not c.startswith("monitor"):
                unknown.append((panel.get("title"), c, expr[:60]))

    if unknown:
        import warnings
        warnings.warn(
            f"{fname}: Expressions reference unrecognized metric names "
            f"(may be new metrics or typos):\n"
            + "\n".join(f"  [{t}] '{m}' in: {e}..." for t, m, e in unknown[:5])
        )
    # Teeth: a small number of unknowns is tolerable (new metric, edge-case
    # tokenizer miss) but a sudden flood means our regex/keyword list broke
    # or someone mass-renamed a metric without updating dashboards.
    assert len(unknown) < 20, (
        f"{fname}: {len(unknown)} unrecognized metric names — likely a regex "
        f"or rename regression. First few: {unknown[:5]}"
    )

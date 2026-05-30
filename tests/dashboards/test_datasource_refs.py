"""
Validate that every datasource UID in panel definitions resolves to a
provisioned datasource. A wrong UID causes silent 'No data' in Grafana.
"""
from .conftest import PROVISIONED_DS_UIDS, VARIABLE_DS_RE, iter_panels


def test_all_datasource_uids_are_valid(dashboard):
    """
    Every panel datasource.uid must be either:
    - A provisioned UID (from datasources.yml)
    - A Grafana template variable like ${DS_MARIADB}
    """
    fname, d = dashboard
    bad = []

    for panel in iter_panels(d.get("panels", [])):
        ds = panel.get("datasource")
        if not isinstance(ds, dict):
            continue
        uid = ds.get("uid", "")
        if not uid:
            continue
        is_provisioned = uid in PROVISIONED_DS_UIDS
        is_variable = bool(VARIABLE_DS_RE.match(uid))
        if not (is_provisioned or is_variable):
            bad.append((panel.get("title", f"id={panel.get('id')}"), uid))

    assert not bad, (
        f"{fname}: panels reference unknown datasource UIDs:\n"
        + "\n".join(f"  Panel '{t}': uid='{u}'" for t, u in bad)
        + f"\nProvisioned UIDs: {PROVISIONED_DS_UIDS}"
    )


def test_prometheus_panels_use_monitor_prometheus_uid(dashboard):
    """Panels using PromQL must reference monitor-prometheus, not a raw URL."""
    fname, d = dashboard
    for panel in iter_panels(d.get("panels", [])):
        for target in panel.get("targets", []):
            expr = target.get("expr", "")
            if not expr:
                continue
            ds = panel.get("datasource", {})
            if not isinstance(ds, dict):
                continue
            uid = ds.get("uid", "")
            assert uid != "http://localhost:9090", \
                f"{fname}: panel '{panel.get('title')}' uses raw Prometheus URL instead of uid"


def test_all_target_datasource_uids_are_valid(dashboard):
    """A query target can override its panel's datasource. The override UID
    must resolve too — otherwise that single query silently shows 'No data'
    while the rest of the panel works (much harder to notice than a
    panel-level break)."""
    fname, d = dashboard
    bad = []
    for panel in iter_panels(d.get("panels", [])):
        for target in panel.get("targets", []):
            ds = target.get("datasource")
            if not isinstance(ds, dict):
                continue
            uid = ds.get("uid", "")
            if not uid:
                continue
            is_provisioned = uid in PROVISIONED_DS_UIDS
            is_variable = bool(VARIABLE_DS_RE.match(uid))
            if not (is_provisioned or is_variable):
                bad.append((panel.get("title", f"id={panel.get('id')}"),
                            target.get("refId", "?"), uid))
    assert not bad, (
        f"{fname}: query targets reference unknown datasource UIDs:\n"
        + "\n".join(f"  Panel '{t}' refId={r}: uid='{u}'" for t, r, u in bad)
        + f"\nProvisioned UIDs: {PROVISIONED_DS_UIDS}"
    )

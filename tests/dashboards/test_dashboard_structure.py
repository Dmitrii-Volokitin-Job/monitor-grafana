"""Validate dashboard JSON top-level structure and panel requirements."""
import os
import pytest
from .conftest import EXPECTED_DASHBOARDS, DASHBOARDS_DIR, iter_panels


def test_all_8_dashboard_files_exist():
    missing = [f for f in EXPECTED_DASHBOARDS
               if not os.path.exists(os.path.join(DASHBOARDS_DIR, f))]
    assert not missing, f"Missing dashboard files: {missing}"


def test_each_dashboard_has_uid(dashboard):
    fname, d = dashboard
    assert d.get("uid"), f"{fname}: missing 'uid' field"


def test_each_dashboard_has_title(dashboard):
    fname, d = dashboard
    assert d.get("title"), f"{fname}: missing or empty 'title'"


def test_each_dashboard_has_schema_version(dashboard):
    fname, d = dashboard
    assert d.get("schemaVersion", 0) >= 36, \
        f"{fname}: schemaVersion should be >= 36 (got {d.get('schemaVersion')})"


def test_each_dashboard_has_panels(dashboard):
    fname, d = dashboard
    assert d.get("panels"), f"{fname}: no panels defined"


def test_non_row_panels_have_titles(dashboard):
    fname, d = dashboard
    for panel in iter_panels(d.get("panels", [])):
        if panel.get("type") == "row":
            continue
        assert panel.get("title") is not None, \
            f"{fname}: panel id={panel.get('id')} has no title"


def test_non_row_panels_have_type(dashboard):
    fname, d = dashboard
    for panel in iter_panels(d.get("panels", [])):
        assert panel.get("type"), \
            f"{fname}: panel id={panel.get('id')} has no type"


def test_all_dashboards_share_same_editable_flag(all_dashboards):
    # Audit row 4.1: provisioned dashboards should agree on the `editable`
    # flag. Mixing true/false across the set is almost always a copy-paste
    # oversight — locking the value here means a change to one dashboard
    # forces a deliberate change to the rest.
    flags = {fname: d.get("editable") for fname, d in all_dashboards.items()}
    distinct = set(flags.values())
    assert len(distinct) == 1, f"Dashboards disagree on `editable`: {flags}"


# Cross-dashboard consistency: when the same variable name is declared on
# multiple dashboards, it should produce the same value space — otherwise
# users selecting an option on one dashboard and clicking through to another
# silently see a different list (or no match at all).
#
# Each entry maps `variable_name` → why the divergence is currently tolerated.
# Removing an entry == promising to align the queries; keep the dict small.
KNOWN_VARIABLE_DIVERGENCES = {
    "system_group": (
        "alert-history.json reads DISTINCT system_group FROM monitored_system; "
        "the other 4 dashboards read COALESCE(display_name, name) FROM lab. "
        "Both yield the same filter VALUES; the user-visible LABEL differs."
    ),
    "DS_PROMETHEUS": (
        "Case drift on the datasource-type filter: 2 dashboards use lowercase "
        "'prometheus' (matches the provisioned type id), 3 use 'Prometheus'. "
        "Grafana matches case-insensitively, so both resolve to the same DS."
    ),
}


def _collect_variables_by_name(all_dashboards):
    """{var_name: [(dashboard_file, type, query_string), ...]}"""
    import collections
    out = collections.defaultdict(list)
    for fname, d in all_dashboards.items():
        for v in d.get("templating", {}).get("list", []):
            q = v.get("query")
            if isinstance(q, dict):
                q = q.get("query")
            out[v["name"]].append((fname, v.get("type"), q))
    return out


def test_same_named_variables_share_one_definition(all_dashboards):
    """If a variable appears on N dashboards, its (type, query) tuple must be
    identical across all N — or appear in KNOWN_VARIABLE_DIVERGENCES with a
    documented reason. Catches drift where one dashboard's edit silently
    desyncs the filter value space."""
    by_name = _collect_variables_by_name(all_dashboards)
    divergent = {}
    for name, entries in by_name.items():
        if len(entries) <= 1:
            continue
        first_t, first_q = entries[0][1], entries[0][2]
        if not all(e[1] == first_t and e[2] == first_q for e in entries):
            divergent[name] = entries
    unexpected = {n: locs for n, locs in divergent.items()
                  if n not in KNOWN_VARIABLE_DIVERGENCES}
    assert not unexpected, (
        "Cross-dashboard variable divergence — same name, different definitions:\n"
        + "\n".join(
            f"  {n}:\n" + "\n".join(f"    {f}  type={t}  query={q!r}" for f, t, q in locs)
            for n, locs in unexpected.items()
        )
        + "\n\nIf the divergence is intentional, document it in "
        + "KNOWN_VARIABLE_DIVERGENCES."
    )


def test_known_variable_divergences_still_diverge(all_dashboards):
    """Inverse guard: if someone aligns a variable (removing the divergence)
    but forgets to drop the allowlist entry, fail so the allowlist stays
    honest. A stale allowlist hides future regressions."""
    by_name = _collect_variables_by_name(all_dashboards)
    stale = []
    for name in KNOWN_VARIABLE_DIVERGENCES:
        entries = by_name.get(name, [])
        if len(entries) <= 1:
            stale.append(f"{name}: now appears on {len(entries)} dashboard(s)")
            continue
        first = (entries[0][1], entries[0][2])
        if all((e[1], e[2]) == first for e in entries):
            stale.append(f"{name}: definitions now match — remove from allowlist")
    assert not stale, "Stale KNOWN_VARIABLE_DIVERGENCES entries:\n  " + "\n  ".join(stale)

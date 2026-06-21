"""
admin_ui.py — web UI for CRUD-ing monitored systems.

Flask Blueprint mounted alongside sd_endpoints (same Flask app, port 9119).
Persists to the extended monitored_system table. Authorization is delegated
to Grafana: every request validates the inbound `grafana_session` cookie
against Grafana's /api/user, and the user's org role decides write access.

Routes (all under /admin):
    GET  /admin/                       list page with filters
    GET  /admin/new                    create form (?type=HTTP|TCP|…)
    POST /admin/systems                create
    GET  /admin/systems/<id>/edit      edit form
    POST /admin/systems/<id>           update
    POST /admin/systems/<id>/enable    toggle on
    POST /admin/systems/<id>/disable   toggle off
    POST /admin/systems/<id>/delete    delete
    GET  /admin/_fields/<type>         htmx partial: dynamic field set for a chosen type

The list and form templates live under monitor_exporter/templates/.
Form validation is server-side (per-type required-field matrix) plus
client-side `required` for fast feedback.
"""
from __future__ import annotations

import functools
import logging
import os
import threading
import time
from contextlib import contextmanager
from typing import Callable
from urllib.parse import quote, urljoin

import httpx
try:
    import db as _db
except ImportError:
    from monitor_exporter import db as _db
_IntegrityError = _db.IntegrityError  # noqa: F841
from flask import (
    Blueprint, Flask, abort, flash, redirect, render_template, request,
    session, url_for,
)

logger = logging.getLogger("admin_ui")

# Cache Grafana auth decisions per cookie for this many seconds.
AUTH_CACHE_TTL_S = 60

# Per-system-type required fields. Fields listed here MUST be non-empty on
# create/update; any field not listed is optional.
REQUIRED_FIELDS: dict[str, list[str]] = {
    "HTTP":          ["system_id", "display_name", "system_group", "url", "blackbox_module"],
    "TCP":           ["system_id", "display_name", "system_group", "url"],
    "ICMP":          ["system_id", "display_name", "system_group", "url"],
    "SSL":           ["system_id", "display_name", "url", "cert_alias"],
    "LDAP":          ["system_id", "display_name", "system_group", "url"],
    "KEYCLOAK":      ["system_id", "display_name", "system_group", "url", "realm_path"],
    "DATABASE":      ["system_id", "display_name", "system_group", "db_host", "db_port"],
    "POSTGRES":      ["system_id", "display_name", "system_group", "db_host", "db_port"],
    "REDIS":         ["system_id", "display_name", "system_group", "db_host", "db_port"],
    "MONGODB":       ["system_id", "display_name", "system_group", "db_host", "db_port"],
    "ELASTICSEARCH": ["system_id", "display_name", "system_group", "url"],
    "GRPC":          ["system_id", "display_name", "system_group", "url", "blackbox_module"],
    "DNS":           ["system_id", "display_name", "system_group", "url", "blackbox_module"],
    "VERSION":       ["system_id", "display_name", "system_group", "url", "version_strategy"],
}

# Columns the form may write. system_id is required; the rest are stored as-is.
ALL_FIELDS = [
    "system_id", "display_name", "system_group", "system_type", "url",
    "description", "health_check_path", "expected_status_code",
    "timeout_seconds", "priority", "blackbox_module", "version_strategy",
    "realm_path", "db_host", "db_port",
    "node_id", "node_name", "lab_group", "node_type",
    "cert_alias", "cert_description",
]

BLACKBOX_MODULES = ["http_2xx", "http_2xx_or_401", "http_302", "http_401",
                    "tcp_connect", "icmp_ping",
                    "grpc", "grpc_plain", "dns_udp", "dns_tcp"]
VERSION_STRATEGIES = ["spring_actuator", "openapi", "gateway_version",
                      "json_version", "kubernetes", "camunda", "monitor_version"]
NODE_TYPES = ["SERVER", "MASTER", "WORKER", "EDGE", "LOAD_BALANCER", "DB"]
SYSTEM_TYPES = list(REQUIRED_FIELDS.keys())
DATASOURCE_TYPES = ["mysql", "postgres", "prometheus", "loki", "influxdb",
                    "elasticsearch", "mongodb-bi", "tempo"]


# ============================================================================
# DB helpers
# ============================================================================

def _connect(db_config: dict):
    return _db.connect(db_config)


@contextmanager
def _cursor(db_config: dict):
    """Open a connection, yield a dict cursor, always close.

    Replaces the boilerplate `conn = _connect(); try: with conn.cursor() …
    finally: conn.close()` repeated across every CRUD helper.
    """
    conn = _connect(db_config)
    try:
        with conn.cursor() as cur:
            yield cur
    finally:
        conn.close()


def _list_systems(db_config, type_filter=None, group_filter=None, enabled_filter=None):
    sql = "SELECT * FROM monitored_system WHERE 1=1"
    args: list = []
    if type_filter:
        sql += " AND system_type = %s"; args.append(type_filter)
    if group_filter:
        sql += " AND system_group = %s"; args.append(group_filter)
    if enabled_filter in ("1", "0"):
        sql += " AND is_enable = %s"; args.append(int(enabled_filter))
    sql += " ORDER BY system_group, system_type, system_id"
    with _cursor(db_config) as cur:
        cur.execute(sql, tuple(args))
        return cur.fetchall()


def _get_system(db_config, pk: int):
    with _cursor(db_config) as cur:
        cur.execute("SELECT * FROM monitored_system WHERE id = %s", (pk,))
        return cur.fetchone()


def _distinct_groups(db_config) -> list[str]:
    """Return all known lab names (preferred) plus any orphan system_groups."""
    with _cursor(db_config) as cur:
        cur.execute("SELECT name FROM lab WHERE is_enable = 1 ORDER BY name")
        names = [r["name"] for r in cur.fetchall()]
        cur.execute(
            "SELECT DISTINCT system_group FROM monitored_system "
            "WHERE system_group <> '' AND system_group NOT IN ("
            "  SELECT name FROM lab) ORDER BY system_group"
        )
        names.extend(r["system_group"] for r in cur.fetchall())
        return names


# ============================================================================
# Lab CRUD
# ============================================================================

def _list_labs(db_config) -> list[dict]:
    with _cursor(db_config) as cur:
        cur.execute(
            "SELECT l.*, "
            "  (SELECT COUNT(*) FROM monitored_system s WHERE s.system_group = l.name) AS system_count "
            "FROM lab l ORDER BY l.name"
        )
        return cur.fetchall()


def _get_lab(db_config, pk: int) -> dict | None:
    with _cursor(db_config) as cur:
        cur.execute("SELECT * FROM lab WHERE id = %s", (pk,))
        return cur.fetchone()


def _insert_lab(db_config, name: str, display_name: str, description: str):
    with _cursor(db_config) as cur:
        cur.execute(
            "INSERT INTO lab (name, display_name, description) VALUES (%s, %s, %s)",
            (name, display_name, description or None),
        )


def _update_lab(db_config, pk: int, display_name: str, description: str, is_enable: int):
    with _cursor(db_config) as cur:
        cur.execute(
            "UPDATE lab SET display_name = %s, description = %s, is_enable = %s WHERE id = %s",
            (display_name, description or None, is_enable, pk),
        )


def _delete_lab(db_config, pk: int) -> tuple[bool, str]:
    """Refuse to delete if any system still references the lab name."""
    with _cursor(db_config) as cur:
        cur.execute("SELECT name FROM lab WHERE id = %s", (pk,))
        row = cur.fetchone()
        if not row:
            return False, "Lab not found"
        cur.execute(
            "SELECT COUNT(*) AS n FROM monitored_system WHERE system_group = %s OR lab_group = %s",
            (row["name"], row["name"]),
        )
        n = cur.fetchone()["n"]
        if n > 0:
            return False, f"Lab {row['name']!r} is still referenced by {n} system(s). Reassign or delete those first."
        cur.execute("DELETE FROM lab WHERE id = %s", (pk,))
        return True, ""


# ============================================================================
# Datasource CRUD (Grafana data sources catalog)
# ============================================================================

def _list_datasources(db_config) -> list[dict]:
    with _cursor(db_config) as cur:
        cur.execute("SELECT * FROM datasource ORDER BY type, name")
        return cur.fetchall()


def _get_datasource(db_config, pk: int) -> dict | None:
    with _cursor(db_config) as cur:
        cur.execute("SELECT * FROM datasource WHERE id = %s", (pk,))
        return cur.fetchone()


def _insert_datasource(db_config, row: dict):
    cols = ["name", "display_name", "type", "url", "database_name",
            "db_user", "password_env", "lab_group", "is_enable"]
    sql = (f"INSERT INTO datasource ({', '.join(cols)}) "
           f"VALUES ({', '.join(['%s'] * len(cols))})")
    with _cursor(db_config) as cur:
        cur.execute(sql, tuple(row.get(c) for c in cols))


def _update_datasource(db_config, pk: int, row: dict):
    cols = ["display_name", "type", "url", "database_name",
            "db_user", "password_env", "lab_group", "is_enable"]
    sql = f"UPDATE datasource SET {', '.join(f'{c} = %s' for c in cols)} WHERE id = %s"
    with _cursor(db_config) as cur:
        cur.execute(sql, tuple(row.get(c) for c in cols) + (pk,))


def _delete_datasource(db_config, pk: int):
    with _cursor(db_config) as cur:
        cur.execute("DELETE FROM datasource WHERE id = %s", (pk,))


def _coerce(name: str, raw: str | None):
    """Turn form strings into the value type the column expects."""
    if raw is None or raw == "":
        return None
    if name in ("expected_status_code", "timeout_seconds", "priority", "db_port"):
        try:
            return int(raw)
        except ValueError:
            return None
    return raw.strip()


def _validate(form: dict) -> list[str]:
    errors: list[str] = []
    stype = form.get("system_type")
    if stype not in REQUIRED_FIELDS:
        errors.append(f"Unknown system_type: {stype!r}")
        return errors
    for f in REQUIRED_FIELDS[stype]:
        if not (form.get(f) or "").strip():
            errors.append(f"Missing required field: {f}")
    return errors


def _form_to_row(form: dict) -> dict:
    return {f: _coerce(f, form.get(f)) for f in ALL_FIELDS}


def _insert(db_config, row: dict):
    cols = [c for c in ALL_FIELDS if row.get(c) is not None]
    placeholders = ", ".join(["%s"] * len(cols))
    sql = f"INSERT INTO monitored_system ({', '.join(cols)}) VALUES ({placeholders})"
    with _cursor(db_config) as cur:
        cur.execute(sql, tuple(row[c] for c in cols))


def _update(db_config, pk: int, row: dict):
    # Allow explicit NULLs on update so a user can clear an optional field.
    set_clause = ", ".join(f"{c} = %s" for c in ALL_FIELDS if c != "system_id")
    args = [row.get(c) for c in ALL_FIELDS if c != "system_id"] + [pk]
    sql = f"UPDATE monitored_system SET {set_clause} WHERE id = %s"
    with _cursor(db_config) as cur:
        cur.execute(sql, tuple(args))


def _set_enabled(db_config, pk: int, enabled: bool):
    with _cursor(db_config) as cur:
        cur.execute("UPDATE monitored_system SET is_enable = %s WHERE id = %s",
                    (1 if enabled else 0, pk))


def _delete(db_config, pk: int):
    with _cursor(db_config) as cur:
        cur.execute("DELETE FROM monitored_system WHERE id = %s", (pk,))


# ============================================================================
# Grafana session auth
# ============================================================================

_auth_cache: dict[str, tuple[float, dict | None]] = {}
_auth_lock = threading.Lock()


def _check_grafana_session(cookie_value: str | None, internal_url: str) -> dict | None:
    """Return Grafana user dict or None. Cached AUTH_CACHE_TTL_S per cookie."""
    if not cookie_value:
        return None
    now = time.monotonic()
    with _auth_lock:
        entry = _auth_cache.get(cookie_value)
        if entry and entry[0] > now:
            return entry[1]
    user: dict | None = None
    try:
        r = httpx.get(
            urljoin(internal_url.rstrip("/") + "/", "api/user"),
            cookies={"grafana_session": cookie_value},
            timeout=2.0,
        )
        if r.status_code == 200:
            user = r.json()
    except Exception:
        logger.debug("Grafana /api/user call failed", exc_info=True)
    with _auth_lock:
        _auth_cache[cookie_value] = (now + AUTH_CACHE_TTL_S, user)
    return user


def _user_role(user: dict | None) -> str:
    if not user:
        return ""
    if user.get("isGrafanaAdmin"):
        return "Admin"
    # /api/user returns orgRole if the user belongs to the current org;
    # fall back to "Viewer" so unknown roles don't accidentally get write.
    return user.get("orgRole") or "Viewer"


def require_grafana_auth(min_role: str = "Editor") -> Callable:
    """Decorator: 302 to Grafana login if no session; 403 if role too low."""
    role_rank = {"Viewer": 1, "Editor": 2, "Admin": 3}
    required = role_rank.get(min_role, 2)

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            internal_url = os.environ.get("GRAFANA_INTERNAL_URL", "http://grafana:3000")
            public_url = os.environ.get("GRAFANA_PUBLIC_URL", "http://localhost:3000")
            cookie = request.cookies.get("grafana_session")
            user = _check_grafana_session(cookie, internal_url)
            if not user:
                login = f"{public_url.rstrip('/')}/login?redirect_to={quote(request.url, safe='')}"
                return redirect(login, code=302)
            actual = role_rank.get(_user_role(user), 0)
            if actual < required:
                abort(403, description=f"Role {_user_role(user)!r} cannot perform this action.")
            # stash for templates
            session_user = {"login": user.get("login"), "email": user.get("email"),
                            "role": _user_role(user)}
            request.environ["monitor.user"] = session_user
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# ============================================================================
# Blueprint
# ============================================================================

def create_blueprint(db_config: dict) -> Blueprint:
    bp = Blueprint("admin_ui", __name__,
                   template_folder=os.path.join(os.path.dirname(__file__), "templates"),
                   static_folder=os.path.join(os.path.dirname(__file__), "static"),
                   static_url_path="/admin/static",
                   url_prefix="/admin")

    @bp.context_processor
    def inject_user():
        return {
            "current_user": request.environ.get("monitor.user", {}),
            "system_types": SYSTEM_TYPES,
            "blackbox_modules": BLACKBOX_MODULES,
            "version_strategies": VERSION_STRATEGIES,
            "datasource_types": DATASOURCE_TYPES,
            "node_types": NODE_TYPES,
        }

    @bp.get("/")
    @require_grafana_auth(min_role="Viewer")
    def index():
        rows = _list_systems(
            db_config,
            type_filter=request.args.get("type") or None,
            group_filter=request.args.get("group") or None,
            enabled_filter=request.args.get("enabled"),
        )
        return render_template("systems_list.html",
                               rows=rows,
                               groups=_distinct_groups(db_config),
                               selected_type=request.args.get("type", ""),
                               selected_group=request.args.get("group", ""),
                               selected_enabled=request.args.get("enabled", ""))

    @bp.get("/new")
    @require_grafana_auth(min_role="Editor")
    def new():
        stype = request.args.get("type", "HTTP")
        if stype not in REQUIRED_FIELDS:
            stype = "HTTP"
        row = {"system_type": stype, "is_enable": 1, "timeout_seconds": 30, "priority": 5}
        return render_template("systems_form.html",
                               row=row, mode="new",
                               required_fields=REQUIRED_FIELDS[stype],
                               groups=_distinct_groups(db_config))

    @bp.get("/_fields/<stype>")
    @require_grafana_auth(min_role="Editor")
    def fields_partial(stype: str):
        # htmx swap when the type dropdown changes on the new/edit form.
        if stype not in REQUIRED_FIELDS:
            abort(400, "Unknown type")
        row = {"system_type": stype, "timeout_seconds": 30}
        return render_template(f"_form_fields_{stype.lower()}.html",
                               row=row,
                               required_fields=REQUIRED_FIELDS[stype])

    @bp.post("/systems")
    @require_grafana_auth(min_role="Editor")
    def create():
        form = request.form.to_dict()
        errors = _validate(form)
        if errors:
            for e in errors: flash(e, "error")
            row = {**form, "id": None}
            return render_template("systems_form.html",
                                   row=row, mode="new",
                                   required_fields=REQUIRED_FIELDS.get(form.get("system_type", "HTTP"), []),
                                   groups=_distinct_groups(db_config)), 400
        try:
            _insert(db_config, _form_to_row(form))
        except _IntegrityError as e:
            flash(f"system_id already exists: {form.get('system_id')!r}", "error")
            return render_template("systems_form.html",
                                   row={**form, "id": None}, mode="new",
                                   required_fields=REQUIRED_FIELDS.get(form.get("system_type", "HTTP"), []),
                                   groups=_distinct_groups(db_config)), 409
        flash(f"Created {form['system_id']}", "success")
        return redirect(url_for("admin_ui.index"))

    @bp.get("/systems/<int:pk>/edit")
    @require_grafana_auth(min_role="Editor")
    def edit(pk: int):
        row = _get_system(db_config, pk)
        if not row:
            abort(404)
        return render_template("systems_form.html",
                               row=row, mode="edit",
                               required_fields=REQUIRED_FIELDS.get(row["system_type"], []),
                               groups=_distinct_groups(db_config))

    @bp.post("/systems/<int:pk>")
    @require_grafana_auth(min_role="Editor")
    def update(pk: int):
        form = request.form.to_dict()
        errors = _validate(form)
        if errors:
            for e in errors: flash(e, "error")
            row = {**form, "id": pk}
            return render_template("systems_form.html",
                                   row=row, mode="edit",
                                   required_fields=REQUIRED_FIELDS.get(form.get("system_type", "HTTP"), []),
                                   groups=_distinct_groups(db_config)), 400
        _update(db_config, pk, _form_to_row(form))
        flash(f"Updated {form['system_id']}", "success")
        return redirect(url_for("admin_ui.index"))

    @bp.post("/systems/<int:pk>/enable")
    @require_grafana_auth(min_role="Editor")
    def enable(pk: int):
        _set_enabled(db_config, pk, True)
        if request.headers.get("HX-Request"):
            row = _get_system(db_config, pk)
            return render_template("_system_row.html", r=row)
        return redirect(url_for("admin_ui.index"))

    @bp.post("/systems/<int:pk>/disable")
    @require_grafana_auth(min_role="Editor")
    def disable(pk: int):
        _set_enabled(db_config, pk, False)
        if request.headers.get("HX-Request"):
            row = _get_system(db_config, pk)
            return render_template("_system_row.html", r=row)
        return redirect(url_for("admin_ui.index"))

    @bp.post("/systems/<int:pk>/delete")
    @require_grafana_auth(min_role="Editor")
    def delete(pk: int):
        row = _get_system(db_config, pk)
        if row:
            _delete(db_config, pk)
            flash(f"Deleted {row['system_id']}", "success")
        return redirect(url_for("admin_ui.index"))

    # --- Lab routes -----------------------------------------------------------

    @bp.get("/labs")
    @require_grafana_auth(min_role="Viewer")
    def labs_index():
        return render_template("labs_list.html", labs=_list_labs(db_config))

    @bp.get("/labs/new")
    @require_grafana_auth(min_role="Editor")
    def labs_new():
        return render_template("labs_form.html", lab={"is_enable": 1}, mode="new")

    @bp.post("/labs")
    @require_grafana_auth(min_role="Editor")
    def labs_create():
        name = (request.form.get("name") or "").strip()
        display_name = (request.form.get("display_name") or "").strip() or name
        description = (request.form.get("description") or "").strip()
        if not name:
            flash("Name is required", "error")
            return render_template("labs_form.html",
                                   lab={"name": name, "display_name": display_name,
                                        "description": description, "is_enable": 1},
                                   mode="new"), 400
        try:
            _insert_lab(db_config, name, display_name, description)
        except _IntegrityError:
            flash(f"Lab name already exists: {name!r}", "error")
            return render_template("labs_form.html",
                                   lab={"name": name, "display_name": display_name,
                                        "description": description, "is_enable": 1},
                                   mode="new"), 409
        flash(f"Created lab {name}", "success")
        return redirect(url_for("admin_ui.labs_index"))

    @bp.get("/labs/<int:pk>/edit")
    @require_grafana_auth(min_role="Editor")
    def labs_edit(pk: int):
        lab = _get_lab(db_config, pk)
        if not lab:
            abort(404)
        return render_template("labs_form.html", lab=lab, mode="edit")

    @bp.post("/labs/<int:pk>")
    @require_grafana_auth(min_role="Editor")
    def labs_update(pk: int):
        display_name = (request.form.get("display_name") or "").strip()
        description = (request.form.get("description") or "").strip()
        is_enable = 1 if request.form.get("is_enable") in ("1", "on", "true") else 0
        if not display_name:
            flash("Display name is required", "error")
            return redirect(url_for("admin_ui.labs_edit", pk=pk))
        _update_lab(db_config, pk, display_name, description, is_enable)
        flash("Lab updated", "success")
        return redirect(url_for("admin_ui.labs_index"))

    @bp.post("/labs/<int:pk>/delete")
    @require_grafana_auth(min_role="Editor")
    def labs_delete(pk: int):
        ok, msg = _delete_lab(db_config, pk)
        flash(msg or "Lab deleted", "success" if ok else "error")
        return redirect(url_for("admin_ui.labs_index"))

    # --- Datasource routes ---------------------------------------------------

    @bp.get("/datasources")
    @require_grafana_auth(min_role="Viewer")
    def datasources_index():
        return render_template("datasources_list.html",
                               rows=_list_datasources(db_config))

    @bp.get("/datasources/new")
    @require_grafana_auth(min_role="Editor")
    def datasources_new():
        row = {"is_enable": 1, "type": "mysql"}
        return render_template("datasources_form.html",
                               row=row, mode="new", groups=_distinct_groups(db_config))

    @bp.post("/datasources")
    @require_grafana_auth(min_role="Editor")
    def datasources_create():
        form = request.form.to_dict()
        if not form.get("name") or not form.get("display_name") \
                or not form.get("type") or not form.get("url"):
            flash("name, display_name, type, url are required", "error")
            return render_template("datasources_form.html",
                                   row=form, mode="new",
                                   groups=_distinct_groups(db_config)), 400
        row = {
            "name": form["name"].strip(),
            "display_name": form["display_name"].strip(),
            "type": form["type"],
            "url": form["url"].strip(),
            "database_name": (form.get("database_name") or "").strip() or None,
            "db_user": (form.get("db_user") or "").strip() or None,
            "password_env": (form.get("password_env") or "").strip() or None,
            "lab_group": (form.get("lab_group") or "").strip() or None,
            "is_enable": 1 if form.get("is_enable", "1") in ("1", "on") else 0,
        }
        try:
            _insert_datasource(db_config, row)
        except _IntegrityError:
            flash(f"Datasource name already exists: {row['name']!r}", "error")
            return render_template("datasources_form.html",
                                   row=form, mode="new",
                                   groups=_distinct_groups(db_config)), 409
        flash(f"Created datasource {row['name']}", "success")
        return redirect(url_for("admin_ui.datasources_index"))

    @bp.get("/datasources/<int:pk>/edit")
    @require_grafana_auth(min_role="Editor")
    def datasources_edit(pk: int):
        row = _get_datasource(db_config, pk)
        if not row:
            abort(404)
        return render_template("datasources_form.html",
                               row=row, mode="edit",
                               groups=_distinct_groups(db_config))

    @bp.post("/datasources/<int:pk>")
    @require_grafana_auth(min_role="Editor")
    def datasources_update(pk: int):
        form = request.form.to_dict()
        row = {
            "display_name": (form.get("display_name") or "").strip(),
            "type": form.get("type"),
            "url": (form.get("url") or "").strip(),
            "database_name": (form.get("database_name") or "").strip() or None,
            "db_user": (form.get("db_user") or "").strip() or None,
            "password_env": (form.get("password_env") or "").strip() or None,
            "lab_group": (form.get("lab_group") or "").strip() or None,
            "is_enable": 1 if form.get("is_enable", "1") in ("1", "on") else 0,
        }
        if not row["display_name"] or not row["type"] or not row["url"]:
            flash("display_name, type, url are required", "error")
            return redirect(url_for("admin_ui.datasources_edit", pk=pk))
        _update_datasource(db_config, pk, row)
        flash("Datasource updated", "success")
        return redirect(url_for("admin_ui.datasources_index"))

    @bp.post("/datasources/<int:pk>/delete")
    @require_grafana_auth(min_role="Editor")
    def datasources_delete(pk: int):
        _delete_datasource(db_config, pk)
        flash("Datasource deleted", "success")
        return redirect(url_for("admin_ui.datasources_index"))

    return bp


def start_admin_ui(config: dict, port: int = 9119) -> threading.Thread | None:
    """Start a Flask app exposing both the admin UI and /sd/* endpoints.

    When this is started, sd_endpoints.start_sd_endpoints() should NOT also be
    called — both are registered on the same app here so they share a port.
    """
    from sd_endpoints import create_blueprint as sd_blueprint

    db_config = dict(config.get("postgres") or {})
    if env_host := os.environ.get("POSTGRES_HOST"):
        db_config["host"] = env_host
    if env_pw := os.environ.get("POSTGRES_PASSWORD"):
        db_config["password"] = env_pw
    if not db_config.get("enabled", False):
        logger.warning("Postgres disabled — admin UI will not start")
        return None

    app = Flask("monitor_admin", template_folder=os.path.join(os.path.dirname(__file__), "templates"))
    app.secret_key = os.environ.get("ADMIN_UI_SECRET_KEY", "dev-only-change-me")
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    app.register_blueprint(create_blueprint(db_config))
    app.register_blueprint(sd_blueprint(db_config))

    def run():
        logger.info("Admin UI + SD endpoints listening on 0.0.0.0:%d", port)
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)

    t = threading.Thread(target=run, daemon=True, name="admin-ui")
    t.start()
    return t

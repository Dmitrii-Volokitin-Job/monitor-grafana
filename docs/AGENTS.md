# AGENTS.md — adding & validating a monitored service

> **Audience:** AI agents (Claude Code, Copilot, Cursor) and humans who want a
> copy-pasteable workflow. Read CLAUDE.md first for the broader architecture;
> this file is the focused **"add a new service"** runbook.

## Mental model in 5 lines

1. Targets live in the Postgres `monitored_system` table (NOT in YAML).
2. The exporter rereads the table every cycle (~30 s) and serves Prometheus
   via HTTP-SD at `http://monitor-exporter:9119/sd/<type>`.
3. Three ways to add a row: **admin UI** (humans), **SQL INSERT** (agents in
   CI/scripts), or **HTTP POST `/admin/systems`** (programmatic).
4. The exporter validates the row against `REQUIRED_FIELDS` per `system_type`
   (canonical source: `monitor_exporter/admin_ui.py:53`). Missing required
   fields → the row is rejected at form/API level.
5. Verification = `curl http://localhost:9091/api/v1/query?query=<metric>` —
   probe metrics appear within one probe cycle + Prom HTTP-SD refresh (~60 s).

## Decision tree — "I want to monitor X"

```
Is X reachable over the internet?
├── Yes — does it expose a probe-friendly endpoint?
│   ├── HTTPS health URL                      → system_type=HTTP,  blackbox_module=http_2xx
│   ├── TCP port (no TLS)                     → system_type=TCP,   blackbox_module=tcp_connect
│   ├── ICMP (host pingable)                  → system_type=ICMP
│   ├── TLS cert only                         → system_type=SSL,   needs cert_alias
│   ├── LDAP server                           → system_type=LDAP,  url=ldap[s]://host:port
│   ├── Keycloak realm                        → system_type=KEYCLOAK, needs realm_path
│   ├── MySQL/MariaDB (no auth needed for handshake) → system_type=DATABASE, needs db_host+db_port
│   ├── Postgres (handshake only)             → system_type=POSTGRES
│   ├── Redis                                 → system_type=REDIS
│   ├── MongoDB                               → system_type=MONGODB
│   ├── Elasticsearch                         → system_type=ELASTICSEARCH
│   ├── gRPC service with health-check        → system_type=GRPC, blackbox_module=grpc
│   ├── DNS resolver                          → system_type=DNS, blackbox_module=dns_udp
│   └── App with version endpoint             → system_type=VERSION, needs version_strategy
└── No (private/dev only)
    ├── Add a bundled demo container (see docker-compose.yml `profiles: ["full"]`)
    └── Point the seed row at that container's hostname (e.g. demo-postgres-target:5432)
```

## REQUIRED_FIELDS matrix (canonical: `monitor_exporter/admin_ui.py:53`)

| system_type     | Required fields (besides `system_id` + `display_name` + `system_group`) |
|-----------------|--------------------------------------------------------------------------|
| `HTTP`          | `url`, `blackbox_module`                                                 |
| `TCP`           | `url`                                                                    |
| `ICMP`          | `url`                                                                    |
| `SSL`           | `url`, `cert_alias` *(no `system_group` requirement)*                   |
| `LDAP`          | `url`                                                                    |
| `KEYCLOAK`      | `url`, `realm_path`                                                      |
| `DATABASE`      | `db_host`, `db_port` *(MySQL/MariaDB greeting-packet handshake)*         |
| `POSTGRES`      | `db_host`, `db_port`                                                     |
| `REDIS`         | `db_host`, `db_port`                                                     |
| `MONGODB`       | `db_host`, `db_port`                                                     |
| `ELASTICSEARCH` | `url`                                                                    |
| `GRPC`          | `url`, `blackbox_module`                                                 |
| `DNS`           | `url`, `blackbox_module`                                                 |
| `VERSION`       | `url`, `version_strategy`                                                |

**Allowed `blackbox_module` values:** `http_2xx`, `http_2xx_or_401`, `http_302`, `http_401`, `tcp_connect`, `icmp_ping`, `grpc`, `grpc_plain`, `dns_udp`, `dns_tcp`.

**Allowed `version_strategy` values:** `spring_actuator`, `openapi`, `gateway_version`, `json_version`, `kubernetes`, `camunda`, `monitor_version`.

**Allowed `node_type` values (ICMP rows for node-style hosts):** `SERVER`, `MASTER`, `WORKER`, `EDGE`, `LOAD_BALANCER`, `DB`.

## Method 1 — SQL INSERT (preferred for agents)

Best for: CI scripts, demo seeds, bulk additions. Bypasses the admin UI and writes straight to the table the exporter reads.

```sql
INSERT INTO monitored_system
  (system_id, display_name, system_group, system_type, url, blackbox_module,
   realm_path, db_host, db_port, version_strategy,
   node_id, node_name, lab_group, node_type,
   cert_alias, cert_description, timeout_seconds)
VALUES
  -- HTTP example
  ('my-api', 'My API', 'prod', 'HTTP', 'https://api.example.com/health',
   'http_2xx', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 10),
  -- POSTGRES example
  ('my-db', 'My Postgres', 'prod', 'POSTGRES', 'pg.example.com:5432',
   NULL, NULL, 'pg.example.com', 5432, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 5)
ON CONFLICT (system_id) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  system_group = EXCLUDED.system_group,
  url          = EXCLUDED.url;
```

Run against the running stack:
```bash
docker exec -i monitor-postgres psql -U monitoring -d monitoring < your-rows.sql
```

For permanent demo additions, edit `docker/init-db/07-seed-systems.sql` or `09-seed-new-types-and-datasources.sql` **AND** mirror the same INSERT into `deployments/k8s-helm/dev/monitor-grafana/templates/monitor-db-init.yaml` (the Helm chart re-embeds the seed as a ConfigMap — there is no auto-sync).

## Method 2 — HTTP POST to the admin UI

Best for: programmatic single additions. Requires a Grafana session cookie (admin UI delegates auth to Grafana — see CLAUDE.md "Admin UI requires Grafana basic auth").

```bash
# 1. Get a Grafana session cookie
COOKIE=$(curl -s -c - -X POST 'http://localhost:3030/login' \
  -H 'Content-Type: application/json' \
  -d '{"user":"admin","password":"admin"}' | awk '/grafana_session/{print $NF}')

# 2. POST the new system
curl -X POST 'http://localhost:9119/admin/systems' \
  -H "Cookie: grafana_session=$COOKIE" \
  -d 'system_id=my-api' \
  -d 'display_name=My API' \
  -d 'system_group=prod' \
  -d 'system_type=HTTP' \
  -d 'url=https://api.example.com/health' \
  -d 'blackbox_module=http_2xx' \
  -d 'timeout_seconds=10'
```

## Method 3 — admin UI in browser

`http://localhost:9119/admin/` → "+ New system" → fill the form. Field set adapts to the chosen `system_type` (per `REQUIRED_FIELDS`).

## Verification — proving the new service is actually being probed

Three layers, smallest first. Do all three before claiming "the service is monitored".

### Layer 1: row exists in the catalog
```bash
docker exec monitor-postgres psql -U monitoring -d monitoring \
  -tAc "SELECT system_id, system_type, url FROM monitored_system WHERE system_id='my-api'"
```

### Layer 2: exporter is publishing the target to Prometheus HTTP-SD
```bash
curl -s http://localhost:9119/sd/http | jq '.[] | select(.labels.system_id=="my-api")'
# expect: a single object with targets=[<url>], labels including system_id, system_group, etc.
```

If the row is in the DB but missing here:
- the exporter may not have refreshed (wait ≤30 s), or
- the row failed validation in `_shape_target` (`monitor_exporter/exporter.py`) — check exporter logs.

### Layer 3: probe is producing a non-zero metric
```bash
# HTTP/TCP/ICMP/SSL/gRPC/DNS  — blackbox probes:
curl -s 'http://localhost:9091/api/v1/query?query=probe_success%7Bsystem_id%3D%22my-api%22%7D' | jq

# LDAP/Keycloak/DATABASE/POSTGRES/REDIS/MONGODB/ELASTICSEARCH/VERSION — exporter-emitted:
curl -s 'http://localhost:9091/api/v1/query?query=monitor_database_up%7Bsystem_id%3D%22my-db%22%7D' | jq
```

Expected value: `"1"` (probe succeeded). `"0"` means the target is reachable from the Prometheus / exporter container but failed the actual check (e.g. wrong status code, gRPC health-check not implemented — see grpcb.in note in `tests/live/test_prometheus_live.py`). No data at all means HTTP-SD hasn't refreshed yet or the seed row never reached the exporter.

### Layer 4 (optional but recommended for CI): add a pytest

Pattern in `tests/live/test_prometheus_live.py:test_bundled_db_probe_is_up`:
```python
@pytest.mark.parametrize("system_id", ["my-api", "my-db"])
def test_my_new_service_up(prometheus_url, system_id):
    promql = f'probe_success{{system_id="{system_id}"}} or monitor_database_up{{system_id="{system_id}"}}'
    result = _query(prometheus_url, promql)
    assert result and float(result[0]["value"][1]) == 1.0, \
        f"{system_id}: probe is not UP"
```

Run with `pytest tests/live --live` against a running stack.

## Per-system-type cheat sheet — minimal copy-paste

Each example assumes the row also has `system_id`, `display_name`, `system_group`. Only the type-discriminating fields are shown.

| Type            | Minimal extra fields                                                                  |
|-----------------|---------------------------------------------------------------------------------------|
| HTTP            | `url='https://x/health', blackbox_module='http_2xx'`                                  |
| TCP             | `url='host:port'`                                                                     |
| ICMP            | `url='1.2.3.4'` *(plus optional `node_id`, `node_name`, `node_type`)*                 |
| SSL             | `url='host:443', cert_alias='my-cert'`                                                |
| LDAP            | `url='ldaps://ldap.example.com:636'`                                                  |
| KEYCLOAK        | `url='https://kc.example.com', realm_path='/realms/myrealm'`                          |
| DATABASE        | `db_host='mysql.example.com', db_port=3306`                                           |
| POSTGRES        | `db_host='pg.example.com', db_port=5432`                                              |
| REDIS           | `db_host='redis.example.com', db_port=6379`                                           |
| MONGODB         | `db_host='mongo.example.com', db_port=27017`                                          |
| ELASTICSEARCH   | `url='http://es.example.com:9200/'`                                                   |
| GRPC            | `url='host:9001', blackbox_module='grpc'` *(use `grpc_plain` if not TLS)*             |
| DNS             | `url='1.1.1.1', blackbox_module='dns_udp'`                                            |
| VERSION         | `url='https://app/api/v3/openapi.json', version_strategy='openapi'`                   |

## Pitfalls that catch agents

- **The Helm chart re-embeds the seed as a ConfigMap.** Editing `docker/init-db/*.sql` without mirroring into `deployments/k8s-helm/dev/monitor-grafana/templates/monitor-db-init.yaml` makes the K8s install diverge from docker-compose. No auto-sync.
- **The Postgres data volume persists across `docker compose up -d`** — init SQL only runs on FIRST start (empty volume). To re-load an edited seed: `docker compose stop postgres && docker compose rm -f postgres && docker volume rm monitor-grafana_postgres-data && docker compose up -d postgres`.
- **The `datasource` table is NOT the same as `monitored_system`.** Datasources are Grafana data sources (for dashboards to query); monitored_system rows are probes. Adding a Postgres probe ≠ adding a Postgres datasource.
- **`system_group` is free-text in `monitored_system` but the dashboard variable reads from the `lab` table.** If you add a probe with `system_group='new-lab'` and `lab` doesn't have a row named `'new-lab'`, the dashboard filter dropdown won't list it. Add the `lab` row first: `INSERT INTO lab (name, display_name) VALUES ('new-lab', 'My New Lab');`
- **`COMPOSE_PROFILES=full`** brings up 5 extra demo target containers (Postgres/MySQL/Redis/Mongo/ES). The seed's `demo-a-*` DB rows point at them. The default profile leaves those rows DOWN.
- **Two intentional SSL negatives** (`ssl-demo-expired`, `ssl-demo-selfsigned`) are in the seed *by design* to exercise the SSL alerting path. Do not "fix" them.
- **Probe metrics use different naming conventions:** blackbox probes → `probe_success{job="blackbox_*",system_id=...}`, exporter probes → `monitor_database_up{system_id=...}` (a UNIFIED metric covering POSTGRES/REDIS/MONGODB/ELASTICSEARCH/DATABASE), version → `monitor_system_version_info`, SSL → `ssl_probe_success{cert_alias=...}` (labeled by cert_alias, not system_id — `/sd/ssl` payload only carries cert-specific labels).
- **`grpcb.in:9001` is a TLS-only gRPC echo server that does NOT implement the gRPC health-check protocol.** `probe_success` will always be 0 for it. The live test `test_grpcb_in_grpc_probe_runs` asserts the gRPC handshake completed (duration > 0) rather than insisting on a 1 it can never return.

## Where to find things

| What | File |
|---|---|
| REQUIRED_FIELDS / ALL_FIELDS / SYSTEM_TYPES / BLACKBOX_MODULES / VERSION_STRATEGIES / NODE_TYPES | `monitor_exporter/admin_ui.py:53–86` |
| Probe implementations | `monitor_exporter/exporter.py` |
| HTTP-SD endpoints | `monitor_exporter/sd_endpoints.py` |
| Default seed (canonical) | `docker/init-db/07-seed-systems.sql`, `09-seed-new-types-and-datasources.sql` |
| Helm chart's mirror of the seed | `deployments/k8s-helm/dev/monitor-grafana/templates/monitor-db-init.yaml` |
| Live test patterns | `tests/live/test_prometheus_live.py` (result-pinning), `tests/live/test_targets_live.py` (per-target connectivity) |
| Schema-level regression tests | `tests/db/test_schema.py` (incl. the "no placeholder hosts in seed" guard) |
| Architectural background | `CLAUDE.md`, `docs/runbook.md` |

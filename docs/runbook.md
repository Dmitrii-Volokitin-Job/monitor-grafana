# Operator Runbook

What to do when an alert fires. Each section is keyed off the **alert name** that appears in the email subject and the Alert History dashboard, so you can `Ctrl-F` the subject line to find the right entry.

Generic checklist for any availability alert:
1. Open the **System Health Overview** dashboard, filter by `system_group` from the email
2. Confirm the alert is real (vs. a transient blip — check the timeseries panel)
3. If real: identify scope (one system? whole lab? whole environment?)
4. Notify the system owner if scope is a single system; oncall if scope is bigger

---

## Availability alerts (HTTP / TCP / ICMP / LDAP / Keycloak / Database)

These all share the same 3-tier escalation: WARNING at 10 min → CRITICAL at 60 min → EMERGENCY at 2h.

**Diagnose**
1. From email subject, identify `system_id`. Open **System Health Overview** dashboard, filter by that system.
2. Look at the live `probe_success` / `monitor_*_up` panel — is it consistently 0, or flapping?
3. Open the **Uptime & Performance Statistics** dashboard for trends.
4. Check the underlying probe directly:
   ```bash
   # HTTP probe
   curl "http://localhost:9115/probe?target=<full_url>&module=http_2xx_or_401" | grep probe_success
   # TCP probe
   curl "http://localhost:9115/probe?target=<host:port>&module=tcp_connect" | grep probe_success
   # LDAP / Keycloak / DB
   curl http://localhost:9116/metrics | grep -E "monitor_(ldap|keycloak|database)_up"
   ```

**Resolve**
- Single system down → ping the owner, link them to the system in Grafana
- Multiple systems same group down → likely network/firewall/cluster issue, escalate
- All systems same lab down → escalate to lab admin

**Silence (planned maintenance)**
- One-time: Grafana → Alerting → Silences → match `system_group=<group>` or `system_id=<id>`
- Recurring window: Alerting → Notification policies → Mute timings

---

## SSL alerts

| Alert | Threshold | Action |
|---|---|---|
| Warning | 30 days to expiry | Notify the cert owner; renewal usually takes a week |
| Critical | 7 days to expiry | Escalate; renewal MUST happen now |

**Diagnose**
1. Open **SSL Certificates** dashboard, find the cert.
2. Confirm with: `openssl s_client -connect <host>:443 -servername <host> </dev/null 2>/dev/null | openssl x509 -noout -dates`

**Resolve**
- Renew the cert through the standard process (Let's Encrypt for public; your internal CA for `*.example.com`).
- After renewal, the next ssl_exporter probe (within 1 hour) clears the alert.

> **Demo seed note:** two SSL rows in the demo seed are **intentionally broken**
> as negative tests — `ssl-demo-expired` (`expired.badssl.com:443`, perpetually
> expired) and `ssl-demo-selfsigned` (`self-signed.badssl.com:443`, chain
> validation fails). If you see those two firing in the demo dashboards, that's
> by design — they prove the SSL alerting pipeline works end-to-end. Real
> incident triage should ignore them; they're filed under the
> `ssl-demo-*` system_id prefix.

---

**Diagnose**

**Resolve**
- The alert clears within 30 min of the next analysis showing OK.

---

> A project has ≥1 open vulnerability for over an hour.

**Diagnose**
2. Review each vulnerability — severity, description, "How to fix"

**Resolve**
- Fix the vulnerability and re-scan; or

---

**Diagnose**

**Resolve**
- CI broken → fix the build (typical: token expired in `.gitlab-ci.yml`, rotate)

---

## Smoke test fails after deploy

```bash
./scripts/smoke-test.sh
# or against a remote deploy:
GRAFANA=https://grafana.example.com \
EXPORTER=https://prometheus.example.com/api/v1/query?query=up \
TRIGGER=https://e2e-trigger.example.com \
./scripts/smoke-test.sh
```

Each `✗` line tells you exactly which component is broken. Cross-reference with the troubleshooting sections above.

---

## Admin UI (port 9119) — service & lab CRUD

The admin UI replaces hand-editing `config/targets/*.yml`. It writes the
`monitored_system` table; the exporter rereads the table every check cycle,
and Prometheus discovers blackbox/SSL/node targets via HTTP-SD (`/sd/<type>`)
on the same port.

### Logging in

The admin UI has no login screen of its own — it trusts the inbound
`grafana_session` cookie. Workflow:

1. Open Grafana at `http://localhost:3000` (docker-compose) or your
   production URL and log in (`admin` / your `GF_SECURITY_ADMIN_PASSWORD`).
2. Open `http://localhost:9119/admin/` in the same browser. The UI calls
   Grafana's `/api/user` with your cookie; if it returns Admin/Editor, you
   can write. Viewer = read-only.
3. If you land on the Grafana login page, your cookie expired — log in again.

Decision is cached 60 s per cookie, so you won't hit Grafana on every page
click.

### Adding a lab

1. Click **Labs** in the nav → **+ New lab**.
2. **Name** is the stable key used as `system_group` / `lab_group` on systems
   and as the value of `${lab_group}` in dashboards. Choose kebab-case
   (`prod-frankfurt`, `dev-us-east`); don't change it later.
3. **Display name** is what humans see in the lab dropdown.
4. The new lab appears in every dashboard's lab dropdown on next refresh
   (variables run a SQL query against the `lab` table on each load).

### Adding a service

1. Click **Systems** → **+ New system** → pick the type (HTTP / TCP / ICMP /
   SSL / LDAP / KEYCLOAK / DATABASE / VERSION / NODE).
2. Fill the type-specific form. Required fields are enforced server-side.
3. After save: Prometheus picks up the target within ~30 s (HTTP-SD refresh
   interval), and the exporter starts probing on its next check cycle.

### "My new service isn't appearing in Prometheus"

Walk this checklist top-down:

1. `curl http://localhost:9119/sd/<type> | jq` — is the row present here? If
   not, it's not enabled or the `system_type` doesn't match (e.g. you added
   a Database to `/sd/http` instead of `/sd/tcp`).
2. `curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | select(.labels.system_id=="<your-id>")'` —
   Prometheus side. Empty? Wait 30 s (HTTP-SD refresh), then re-check.
3. `curl 'http://localhost:9090/api/v1/query?query=probe_success{system_id="<your-id>"}'` —
   metric arriving? If you see `up=0`, the *target* is unreachable but the
   probe is running.
4. `docker compose logs monitor-exporter | tail -50` — boot errors or
   DB connection failures.

### Exporter pod down → Prometheus loses all dynamic targets

`http_sd_configs` queries the exporter on every refresh. If the exporter is
unreachable, Prometheus drops the target set after one refresh window (~30 s).
Symptom: a sudden cliff in the System Health Overview, all `probe_success`
series simultaneously absent.

Mitigation in production: the Helm Deployment includes a readiness probe on
`/sd/healthz`, so Kubernetes doesn't route traffic to a half-started pod, and
Prometheus continues using the last good response between scrapes. In
docker-compose: `docker compose restart monitor-exporter`.

### What each `url` column actually means per type

- HTTP / TCP / ICMP / SSL / NODE: `url` is the literal target string given to
  the upstream probe (URL, host:port, IP).
- LDAP: an `ldap://` or `ldaps://` URI.
- KEYCLOAK: just the base URL; `realm_path` lives in its own column.
- DATABASE: `url` mirrors `db_host:db_port` for display — the actual probe
  uses the dedicated `db_host` / `db_port` columns.
- VERSION: the `url` is probed and `version_strategy` picks which JSON path
  holds the version string.

If a field doesn't match the form template, check the per-type partial under
`monitor_exporter/templates/_form_fields_<type>.html`.

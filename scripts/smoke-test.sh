#!/usr/bin/env bash
# Smoke-test the Monitor monitoring stack end-to-end.
# Exits 0 if every endpoint is healthy, non-zero otherwise.
#
# Usage:
#   ./scripts/smoke-test.sh                                           # local docker-compose
#   GRAFANA=https://grafana.example.com \
#   PROMETHEUS=http://prom-host:9090 \
#   EXPORTER=http://exporter-host:9116 \
#   ./scripts/smoke-test.sh                                           # remote

set -u
PASS=0
FAIL=0

# Defaults match docker-compose host port mappings (not the in-cluster ports).
GRAFANA=${GRAFANA:-http://localhost:3030}
PROMETHEUS=${PROMETHEUS:-http://localhost:9091}
EXPORTER=${EXPORTER:-http://localhost:9116}
EXPORTER_SD=${EXPORTER_SD:-http://localhost:9119}
BLACKBOX=${BLACKBOX:-http://localhost:9115}
SSL_EXPORTER=${SSL_EXPORTER:-http://localhost:9117}

green() { printf "\e[32m✓\e[0m  %s\n" "$1"; PASS=$((PASS+1)); }
red()   { printf "\e[31m✗\e[0m  %s\n" "$1"; FAIL=$((FAIL+1)); }

# Generic HTTP 200 check (optional body-pattern match).
check_http() {
    local label=$1 url=$2 grep_pattern=${3:-}
    local out
    out=$(curl -sk --max-time 10 -w '|%{http_code}' "$url" 2>/dev/null) || { red "$label  unreachable: $url"; return; }
    local code=${out##*|}
    local body=${out%|*}
    if [[ $code != 200 ]]; then
        red "$label  HTTP $code from $url"
        return
    fi
    if [[ -n "$grep_pattern" && ! "$body" =~ $grep_pattern ]]; then
        red "$label  HTTP 200 but body missing pattern '$grep_pattern'"
        return
    fi
    green "$label  ($url)"
}

echo "═══ Monitor — smoke test ═══"
echo

# --- Core stack ---
check_http "Grafana"               "$GRAFANA/api/health"              '"database"'
check_http "Prometheus"            "$PROMETHEUS/-/healthy"
check_http "Prometheus targets"    "$PROMETHEUS/api/v1/targets"       '"status":"success"'
check_http "Blackbox exporter"     "$BLACKBOX/probe?target=http://localhost&module=http_2xx" 'probe_success'
check_http "SSL exporter"          "$SSL_EXPORTER/probe?target=google.com:443" 'ssl_'

# --- Monitor Exporter ---
check_http "Exporter / metrics"            "$EXPORTER/metrics"  'monitor_ldap_up'
check_http "Exporter / keycloak metrics"   "$EXPORTER/metrics"  'monitor_keycloak_up'
check_http "Exporter / database metrics"   "$EXPORTER/metrics"  'monitor_database_up'
check_http "Exporter / version detection"  "$EXPORTER/metrics"  'monitor_system_version'
check_http "Exporter / SD http"            "$EXPORTER_SD/sd/http"  '"system_id"'

# --- Grafana datasources (uses default admin/admin — override with GF_USER/GF_PASS) ---
GF_USER=${GF_USER:-admin}
GF_PASS=${GF_PASS:-admin}

check_grafana_ds() {
    local uid=$1
    local code body
    body=$(curl -sk --max-time 10 -u "$GF_USER:$GF_PASS" -w '|%{http_code}' "$GRAFANA/api/datasources/uid/$uid/health" 2>/dev/null) || { red "DS $uid  unreachable"; return; }
    code=${body##*|}
    body=${body%|*}
    if [[ $code == 200 && "$body" =~ \"status\":\"OK\" ]]; then
        green "DS $uid  health OK"
    elif [[ $code == 200 ]]; then
        red "DS $uid  reachable but unhealthy: $body"
    else
        red "DS $uid  HTTP $code"
    fi
}

check_grafana_ds monitor-prometheus
check_grafana_ds monitor-postgres

echo
echo "─────────────────────────"
printf "%d passed, %d failed\n" "$PASS" "$FAIL"
exit $((FAIL > 0 ? 1 : 0))

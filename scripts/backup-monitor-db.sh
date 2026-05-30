#!/usr/bin/env bash
# Back up the Monitor Postgres schema (monitored systems, alert state,
# health check history, email log, maintenance windows, labs, datasources).
# Suitable for cron / systemd timer. Output is gzipped SQL.
#
# Usage:
#   ./scripts/backup-monitor-db.sh                       # writes to ./backups/monitoring-<ts>.sql.gz
#   BACKUP_DIR=/srv/backups ./scripts/backup-monitor-db.sh
#   RETENTION_DAYS=14       ./scripts/backup-monitor-db.sh    # prune older
#
# Tables backed up (all of schema 'public'):
#   - monitored_system        (target inventory; regenerated on exporter restart)
#   - lab                     (lab / environment groups)
#   - datasource              (per-type datasource credentials)
#   - health_check_history    (per-check result rows)
#   - alert_state             (current alert status per system)
#   - email_log               (sent / queued / failed alert emails)
#   - maintenance_window      (manual silence windows)
#   - maintenance_window_system (M:N membership)
#
# Required env (defaults match docker-compose):
#   DB_HOST     (default: localhost)
#   DB_PORT     (default: 5433 — host port mapped by docker-compose; use 5432 inside cluster)
#   DB_USER     (default: monitoring)
#   DB_PASSWORD (default: monitoring)
#   DB_NAME     (default: monitoring)

set -euo pipefail

DB_HOST=${DB_HOST:-localhost}
DB_PORT=${DB_PORT:-5433}
DB_USER=${DB_USER:-monitoring}
DB_PASSWORD=${DB_PASSWORD:-monitoring}
DB_NAME=${DB_NAME:-monitoring}

BACKUP_DIR=${BACKUP_DIR:-./backups}
RETENTION_DAYS=${RETENTION_DAYS:-30}

mkdir -p "$BACKUP_DIR"
TS=$(date +%Y%m%d-%H%M%S)
OUT="$BACKUP_DIR/${DB_NAME}-${TS}.sql.gz"

echo "▶ Dumping $DB_NAME from $DB_HOST:$DB_PORT to $OUT"

# pg_dump flags:
#   --format=plain  → SQL script (greppable, replayable with psql)
#   --no-owner      → portable across users (e.g. restoring into a different role)
#   --no-privileges → strip GRANT/REVOKE; restore site decides ACLs
#   --clean --if-exists → makes the dump idempotent: drops objects before recreating
PGPASSWORD="$DB_PASSWORD" pg_dump \
    --host="$DB_HOST" \
    --port="$DB_PORT" \
    --username="$DB_USER" \
    --dbname="$DB_NAME" \
    --format=plain \
    --no-owner \
    --no-privileges \
    --clean \
    --if-exists \
    | gzip -9 > "$OUT"

SIZE=$(du -h "$OUT" | cut -f1)
echo "✔ Backup complete: $OUT ($SIZE)"

# Prune older backups
if [[ $RETENTION_DAYS -gt 0 ]]; then
    PRUNED=$(find "$BACKUP_DIR" -maxdepth 1 -name "${DB_NAME}-*.sql.gz" -mtime "+$RETENTION_DAYS" -print -delete | wc -l)
    if [[ $PRUNED -gt 0 ]]; then
        echo "✔ Pruned $PRUNED backups older than $RETENTION_DAYS days"
    fi
fi

# Quick integrity sanity check — gunzip the dump to /dev/null
if ! gunzip -t "$OUT"; then
    echo "✗ gzip integrity check FAILED for $OUT" >&2
    exit 1
fi

echo "✔ Integrity check OK"

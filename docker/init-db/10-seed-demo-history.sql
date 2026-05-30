-- 10-seed-demo-history.sql (Postgres dialect)
--
-- Backfills synthetic history so the dashboards have something to render on
-- first boot (otherwise every "Recent …", "Trends", "Last 7d uptime" panel
-- shows "No data").
--
-- NOT idempotent: the INSERTs do not carry ON CONFLICT clauses because the
-- timestamps are synthetic. Re-running on a populated DB will duplicate every
-- row. Postgres only runs scripts in /docker-entrypoint-initdb.d/ on FIRST
-- container start (empty data dir), so this is safe in normal docker-compose
-- usage. If you ever need to re-seed: `docker compose down -v` first.

-- ============================================================================
-- 1. Health check history (7 days × 30-min cadence × N systems)
-- ============================================================================
INSERT INTO health_check_history (system_id, check_timestamp, status, http_status_code, response_time_ms, error_message)
WITH RECURSIVE offsets AS (
    SELECT 0 AS n
    UNION ALL
    SELECT n + 1 FROM offsets WHERE n < 335
)
SELECT
    s.id,
    NOW() - make_interval(mins => o.n * 30) AS check_timestamp,
    CASE WHEN (s.id * 7 + o.n) % 47 IN (0, 1) THEN 'DOWN' ELSE 'UP' END AS status,
    CASE
        WHEN (s.id * 7 + o.n) % 47 IN (0, 1) THEN 503
        WHEN s.system_type IN ('HTTP', 'KEYCLOAK', 'ELASTICSEARCH') THEN 200
        ELSE NULL
    END AS http_status_code,
    GREATEST(1, ROUND(50 + ((s.id * 17 + o.n) % 300))::int) AS response_time_ms,
    CASE WHEN (s.id * 7 + o.n) % 47 IN (0, 1)
         THEN 'demo: connection timed out'
         ELSE NULL
    END AS error_message
FROM monitored_system s
CROSS JOIN offsets o
WHERE s.is_enable = 1;


-- ============================================================================
-- 2. alert_state — one row per system showing its current status
-- ============================================================================
INSERT INTO alert_state (system_id, current_status, current_severity, down_since, alert_count)
SELECT
    s.id,
    CASE
        WHEN s.system_id IN ('demo-a-mariadb', 'demo-b-mongo') THEN 'DOWN'
        ELSE 'UP'
    END AS current_status,
    CASE
        WHEN s.system_id = 'demo-a-mariadb' THEN 'CRITICAL'
        WHEN s.system_id = 'demo-b-mongo'   THEN 'WARNING'
        ELSE NULL
    END AS current_severity,
    CASE
        WHEN s.system_id = 'demo-a-mariadb' THEN NOW() - INTERVAL '2 hours'
        WHEN s.system_id = 'demo-b-mongo'   THEN NOW() - INTERVAL '15 minutes'
        ELSE NULL
    END AS down_since,
    CASE
        WHEN s.system_id = 'demo-a-mariadb' THEN 3
        WHEN s.system_id = 'demo-b-mongo'   THEN 1
        ELSE 0
    END AS alert_count
FROM monitored_system s
WHERE s.is_enable = 1;


-- ============================================================================
-- 3. email_log — last 5 alert emails
-- ============================================================================
INSERT INTO email_log (related_system_id, sent_timestamp, subject, to_recipients, email_type, status) VALUES
    ((SELECT id FROM monitored_system WHERE system_id = 'demo-a-mariadb'),
     NOW() - INTERVAL '5 minutes',
     '[FIRING] [CRITICAL] Demo Lab A - MariaDB - demo-lab-a',
     'alerts@example.com', 'alert', 'SENT'),
    ((SELECT id FROM monitored_system WHERE system_id = 'demo-a-mariadb'),
     NOW() - INTERVAL '65 minutes',
     '[FIRING] [WARNING] Demo Lab A - MariaDB - demo-lab-a',
     'alerts@example.com', 'alert', 'SENT'),
    ((SELECT id FROM monitored_system WHERE system_id = 'demo-b-mongo'),
     NOW() - INTERVAL '10 minutes',
     '[FIRING] [WARNING] Demo Lab B - MongoDB - demo-lab-b',
     'alerts@example.com', 'alert', 'SENT'),
    (NULL,
     NOW() - INTERVAL '6 hours',
     '[RESOLVED] Demo Lab A - Sample API - demo-lab-a',
     'alerts@example.com', 'resolution', 'SENT'),
    (NULL,
     NOW() - INTERVAL '1 day',
     '[FIRING] [WARNING] Demo Lab B - Edge Node (ICMP) - demo-lab-b',
     'alerts@example.com', 'alert', 'SENT');


-- ============================================================================
-- 4. maintenance_window — 1 active + 2 upcoming entries
-- ============================================================================
WITH inserted_windows AS (
    INSERT INTO maintenance_window (title, maintenance_type, start_time, end_time)
    VALUES
      ('Postgres minor version upgrade', 'scheduled',
       NOW() - INTERVAL '30 minutes', NOW() + INTERVAL '90 minutes'),
      ('Quarterly OS patching — Demo Lab A', 'scheduled',
       NOW() + INTERVAL '2 days',  NOW() + INTERVAL '2 days 4 hours'),
      ('Certificate rotation — Demo Lab B', 'scheduled',
       NOW() + INTERVAL '5 days',  NOW() + INTERVAL '5 days 2 hours')
    RETURNING id, title
)
-- Link each window to the relevant systems (active=mariadb sample, others=spread across the lab)
INSERT INTO maintenance_window_system (maintenance_window_id, system_id)
SELECT w.id, ms.id
FROM inserted_windows w
JOIN monitored_system ms ON
  (w.title = 'Postgres minor version upgrade' AND ms.system_id IN ('demo-a-mariadb','demo-a-postgres')) OR
  (w.title = 'Quarterly OS patching — Demo Lab A' AND ms.system_group = 'demo-lab-a') OR
  (w.title = 'Certificate rotation — Demo Lab B' AND ms.system_id IN ('ssl-demo-b','demo-b-web'));





-- ============================================================================
-- Sanity counts
-- ============================================================================
SELECT 'health_check_history' AS tbl, COUNT(*) AS rows_inserted FROM health_check_history
UNION ALL SELECT 'alert_state',    COUNT(*) FROM alert_state
UNION ALL SELECT 'email_log',      COUNT(*) FROM email_log
UNION ALL SELECT 'maintenance_window', COUNT(*) FROM maintenance_window

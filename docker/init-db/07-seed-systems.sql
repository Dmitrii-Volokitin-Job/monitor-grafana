-- Seed monitored_system + lab tables with DEMO data.
--
-- This file is loaded by docker-entrypoint-initdb.d on first Postgres startup
-- (empty data dir only). The admin UI on port 9119 is the long-term editor —
-- this seed exists so a fresh `docker-compose up -d` produces a UI with two
-- example labs and one example system per supported type, useful for poking
-- at the stack without configuring anything.
--
-- Two labs: demo-lab-a and demo-lab-b.
-- One example per type: HTTP, TCP, ICMP, SSL, LDAP, KEYCLOAK, DATABASE,
-- VERSION — repeated per lab → 16 rows total.

-- Labs (the lab table is created in 06-extend-monitored-system.sql, which
-- runs before this file alphabetically — so the table exists by now).
INSERT INTO lab (name, display_name, description) VALUES
  ('demo-lab-a', 'Demo Lab A — Primary',
   'Open-source example lab. Replace with your real environment in the admin UI.'),
  ('demo-lab-b', 'Demo Lab B — Secondary',
   'Open-source example lab. Replace with your real environment in the admin UI.')
ON CONFLICT (name) DO NOTHING;

INSERT INTO monitored_system
  (system_id, display_name, system_group, system_type, url, blackbox_module,
   realm_path, db_host, db_port, version_strategy,
   node_id, node_name, lab_group, node_type,
   cert_alias, cert_description, timeout_seconds)
VALUES
  -- ---------------- Demo Lab A ----------------
  ('demo-a-api',       'Demo Lab A — Sample API',        'demo-lab-a', 'HTTP',     'https://httpbin.org/status/200', 'http_2xx',    NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 10),
  ('demo-a-tcp',       'Demo Lab A — Public DNS',        'demo-lab-a', 'TCP',      'dns.google:53',                  'tcp_connect', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 5),
  ('demo-a-node',      'Demo Lab A — Edge Node (ICMP)',  'demo-lab-a', 'ICMP',     '1.1.1.1',                         NULL,         NULL, NULL, NULL, NULL, 'demo-a-node', 'Demo Lab A — Edge Node', 'demo-lab-a', 'SERVER', NULL, NULL, 5),
  ('ssl-demo-a',       'Demo Lab A — Web cert',          'demo-lab-a', 'SSL',      'github.com:443',                  NULL,         NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 'demo-a-cert', 'Demo Lab A — Web cert (github.com)', 30),
  ('demo-a-ldap',      'Demo Lab A — Public LDAP',       'demo-lab-a', 'LDAP',     'ldap://ldap.forumsys.com:389',    NULL,         NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 10),
  ('demo-a-keycloak',  'Demo Lab A — Keycloak (public demo)', 'demo-lab-a', 'KEYCLOAK', 'https://www.keycloak.org',    NULL,         '/',              NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 10),
  ('demo-a-mariadb',   'Demo Lab A — MySQL (bundled)',   'demo-lab-a', 'DATABASE', 'demo-mysql-target:3306',          NULL,         NULL, 'demo-mysql-target', 3306, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 5),
  ('ver-demo-a',       'Demo Lab A — App version',       'demo-lab-a', 'VERSION',  'https://petstore3.swagger.io/api/v3/openapi.json',         NULL,         NULL, NULL, NULL, 'openapi', NULL, NULL, NULL, NULL, NULL, NULL, 10),

  -- ---------------- Demo Lab B ----------------
  ('demo-b-web',       'Demo Lab B — Grafana Play',      'demo-lab-b', 'HTTP',     'https://play.grafana.org/',       'http_2xx',    NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 10),
  ('demo-b-tcp',       'Demo Lab B — Public DNS',        'demo-lab-b', 'TCP',      'one.one.one.one:53',              'tcp_connect', NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 5),
  ('demo-b-node',      'Demo Lab B — Edge Node (ICMP)',  'demo-lab-b', 'ICMP',     '8.8.8.8',                         NULL,         NULL, NULL, NULL, NULL, 'demo-b-node', 'Demo Lab B — Edge Node', 'demo-lab-b', 'SERVER', NULL, NULL, 5),
  ('ssl-demo-b',       'Demo Lab B — Web cert',          'demo-lab-b', 'SSL',      'github.com:443',                  NULL,         NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 'demo-b-cert', 'Demo Lab B — Web cert', 30),
  ('demo-b-ldap',      'Demo Lab B — Public LDAP',       'demo-lab-b', 'LDAP',     'ldap://ldap.forumsys.com:389',    NULL,         NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 10),
  ('demo-b-keycloak',  'Demo Lab B — Keycloak (public demo)', 'demo-lab-b', 'KEYCLOAK', 'https://www.keycloak.org',    NULL,         '/',              NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 10),
  ('demo-b-mariadb',   'Demo Lab B — MySQL (bundled)',   'demo-lab-b', 'DATABASE', 'demo-mysql-target:3306',          NULL,         NULL, 'demo-mysql-target', 3306, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 5),
  ('ver-demo-b',       'Demo Lab B — App version',       'demo-lab-b', 'VERSION',  'https://petstore3.swagger.io/api/v3/openapi.json',         NULL,         NULL, NULL, NULL, 'openapi', NULL, NULL, NULL, NULL, NULL, NULL, 10),

  -- ---------------- SSL negative tests (badssl.com) ----------------
  -- These are INTENTIONALLY broken so the SSL expiry / chain-validation
  -- alerting can be observed in the demo dashboards. See docs/runbook.md.
  ('ssl-demo-expired',    'SSL negative — expired cert',     'demo-lab-a', 'SSL', 'expired.badssl.com:443',      NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 'badssl-expired',    'expired.badssl.com (intentional negative test)',    30),
  ('ssl-demo-selfsigned', 'SSL negative — self-signed',      'demo-lab-b', 'SSL', 'self-signed.badssl.com:443',  NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 'badssl-selfsigned', 'self-signed.badssl.com (intentional negative test)', 30)
ON CONFLICT (system_id) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  system_group = EXCLUDED.system_group,
  system_type  = EXCLUDED.system_type,
  url          = EXCLUDED.url;

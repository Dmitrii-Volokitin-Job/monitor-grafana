-- 09-seed-new-types-and-datasources.sql
--
-- Demo entries for the new probe types added in 08:
--   POSTGRES, REDIS, MONGODB, ELASTICSEARCH, GRPC, DNS
-- One per demo lab so the admin UI shows working examples.
--
-- Also seeds a few example Grafana datasources for the DB Observability
-- dashboard so the variable dropdown isn't empty on first boot.

INSERT INTO monitored_system
  (system_id, display_name, system_group, system_type, url, blackbox_module,
   db_host, db_port,
   timeout_seconds)
VALUES
  -- Lab A points at REAL bundled containers (started via COMPOSE_PROFILES=full
  -- in docker-compose.yml, or the demo-targets.yaml chart template). These
  -- probes return UP when the full profile is running.
  ('demo-a-postgres', 'Demo Lab A — Postgres (bundled)',     'demo-lab-a', 'POSTGRES',      'demo-postgres-target:5432',     NULL,           'demo-postgres-target', 5432, 5),
  ('demo-a-redis',    'Demo Lab A — Redis (bundled)',        'demo-lab-a', 'REDIS',         'demo-redis-target:6379',        NULL,           'demo-redis-target',    6379, 5),
  ('demo-a-mongo',    'Demo Lab A — MongoDB (bundled)',      'demo-lab-a', 'MONGODB',       'demo-mongo-target:27017',       NULL,           'demo-mongo-target',   27017, 5),
  ('demo-a-es',       'Demo Lab A — Elasticsearch (bundled)','demo-lab-a', 'ELASTICSEARCH', 'http://demo-es-target:9200/',   NULL,           NULL,                   NULL, 10),
  -- Lab B also points at the bundled containers so EVERY example probes a
  -- real service. Same upstream, different system_id/labels — both labs
  -- show real UP data. Alerting demo is driven by the intentional negatives
  -- (ssl-demo-expired, ssl-demo-selfsigned) instead of placeholder DOWN.
  ('demo-b-postgres', 'Demo Lab B — Postgres (bundled)',     'demo-lab-b', 'POSTGRES',      'demo-postgres-target:5432',     NULL,           'demo-postgres-target', 5432, 5),
  ('demo-b-redis',    'Demo Lab B — Redis (bundled)',        'demo-lab-b', 'REDIS',         'demo-redis-target:6379',        NULL,           'demo-redis-target',    6379, 5),
  ('demo-b-mongo',    'Demo Lab B — MongoDB (bundled)',      'demo-lab-b', 'MONGODB',       'demo-mongo-target:27017',       NULL,           'demo-mongo-target',   27017, 5),
  ('demo-b-es',       'Demo Lab B — Elasticsearch (bundled)','demo-lab-b', 'ELASTICSEARCH', 'http://demo-es-target:9200/',   NULL,           NULL,                   NULL, 10),
  ('demo-a-grpc',     'Demo Lab A — gRPC echo',  'demo-lab-a', 'GRPC',          'grpcb.in:9001',                   'grpc_plain', NULL,        NULL, 10),
  ('demo-b-grpc',     'Demo Lab B — gRPC echo',  'demo-lab-b', 'GRPC',          'grpcb.in:9001',                   'grpc_plain', NULL,        NULL, 10),
  ('demo-a-dns',      'Demo Lab A — DNS resolver','demo-lab-a', 'DNS',           '1.1.1.1',                       'dns_udp',      NULL,        NULL, 5),
  ('demo-b-dns',      'Demo Lab B — DNS resolver','demo-lab-b', 'DNS',           '8.8.8.8',                       'dns_udp',      NULL,        NULL, 5)
ON CONFLICT (system_id) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  system_group = EXCLUDED.system_group,
  url          = EXCLUDED.url;

-- Demo Grafana datasources. The DB Observability dashboard variable lists
-- entries from this table; admin UI /admin/datasources is the editor; the
-- exporter's datasource_sync thread reconciles them into Grafana via the
-- HTTP API on each cycle.
INSERT INTO datasource
  (name, display_name, type, url, database_name, db_user, password_env, lab_group)
VALUES
  ('monitor-postgres-demo-a','Postgres — Demo Lab A','postgres', 'pg.demo-lab-a.example.com:5432', 'app',  'monitor_ro', 'GF_DS_POSTGRES_DEMO_A_PASSWORD',  'demo-lab-a'),
  ('monitor-postgres-demo-b','Postgres — Demo Lab B','postgres', 'pg.demo-lab-b.example.com:5432', 'app',  'monitor_ro', 'GF_DS_POSTGRES_DEMO_B_PASSWORD',  'demo-lab-b'),
  ('monitor-mysql-demo-a',   'MySQL — Demo Lab A',   'mysql',    'mysql.demo-lab-a.example.com:3306', 'app',  'monitor_ro', 'GF_DS_MYSQL_DEMO_A_PASSWORD',     'demo-lab-a'),
  ('monitor-mysql-demo-b',   'MySQL — Demo Lab B',   'mysql',    'mysql.demo-lab-b.example.com:3306', 'app',  'monitor_ro', 'GF_DS_MYSQL_DEMO_B_PASSWORD',     'demo-lab-b')
ON CONFLICT (name) DO NOTHING;

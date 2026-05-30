-- 06-extend-monitored-system.sql (Postgres dialect)
--
-- Extends monitored_system to hold every parameter previously scattered across
-- config/targets/*.yml and monitor_exporter/config.yml. After this migration
-- the DB becomes the single source of truth; the admin UI writes here, the
-- exporter reads from here, and Prometheus discovers targets via HTTP-SD over
-- the new endpoints in sd_endpoints.py.

ALTER TABLE monitored_system
  ADD COLUMN IF NOT EXISTS description          VARCHAR(500),
  ADD COLUMN IF NOT EXISTS health_check_path    VARCHAR(200),
  ADD COLUMN IF NOT EXISTS expected_status_code INT,
  ADD COLUMN IF NOT EXISTS timeout_seconds      INT          DEFAULT 30,
  ADD COLUMN IF NOT EXISTS priority             INT          DEFAULT 5,
  ADD COLUMN IF NOT EXISTS blackbox_module      VARCHAR(50),
  ADD COLUMN IF NOT EXISTS version_strategy     VARCHAR(50),
  ADD COLUMN IF NOT EXISTS realm_path           VARCHAR(200),
  ADD COLUMN IF NOT EXISTS db_host              VARCHAR(200),
  ADD COLUMN IF NOT EXISTS db_port              INT,
  ADD COLUMN IF NOT EXISTS node_id              VARCHAR(100),
  ADD COLUMN IF NOT EXISTS node_name            VARCHAR(200),
  ADD COLUMN IF NOT EXISTS lab_group            VARCHAR(100),
  ADD COLUMN IF NOT EXISTS node_type            VARCHAR(50),
  ADD COLUMN IF NOT EXISTS cert_alias           VARCHAR(100),
  ADD COLUMN IF NOT EXISTS cert_description     VARCHAR(200);

CREATE INDEX IF NOT EXISTS idx_type_enable
  ON monitored_system (system_type, is_enable);

CREATE TABLE IF NOT EXISTS lab (
    id           BIGSERIAL    PRIMARY KEY,
    name         VARCHAR(100) NOT NULL UNIQUE,
    display_name VARCHAR(200) NOT NULL,
    description  VARCHAR(500),
    is_enable    SMALLINT     DEFAULT 1,
    created_at   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

DROP TRIGGER IF EXISTS trg_lab_updated ON lab;
CREATE TRIGGER trg_lab_updated BEFORE UPDATE ON lab
  FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- Seed lab with every distinct group already present in monitored_system,
-- so the dropdowns are populated and existing rows stay associated.
INSERT INTO lab (name, display_name)
SELECT DISTINCT g, g FROM (
    SELECT system_group AS g FROM monitored_system WHERE system_group <> ''
    UNION
    SELECT lab_group    AS g FROM monitored_system WHERE lab_group IS NOT NULL AND lab_group <> ''
) groups
WHERE g IS NOT NULL AND g <> ''
ON CONFLICT (name) DO NOTHING;

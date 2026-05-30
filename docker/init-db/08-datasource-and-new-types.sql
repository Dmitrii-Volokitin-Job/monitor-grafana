-- 08-datasource-and-new-types.sql (Postgres dialect)
--
-- Adds the `datasource` table — Grafana data-source catalog editable from
-- the admin UI. A background sync (datasource_sync.py) reconciles this
-- table against Grafana's /api/datasources every cycle so adding a row
-- here makes the datasource appear in Grafana without any provisioning
-- file edits.

CREATE TABLE IF NOT EXISTS datasource (
    id            BIGSERIAL    PRIMARY KEY,
    name          VARCHAR(100) NOT NULL UNIQUE,
    display_name  VARCHAR(200) NOT NULL,
    type          VARCHAR(50)  NOT NULL,
    url           VARCHAR(500) NOT NULL,
    database_name VARCHAR(200),
    db_user       VARCHAR(100),
    -- Convention: store an env-var name here, not the secret itself.
    password_env  VARCHAR(100),
    lab_group     VARCHAR(100),
    is_enable     SMALLINT     DEFAULT 1,
    created_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_datasource_type ON datasource (type);

DROP TRIGGER IF EXISTS trg_datasource_updated ON datasource;
CREATE TRIGGER trg_datasource_updated BEFORE UPDATE ON datasource
  FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

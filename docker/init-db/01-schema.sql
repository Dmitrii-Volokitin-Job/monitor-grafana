-- Monitoring schema for the Grafana stack (Postgres dialect).
-- The Postgres image creates the database from POSTGRES_DB before running
-- this script, so there is no CREATE DATABASE / USE here.

CREATE TABLE IF NOT EXISTS monitored_system (
    id BIGSERIAL PRIMARY KEY,
    system_id VARCHAR(100) NOT NULL UNIQUE,
    display_name VARCHAR(255) NOT NULL,
    system_group VARCHAR(100) NOT NULL,
    system_type VARCHAR(50) DEFAULT 'HTTP',
    url VARCHAR(500),
    is_enable SMALLINT DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_system_group ON monitored_system (system_group);

CREATE TABLE IF NOT EXISTS health_check_history (
    id BIGSERIAL PRIMARY KEY,
    system_id BIGINT NOT NULL REFERENCES monitored_system(id),
    check_timestamp TIMESTAMP NOT NULL,
    status VARCHAR(20) NOT NULL,
    http_status_code INT,
    response_time_ms BIGINT,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_hch_system_id ON health_check_history (system_id);
CREATE INDEX IF NOT EXISTS idx_hch_check_ts ON health_check_history (check_timestamp);
CREATE INDEX IF NOT EXISTS idx_hch_status ON health_check_history (status);

CREATE TABLE IF NOT EXISTS alert_state (
    id BIGSERIAL PRIMARY KEY,
    system_id BIGINT NOT NULL REFERENCES monitored_system(id),
    current_status VARCHAR(20) NOT NULL DEFAULT 'UP',
    current_severity VARCHAR(20),
    down_since TIMESTAMP,
    last_status_change TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    alert_count INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_as_system_id ON alert_state (system_id);
CREATE INDEX IF NOT EXISTS idx_as_status ON alert_state (current_status);

CREATE TABLE IF NOT EXISTS email_log (
    id BIGSERIAL PRIMARY KEY,
    related_system_id BIGINT REFERENCES monitored_system(id),
    sent_timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    subject VARCHAR(500),
    to_recipients VARCHAR(1000),
    email_type VARCHAR(50),
    status VARCHAR(20) DEFAULT 'SENT',
    retry_count INT DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_el_timestamp ON email_log (sent_timestamp);
CREATE INDEX IF NOT EXISTS idx_el_system ON email_log (related_system_id);
CREATE INDEX IF NOT EXISTS idx_el_type ON email_log (email_type);

CREATE TABLE IF NOT EXISTS maintenance_window (
    id BIGSERIAL PRIMARY KEY,
    title VARCHAR(255),
    maintenance_type VARCHAR(100),
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP NOT NULL,
    is_cancelled SMALLINT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_mw_time ON maintenance_window (start_time, end_time);

CREATE TABLE IF NOT EXISTS maintenance_window_system (
    id BIGSERIAL PRIMARY KEY,
    maintenance_window_id BIGINT NOT NULL REFERENCES maintenance_window(id),
    system_id BIGINT NOT NULL REFERENCES monitored_system(id)
);
CREATE INDEX IF NOT EXISTS idx_mws_window ON maintenance_window_system (maintenance_window_id);
CREATE INDEX IF NOT EXISTS idx_mws_system ON maintenance_window_system (system_id);

-- Trigger to mimic MariaDB's ON UPDATE CURRENT_TIMESTAMP for monitored_system + alert_state.
CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at = CURRENT_TIMESTAMP;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_monitored_system_updated ON monitored_system;
CREATE TRIGGER trg_monitored_system_updated BEFORE UPDATE ON monitored_system
  FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

DROP TRIGGER IF EXISTS trg_alert_state_updated ON alert_state;
CREATE TRIGGER trg_alert_state_updated BEFORE UPDATE ON alert_state
  FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

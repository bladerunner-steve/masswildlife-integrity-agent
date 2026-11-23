-- 002_run_state.sql
-- Creates masswildlife.agent_run_state: one row per agent run, so the next run can read its incremental
-- window with SELECT (window_start = last successful window_end of the same env, capped at 24 h + grace).
-- The agent INSERTs a row with status 'running' and UPDATEs it when the run closes. No DELETE is ever needed.
-- prod and test runs are kept apart by `env`, so test runs never move the production window.
-- Idempotent (CREATE TABLE IF NOT EXISTS). Run as a MySQL admin.
-- AI-assisted (Claude); reviewed by the author before running.

CREATE TABLE IF NOT EXISTS masswildlife.agent_run_state (
  run_id          CHAR(36)    NOT NULL,
  env             VARCHAR(8)  NOT NULL COMMENT 'prod | test',
  dry_run         TINYINT(1)  NOT NULL DEFAULT 0,
  window_start    DATETIME(6) NOT NULL COMMENT 'UTC',
  window_end      DATETIME(6) NOT NULL COMMENT 'UTC',
  status          VARCHAR(16) NOT NULL COMMENT 'running | success | partial | failed',
  gap_seconds     INT         NULL     COMMENT 'uncovered time since the previous successful window_end (flagged, never silently widened)',
  started_at      DATETIME(6) NOT NULL,
  finished_at     DATETIME(6) NULL,
  seal_hash       CHAR(64)    NULL,
  prev_seal_hash  CHAR(64)    NULL,
  PRIMARY KEY (run_id),
  KEY ix_env_status_end (env, status, window_end)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

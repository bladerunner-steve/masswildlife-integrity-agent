-- 001_provenance_index.sql
-- Creates masswildlife.provenance_index: the local equivalent of the Aurora provenance index.
-- One row per receipt (steps 0-5 = PR0-PR5) plus one row for the run seal (step 6, step_type 'seal'),
-- written by the agent (INSERT) only after the object is safely in the WORM vault.
-- The verifier may record its verdict with UPDATE on the verification_* columns.
-- UNTRUSTED CONVENIENCE: the verifier never relies on this table, only on the vault, trusted keys and anchors.
-- Idempotent (CREATE TABLE IF NOT EXISTS). Run as a MySQL admin; the agent account (claude) cannot run DDL.
-- AI-assisted (Claude); reviewed by the author before running.

CREATE TABLE IF NOT EXISTS masswildlife.provenance_index (
  run_id              CHAR(36)         NOT NULL COMMENT 'UUID of the run',
  step                TINYINT UNSIGNED NOT NULL COMMENT '0-5 = PR0-PR5, 6 = run seal',
  env                 VARCHAR(8)       NOT NULL COMMENT 'prod | test (vault the object lives in)',
  step_type           VARCHAR(32)      NOT NULL COMMENT 'plan | request | response | filtering | db_update | completion | seal',
  module              VARCHAR(64)      NOT NULL COMMENT 'e.g. M3:filter',
  agent_id            CHAR(64)         NULL     COMMENT 'measurement digest (hex); NULL for the seal',
  receipt_timestamp   DATETIME(6)      NOT NULL COMMENT 'receipt body timestamp, UTC',
  receipt_hash        CHAR(64)         NOT NULL COMMENT 'SHA-256(JCS(body)), hex',
  signature           VARCHAR(128)     NOT NULL COMMENT 'Ed25519 signature (hex or base64)',
  notary_key_id       CHAR(16)         NOT NULL,
  vault_key           VARCHAR(255)     NOT NULL COMMENT 'object key in the vault',
  verification_status VARCHAR(32)      NOT NULL DEFAULT 'unverified'
                                       COMMENT 'unverified | VERIFIED WITHIN SCOPE | INSUFFICIENT EVIDENCE | VERIFICATION FAILED',
  verification_config VARCHAR(32)      NULL     COMMENT 'crypto | crypto+policy | crypto+policy+evidence',
  verified_at         DATETIME(6)      NULL,
  indexed_at          DATETIME(6)      NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (run_id, step),
  UNIQUE KEY uq_receipt_hash (receipt_hash),
  KEY ix_env_time (env, receipt_timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

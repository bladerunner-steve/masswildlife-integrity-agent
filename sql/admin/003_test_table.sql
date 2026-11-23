-- 003_test_table.sql
-- Creates masswildlife.inaturalist_test with the same structure (columns + PRIMARY KEY (id)) as
-- masswildlife.inaturalist, for --db test runs and the evaluation harness. Copies structure only, no rows.
-- Because claude cannot DELETE or TRUNCATE, test data is reset by an admin with 900_reset_test.sql.
-- Idempotent (CREATE TABLE IF NOT EXISTS). Run as a MySQL admin, after the author's rebuild of inaturalist.
-- AI-assisted (Claude); reviewed by the author before running.

CREATE TABLE IF NOT EXISTS masswildlife.inaturalist_test LIKE masswildlife.inaturalist;

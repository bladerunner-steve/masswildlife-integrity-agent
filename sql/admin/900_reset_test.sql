-- 900_reset_test.sql
-- DESTRUCTIVE, TEST DATA ONLY. Empties masswildlife.inaturalist_test and removes env='test' rows from
-- agent_run_state and provenance_index, so test and evaluation runs start clean.
-- It never touches masswildlife.inaturalist or any env='prod' row.
-- The agent account (claude) cannot run this (no DELETE/TRUNCATE). Only the author runs it, as admin.
-- Safe to re-run. It does not reset the test vault on disk: delete vault-test/ separately if needed.
-- AI-assisted (Claude); reviewed by the author before running.

TRUNCATE TABLE masswildlife.inaturalist_test;
DELETE FROM masswildlife.agent_run_state  WHERE env = 'test';
DELETE FROM masswildlife.provenance_index WHERE env = 'test';

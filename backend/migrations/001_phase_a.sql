-- Migration 001_phase_a.sql — additive only, safe to re-run.
-- Adds data-quality columns + review/ops tables. No drops, no renames,
-- no backfills that overwrite existing values.
-- Rehearsed on leadpilot_test (restored from backup) before production.

-- Companies: quality + dedup identifiers (all nullable)
ALTER TABLE companies ADD COLUMN IF NOT EXISTS company_type VARCHAR(50);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS completeness FLOAT;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS verified BOOLEAN;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS last_verified TIMESTAMP;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS normalized_name VARCHAR(500);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS normalized_domain VARCHAR(255);
ALTER TABLE companies ADD COLUMN IF NOT EXISTS notes TEXT;
CREATE INDEX IF NOT EXISTS ix_companies_normalized_name ON companies (normalized_name);
CREATE INDEX IF NOT EXISTS ix_companies_normalized_domain ON companies (normalized_domain);

-- Contacts: normalized identifiers (nullable)
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS normalized_email VARCHAR(255);
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS normalized_phone VARCHAR(50);
CREATE INDEX IF NOT EXISTS ix_contacts_normalized_email ON contacts (normalized_email);
CREATE INDEX IF NOT EXISTS ix_contacts_normalized_phone ON contacts (normalized_phone);

-- Duplicate review queue (new table)
CREATE TABLE IF NOT EXISTS duplicate_candidates (
    id SERIAL PRIMARY KEY,
    company_a_id INTEGER NOT NULL REFERENCES companies(id),
    company_b_id INTEGER NOT NULL REFERENCES companies(id),
    match_type VARCHAR(50) NOT NULL,
    confidence FLOAT NOT NULL DEFAULT 0.0,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    CONSTRAINT uq_dup_candidate_pair UNIQUE (company_a_id, company_b_id, match_type)
);
CREATE INDEX IF NOT EXISTS ix_dup_status ON duplicate_candidates (status);

-- Crawl job history (new table)
CREATE TABLE IF NOT EXISTS crawl_jobs (
    id SERIAL PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    url VARCHAR(2048) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    pages_visited INTEGER NOT NULL DEFAULT 0,
    companies_discovered INTEGER NOT NULL DEFAULT 0,
    records_created INTEGER NOT NULL DEFAULT 0,
    records_updated INTEGER NOT NULL DEFAULT 0,
    duplicates_flagged INTEGER NOT NULL DEFAULT 0,
    errors JSON NOT NULL DEFAULT '[]',
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_crawl_jobs_status ON crawl_jobs (status);

-- Auto-send schedule controls (table already exists; add columns only)
ALTER TABLE auto_send_state ADD COLUMN IF NOT EXISTS enabled BOOLEAN;
ALTER TABLE auto_send_state ADD COLUMN IF NOT EXISTS daily_limit INTEGER;

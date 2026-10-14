# Recovery & rollback

## Database backup
- File: `backups/leadpilot_2026-10-11.dump` (PostgreSQL custom format, ~1 MB).
- Covers all 14 tables (3,871 companies at backup time). Verified restorable
  (`pg_restore --list` shows every table-data section).

## Full restore (loses changes after backup time — last resort)
```powershell
# Stop the backend first (frees connections)
docker exec leadpilot-ai-postgres psql -U postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='leadpilot' AND pid <> pg_backend_pid();"
docker exec leadpilot-ai-postgres psql -U postgres -c "DROP DATABASE leadpilot;"
docker exec leadpilot-ai-postgres psql -U postgres -c "CREATE DATABASE leadpilot;"
docker cp backups/leadpilot_2026-10-11.dump leadpilot-ai-postgres:/tmp/restore.dump
docker exec leadpilot-ai-postgres pg_restore -U postgres -d leadpilot /tmp/restore.dump
```

## Backups (newest first)

- `backups/pre_crm_upgrade_20261014.dump` — taken 2026-10-14 BEFORE the CRM
  upgrade (contact_items/suppressions/merge_audit tables, lifecycle +
  consent + template columns). Restore this to return to pre-CRM state.
- `backups/pre_upgrade_20261014.dump`, `backups/leadpilot_2026-10-11.dump` —
  earlier snapshots (same restore procedure as below).

## Rolling back the CRM upgrade (keeps all data)

Every CRM change is additive (new tables + nullable columns). To undo:

```sql
DROP TABLE IF EXISTS contact_items;
DROP TABLE IF EXISTS suppressions;
DROP TABLE IF EXISTS merge_audit;
ALTER TABLE companies DROP COLUMN IF EXISTS lifecycle_status;
ALTER TABLE companies DROP COLUMN IF EXISTS merged_into_id;
ALTER TABLE contacts DROP COLUMN IF EXISTS consent_status;
ALTER TABLE contacts DROP COLUMN IF EXISTS whatsapp_eligible;
ALTER TABLE outreach DROP COLUMN IF EXISTS template_name;
ALTER TABLE outreach DROP COLUMN IF EXISTS template_language;
ALTER TABLE outreach DROP COLUMN IF EXISTS consent_evidence;
ALTER TABLE outreach DROP COLUMN IF EXISTS campaign_id;
ALTER TABLE google_accounts DROP COLUMN IF EXISTS last_verified_at;
ALTER TABLE google_accounts DROP COLUMN IF EXISTS access_ok;
```

Then restart the backend with the previous code. Merged/excluded flags live
in the dropped columns/tables, so flagged rows simply reappear as active —
no data loss either way.

## Rolling back the Phase-A migration (keeps all data)
Every change in `backend/migrations/001_phase_a.sql` is additive. To undo:
```sql
DROP TABLE IF EXISTS duplicate_candidates;
DROP TABLE IF EXISTS crawl_jobs;
ALTER TABLE companies DROP COLUMN IF EXISTS company_type;
ALTER TABLE companies DROP COLUMN IF EXISTS completeness;
ALTER TABLE companies DROP COLUMN IF EXISTS verified;
ALTER TABLE companies DROP COLUMN IF EXISTS last_verified;
ALTER TABLE companies DROP COLUMN IF EXISTS normalized_name;
ALTER TABLE companies DROP COLUMN IF EXISTS normalized_domain;
ALTER TABLE companies DROP COLUMN IF EXISTS notes;
ALTER TABLE contacts DROP COLUMN IF EXISTS normalized_email;
ALTER TABLE contacts DROP COLUMN IF EXISTS normalized_phone;
ALTER TABLE auto_send_state DROP COLUMN IF EXISTS enabled;
ALTER TABLE auto_send_state DROP COLUMN IF EXISTS daily_limit;
```
Then restart the backend with the previous code (no code references removed
columns except new features, which simply stop working).

## Code rollback
No version control is configured in this workspace. Before further phases,
recommended: `git init`, commit the current tree, then branch per phase.

## Stuck crawls
- A source stuck in CRAWLING with a dead thread: reset to PENDING in DB and
  re-trigger — idempotent saves skip existing rows, gaps are filled.
- Never delete companies/sources to "fix" a stuck crawl.

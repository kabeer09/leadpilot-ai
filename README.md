# LeadPilot AI — New Look Impex B2B Lead Automation

Manufacturer/exporter outreach for metal urlis, diyas, lanterns, copper &
brass handicrafts, giftware and home décor (Moradabad, India).

## Start (Windows PowerShell)

Full guide: [`docs/setup_windows.md`](docs/setup_windows.md).

```powershell
docker start leadpilot-ai-postgres
cd backend;  python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
cd frontend; node node_modules\vite\bin\vite.js --port 5173 --strictPort
```

Open http://localhost:5173 · API docs http://localhost:8001/docs

## Configure

| Step | Where |
|---|---|
| Gmail OAuth connect + test send | Settings → Google Login (or paste client in UI) |
| WhatsApp official API | [`docs/whatsapp_setup.md`](docs/whatsapp_setup.md) |
| Daily auto-send + follow-up toggles | Settings → Automatic email schedule |
| Env placeholders | [`.env.example`](.env.example) |

## Safely activate each workflow

1. **Crawl** — Dashboard → Add Website → crawl (polite, resumable, idempotent).
2. **Review** — Companies (filters, duplicates, exclusions) → Leads (eligible/sent/follow-up filters).
3. **Approve batch** — Leads bulk panel or Automation → New batch → **Preview first**, then Approve & send (20/day default, Gmail limits respected).
4. **Follow-ups** — automatic 24h in-thread email (scheduler, fail-closed) + WhatsApp queue for approved numbers only.
5. **Replies** — automatic check (hourly scheduler, Sync buttons, n8n Gmail Replies). Replies stop follow-ups; bounces/unsubscribes suppress.
6. **n8n** — import `n8n/*.json` (see [`n8n/README.md`](n8n/README.md)). Built-in scheduler covers replies + email follow-ups without n8n.

**Do not send live batches until the previewed recipients + subject/body are approved.**

## Key API groups

- Companies: `GET /api/companies` (+`/{id}`, `/{id}/contacts`), crawl `POST /api/sources/{id}/crawl`
- Leads: `GET /api/leads` (+`/{id}`, `/{id}/timeline`)
- Outreach: `GET /api/outreach/summary|/sent`, `GET|POST /api/outreach/new-batch/*`, `GET /api/followups/due|/email-due`, `POST /api/outreach/{id}/follow-up`
- Webhooks: `POST /api/webhooks/gmail|/gmail/reply|/gmail/bounce`, `POST /api/webhooks/whatsapp|/incoming|/status`
- Analytics: `GET /api/analytics/overview|/trends`, health `GET /api/automation/health`
- Data quality: `GET /api/data-quality/duplicates|/merges|/suppressions`, `POST /api/data-quality/deduplicate/*|/exclusions/*`

## Safety & recovery

- Backups before every upgrade: [`docs/setup_windows.md`](docs/setup_windows.md) §4.
- Rollback (additive-only migrations): [`docs/rollback.md`](docs/rollback.md).
- Tests: `cd backend; python -m pytest tests/ -q -W ignore::DeprecationWarning -p no:cacheprovider` (231 passing).

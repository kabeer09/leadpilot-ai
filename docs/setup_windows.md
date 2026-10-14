# LeadPilot AI — Windows PowerShell setup

## 1. Prerequisites

- Windows 10/11, Docker Desktop, Python 3.12, Node.js 18+
- Ollama (optional, for AI emails): https://ollama.ai — then `ollama pull gemma3:1b`

## 2. Start the stack (in order)

```powershell
# 1. Docker first (PostgreSQL lives here)
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
# wait until this succeeds:
docker ps
docker start leadpilot-ai-postgres

# 2. Backend (new terminal)
cd "C:\Users\KABEER AHMED\OneDrive\Desktop\leadpilot-ai\backend"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
# check: http://localhost:8001/health  ->  {"status":"ok",...}

# 3. Frontend (new terminal)
cd "C:\Users\KABEER AHMED\OneDrive\Desktop\leadpilot-ai\frontend"
npm install   # first time only
node node_modules\vite\bin\vite.js --port 5173 --strictPort
# open: http://localhost:5173
```

If Docker Desktop keeps dying (low memory): close heavy apps, then
`docker start leadpilot-ai-postgres` + restart the backend. Saved data is
safe inside the `leadpilot-ai-postgres` container volume.

## 3. First-time wiring

1. Settings → paste Google OAuth client → **Connect with Google**.
2. Settings → **Send test** to your own address.
3. Dashboard → add an exhibitor directory → crawl.
4. Leads → filter **Eligible to send** → Preview → approve a small batch.
5. Automation → review follow-ups due, suppressions, duplicates.

## 4. Backups (before every upgrade)

```powershell
docker exec leadpilot-ai-postgres pg_dump -U postgres -d leadpilot -F c -f /tmp/backup.dump
docker cp leadpilot-ai-postgres:/tmp/backup.dump "C:\Users\KABEER AHMED\OneDrive\Desktop\leadpilot-ai\backups\backup.dump"
```

Rollback: see `docs/rollback.md`. Migrations in this project are
additive-only (new tables/nullable columns) — downgrade = restore backup.

## 5. n8n (optional but recommended)

- Set env `LEADPILOT_API_URL=http://host.docker.internal:8001`
- Import JSONs from `n8n/` (see `n8n/README.md`), connect Gmail OAuth2 +
  WhatsApp credentials, activate in the documented order.
- The built-in scheduler already does reply polling + 24h email
  follow-ups; n8n adds Gmail sending for queued items + WhatsApp delivery.

## 6. Tests

```powershell
cd "C:\Users\KABEER AHMED\OneDrive\Desktop\leadpilot-ai\backend"
python -m pytest tests/ -q -W ignore::DeprecationWarning -p no:cacheprovider
```

## 7. Safety rules the system enforces

- Nothing sends without Gmail connected + your explicit approval
  (except scheduler toggles you switched on in Settings).
- Replies, bounces, opt-outs and suppressions stop follow-ups automatically.
- WhatsApp needs per-contact human approval — scraped numbers never
  auto-send.
- Merges/exclusions never delete rows and never resend messages.
- A Gmail API `send` means "accepted by Gmail", never "delivered".

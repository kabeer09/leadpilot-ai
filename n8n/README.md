# Phase 5 — n8n + Gmail setup

Two import-ready workflows (n8n → Workflows → Import from file):

| File | Purpose |
|---|---|
| `gmail_outreach.json` | Polls `GET /api/outreach/ready` every 5 min → sends via Gmail → acks `POST /api/outreach/{id}/sent` (or `/failed`) |
| `gmail_replies.json` | Polls Gmail for inbound mail → posts to `POST /api/webhooks/gmail` (matched by sender email) |
| `whatsapp_followup.json` | Polls `GET /api/outreach/ready?channel=WHATSAPP` every 15 min → sends via WhatsApp Business Cloud → acks sent/failed |
| `email_followup.json` | Calls `POST /api/outreach/followups/bulk` every 6h → auto 24h follow-ups in-thread → refreshes `GET /api/outreach/summary` |
| `whatsapp_eligibility.json` | Triages phone contacts every 12h → eligible / needs-approval / ineligible (sends nothing) |
| `whatsapp_sender.json` | Sends ONLY backend-queued eligible WhatsApp via official Business Cloud API → acks sent/failed |
| `whatsapp_incoming.json` | Official webhook → `POST /api/webhooks/whatsapp/incoming` (reply routing, opt-out flags) |
| `whatsapp_delivery.json` | Provider receipts → `POST /api/webhooks/whatsapp/status` (sent/delivered/read/failed) |
| `whatsapp_scheduler.json` | Calls `POST /api/outreach/followups/scan` every 6h (eligible contacts only) |
| `whatsapp_sync.json` | Hourly health + summary poll for the Automation dashboard |

## 1. Prerequisites

- LeadPilot backend reachable from n8n. If n8n runs in Docker on the same
  machine, the API URL is `http://host.docker.internal:8001`.
- A Gmail account for sending (Google Workspace or personal).

## 2. Environment variable

In n8n (Docker: `-e LEADPILOT_API_URL=...`, or n8n → Settings → Variables):

```
LEADPILOT_API_URL=http://host.docker.internal:8001
```

## 3. Gmail credential (OAuth2)

1. In n8n, open Credentials → New → **Gmail OAuth2 API**.
2. Create a Google Cloud project, enable the **Gmail API**, create an
   OAuth client (Desktop or Web), and paste client ID/secret.
3. Connect the sending Gmail account.
4. In each imported workflow, open the Gmail node(s) and select this
   credential (replaces `REPLACE_WITH_YOUR_GMAIL_CREDENTIAL_ID`).

## 4. Activate in order

1. Activate **LeadPilot Gmail Outreach**.
2. Activate **LeadPilot Gmail Replies**.
3. Activate **LeadPilot WhatsApp Follow-up** (needs a WhatsApp Business
   Cloud credential; see note in the workflow about templates).
4. Pick ONE 24h email follow-up driver (both are fail-closed, max 1 per lead):
   - built-in scheduler (default ON: `FOLLOWUP_AUTO_SEND_ENABLED`, hourly), or
   - **LeadPilot Email Follow-up (24h)** n8n workflow (every 6h).
5. In LeadPilot (Leads → lead detail): Generate → Validate → **Queue email**.
   The next poll picks it up, sends it, and the dashboard flips to SENT.
6. 24h after the email (and only if no reply), a polite follow-up sends
   automatically inside the original Gmail thread. Manual triggers:
   `POST /api/outreach/followups/scan` (WhatsApp queue),
   `POST /api/outreach/followups/bulk` (email send),
   per-lead: `POST /api/outreach/{lead_id}/follow-up`.
   Due list: `GET /api/outreach/followups/email-due`
   (note: `GET /api/outreach/followups/due` is the WhatsApp queue).

## 5. Contract reference (backend)

- `GET /api/outreach/ready` → `[{id, lead_id, channel, to_email, company_name, subject, message}]`
  (only PENDING items with a recipient, subject and body)
- `POST /api/outreach/{id}/sent` `{message_id?}` → idempotent ack, lead → `EMAIL_SENT`, activity logged
- `POST /api/outreach/{id}/failed` `{error}` → lead activity `OUTREACH_FAILED`
- `POST /api/webhooks/gmail` `{outreach_id?|from_address, event_type: reply|bounce|delivery, subject?, body?}`
  → reply sets outreach + lead to `REPLIED` with activity

## 6. Local test without Gmail

Queue an email in the app, then simulate n8n with curl:

```bash
curl http://localhost:8001/api/outreach/ready
curl -X POST http://localhost:8001/api/outreach/1/sent -H "Content-Type: application/json" -d "{\"message_id\":\"test-123\"}"
curl -X POST http://localhost:8001/api/webhooks/gmail -H "Content-Type: application/json" -d "{\"event_type\":\"reply\",\"from_address\":\"customer@example.com\",\"subject\":\"Re: ...\",\"body\":\"We are interested\"}"
```

## 7. Safety notes

- Sending is human-gated: nothing sends until a user queues it.
- The sent-ack is idempotent; duplicate Gmail deliveries never double-count.
- Replies never execute anything — they only flip status + log activity.
  AI classification + auto-follow-up arrive in later phases.

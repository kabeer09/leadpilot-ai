# WhatsApp Business setup (official API only)

LeadPilot sends WhatsApp ONLY through Meta's official WhatsApp Business
Platform/Cloud API (or a supported official provider). Browser/Web
automation is not used anywhere.

## 1. Create the app (Meta)

1. Go to https://developers.facebook.com → create an app → add the
   **WhatsApp** product.
2. In WhatsApp → API Setup you get a test number, a Phone Number ID and a
   temporary access token. For production, add a real business number and
   generate a permanent system-user token.
3. Note your **Phone Number ID** and **access token**.

## 2. Connect n8n

1. n8n → Credentials → New → **WhatsApp API** (Business Cloud).
2. Paste the access token (and business account details n8n asks for).
3. Import the six workflows from `n8n/`:
   - `whatsapp_eligibility.json` — triage only, sends nothing
   - `whatsapp_sender.json` — sends ONLY backend-queued eligible items
   - `whatsapp_incoming.json` — reply listener → `/api/webhooks/whatsapp/incoming`
   - `whatsapp_delivery.json` — receipts → `/api/webhooks/whatsapp/status`
   - `whatsapp_scheduler.json` — due follow-up scan trigger
   - `whatsapp_sync.json` — hourly dashboard sync
4. In the sender/incoming/delivery workflows, select your WhatsApp
   credential (replaces `REPLACE_WITH_YOUR_WHATSAPP_CREDENTIAL_ID`).
5. Set env `LEADPILOT_API_URL` (Docker: `http://host.docker.internal:8001`).

## 3. Templates and the 24h window

- Inside Meta's 24-hour customer-service window you may send free-form
  follow-ups (what the sender workflow does by default).
- Outside the window Meta requires a **pre-approved template**. Create one
  in WhatsApp Manager → Message Templates, then set `template_name` /
  `template_language` on the queued outreach (stored per message) and switch
  the sender node to the template operation.

## 4. Eligibility = human approval first

A scraped phone number is NEVER assumed eligible:

1. Crawler stores the number + exact source URL (`consent_status` empty).
2. Eligibility workflow marks it `needs-approval`.
3. A human approves: lead detail page → **Approve WhatsApp**, or
   `POST /api/data-quality/whatsapp/approve/{contact_id}` with evidence.
4. Only then (`whatsapp_eligible=true`, not opted-out/suppressed) can the
   backend queue it. `STOP`/opt-out replies auto-revoke eligibility.

## 5. Webhook URL (for inbound + receipts)

Expose n8n or point Meta's webhook at your n8n instance URL; the WhatsApp
Trigger nodes handle verification when configured per n8n docs. LeadPilot
itself only receives the mapped events — it never sends automatic replies.

# Gmail + Google login setup (OAuth)

LeadPilot sends email **directly through your Gmail** (no n8n required) and
polls it for replies. You need a Google OAuth client — 10 minutes, one time.

## 1. Create the OAuth client

1. [Google Cloud Console](https://console.cloud.google.com/) → new project.
2. APIs & Services → Library → enable **Gmail API** (and **Calendar API**
   for meeting booking).
3. OAuth consent screen → **External** → app name `LeadPilot AI` →
   scopes: `gmail.send`, `gmail.readonly`, `calendar` →
   add **your Gmail address** as a test user → save.
4. Credentials → Create Credentials → **OAuth client ID** → **Web application**.
5. Authorized redirect URI (exact):
   ```
   http://localhost:8001/api/auth/google/callback
   ```
   (Production: use your `https://` backend URL + same path.)
6. Copy the **client ID** and **client secret**.

## 2. Backend env (backend/.env)

```
GOOGLE_CLIENT_ID=xxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=xxxx
GOOGLE_REDIRECT_URI=http://localhost:8001/api/auth/google/callback
```

Restart the backend.

## 3. Connect in the app

Settings → **Google Login** → Connect with Google → pick your Gmail →
Allow. The dashboard shows the connected address. Tokens are stored
server-side (refresh token in PostgreSQL, never sent to the browser).

## 4. Send + follow up

- Leads → **Send email to all**: custom subject/body with
  `{company_name} {country} {city} {website} {contact_email}` →
  Preview (dry run) → Send via Gmail. Top scores first, 2s between sends,
  unsubscribed/replied/bounced leads skipped automatically.
- **Check replies** polls Gmail, matches message threads to sent outreach,
  and auto-classifies (INTERESTED / MEETING_REQUEST / UNSUBSCRIBE / …).
- 24h WhatsApp follow-ups and meeting booking work as before.

## 5. Limits & safety

- Gmail: ~500 sends/day (Workspace: 2,000). `BULK_SEND_LIMIT` (default 50)
  caps one run; `DAILY_SEND_CAP` + kill switch guard the n8n queue too.
- Sending is always human-gated (Preview → Send). Replies only flip
  status + log activity. Unsubscribes suppress all future outreach.
- Test user mode: only accounts you add as test users can connect until
  the OAuth app is published.

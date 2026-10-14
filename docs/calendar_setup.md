# Google Calendar + Meet setup (Phase 8)

LeadPilot books meetings via the Google Calendar REST API — no extra
Python packages needed. You supply a Google OAuth **refresh token**;
the backend exchanges it for short-lived access tokens automatically.

## 1. Google Cloud project

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → create a project.
2. APIs & Services → Library → enable **Google Calendar API**.
3. APIs & Services → OAuth consent screen → External (or Internal for
   Workspace) → add scope `.../auth/calendar` → add yourself as test user.
4. Credentials → Create Credentials → **OAuth client ID** → Desktop app.
   Note the client ID and client secret.

## 2. Get a refresh token (one-time, 2 minutes)

1. Open [OAuth 2.0 Playground](https://developers.google.com/oauthplayground/).
2. Settings (gear) → check *Use your own OAuth credentials* → paste your
   client ID + secret.
3. Step 1: select **Calendar API v3 → `https://www.googleapis.com/auth/calendar`** → Authorize.
4. Step 2: Exchange authorization code for tokens.
5. Copy the **Refresh token**.

## 3. Backend env (backend/.env)

```
GOOGLE_CALENDAR_ENABLED=true
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REFRESH_TOKEN=your-refresh-token
```

Restart the backend. `GET /api/meetings/slots` and the availability check
now verify against your real calendar.

## 4. Flow in the app

1. A reply classified `MEETING_REQUEST` sets the lead to `MEETING_PROPOSED`
   with a `MEETING_ACTION_NEEDED` activity (Phase 7 does this automatically).
2. Lead detail → propose a slot → `POST /api/meetings/propose`.
3. **Book on Google Calendar** → `POST /api/meetings/{id}/book` creates the
   Calendar event **with a Google Meet link**, sets the meeting CONFIRMED
   and the lead `MEETING_BOOKED`.
4. Cancel deletes the calendar event too.

Without credentials, booking returns HTTP 409 with this guide's pointer —
proposing still works, so the pipeline is fully demonstrable offline.

## 5. Safety notes

- The refresh token is a password: keep it in `.env` (git-ignored), never in code.
- The playground token inherits the test-user consent; for production,
  publish the OAuth app / move to a service account flow.
- Attendees receive a standard Google Calendar invite from your account.

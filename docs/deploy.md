# Deploy to a cloud server (24/7, faster network, no laptop-sleep risk)

Run the whole stack on a VPS (e.g. Hetzner CX32 ~€11/mo, 4 vCPU / 8 GB —
recommended; minimum CX22 2 vCPU / 4 GB ~€5). Same code, same Docker Compose.

## 1. Create the server
- Ubuntu 24.04, add your SSH key, note the public IP (call it `SERVER-IP`).
- Open firewall ports `22`, `5173`, `8001`, `5678` (or put a domain + HTTPS
  in front later — optional).

## 2. Install Docker on the server
```bash
ssh root@SERVER-IP
curl -fsSL https://get.docker.com | sh
```

## 3. Copy the project
```bash
# from your laptop:
scp -r C:/Users/<you>/OneDrive/Desktop/leadpilot-ai root@SERVER-IP:/opt/
```

## 4. Configure (server)
```bash
cd /opt/leadpilot-ai
cp backend/.env.example backend/.env   # if no .env yet
nano backend/.env
```
Set inside `.env`:
```
DATABASE_URL=postgresql://postgres:postgres@postgres:5432/leadpilot
FRONTEND_URL=http://SERVER-IP:5173
GOOGLE_REDIRECT_URI=http://SERVER-IP:8001/api/auth/google/callback
GOOGLE_CLIENT_ID=...            # same OAuth client as laptop (or a new one)
GOOGLE_CLIENT_SECRET=...
```
Then in Google Cloud Console add one more Authorized redirect URI:
`http://SERVER-IP:8001/api/auth/google/callback`

## 5. Start everything
```bash
docker compose up -d --build
docker compose exec ollama ollama pull gemma3:1b   # one-time AI download
docker compose ps   # all services Up
curl http://localhost:8001/health
```
Open in your browser:
- App: `http://SERVER-IP:5173`
- API docs: `http://SERVER-IP:8001/docs`
- n8n: `http://SERVER-IP:5678`

## 6. (Optional) Move your laptop data to the server
```powershell
# on laptop:
docker exec leadpilot-ai-postgres pg_dump -U postgres -d leadpilot -F c -f /tmp/move.dump
docker cp leadpilot-ai-postgres:/tmp/move.dump ./move.dump
scp ./move.dump root@SERVER-IP:/opt/
```
```bash
# on server:
docker cp /opt/move.dump $(docker compose ps -q postgres):/tmp/move.dump
docker compose exec postgres pg_restore -U postgres -d leadpilot /tmp/move.dump
```

## 7. Realistic expectations
- Crawl speed is politeness-bound (~8–10s per page), so a 2,000-company
  fair still takes hours — but it runs **unattended, overnight, immune to
  laptop sleep**, on a faster, stable network. Roughly 2–3× wall-clock
  faster than a laptop that sleeps.
- Gmail limits are per Gmail account, unchanged by the server.
- Keep `backend/.env` secret (never commit it anywhere).

## 8. Update later
```bash
cd /opt/leadpilot-ai
# copy changed files over (or git pull), then:
docker compose up -d --build backend frontend
```

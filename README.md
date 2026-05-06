# Exam Audio Relay

Self-hostable web app for delivering exam audio with **time-windowed, single-link, server-mediated streaming**.

Teachers upload audio files, schedule a listening window, and share a unique student URL. Outside the
window or after revocation, the link returns nothing useful: the backend re-validates each page-view
and each byte streamed and never exposes the underlying file path.

## What it does

- Multi-teacher support (`superadmin` + `teacher` roles)
- Upload `.mp3 / .wav / .m4a / .ogg` (max size configurable)
- Create exam sessions with start/end datetime, optional max access count, optional notes
- "Start now for 15/30/45/60/90/120 minutes" convenience option
- Generates a cryptographically random session token and a public link `/s/{token}`
- Streaming endpoint `/stream/{token}` validates: token, time window, revocation, teacher active,
  optional max access count — and supports HTTP `Range` (206 Partial Content) for audio scrubbing
- Access logs (page views, stream starts, denied events) per session
- Manual revocation by the owner teacher (or any session by superadmin)
- The "last active superadmin" cannot be disabled or demoted

## Security model and limitations

What this app **does** prevent:
- Reuse of old links after the session window closes or after revocation
- Direct file URLs (audio is never served from a public static directory)
- One teacher seeing another teacher's files / sessions / logs
- CSRF on authenticated `POST/PUT/DELETE` requests under `/admin` (per-session token)

What this app **does not** prevent:
- A student recording the audio with screen/audio capture, an external phone, etc.
- A determined technical user from saving the audio bytes during the session window. Browsers
  *will* download the audio bytes in order to play them. `controlsList="nodownload"` and
  disabling right-click are UX nudges, not security.
- Sharing of the public link to another device during the active window

This is **controlled exam delivery**, not DRM. If you need DRM, you need a different product.

Hardening notes for production:
- Set a strong `SECRET_KEY` (`python -c "import secrets; print(secrets.token_urlsafe(64))"`)
- Set `SESSION_COOKIE_SECURE=true` when serving over HTTPS (Tailscale Funnel terminates TLS, so
  this is correct in that setup)
- Front the app with a reverse proxy or Tailscale Funnel — uvicorn is started with
  `--proxy-headers`
- Add rate limiting in front of `/login` and `/s/{token}` (Caddy / Tailscale ACLs / fail2ban /
  `slowapi`). Not implemented in-app.
- PostgreSQL backups: see "Backups" section

## Quick start (Docker Compose)

```bash
cp .env.example .env
# Edit at least:
#   INITIAL_ADMIN_USERNAME, INITIAL_ADMIN_PASSWORD, INITIAL_ADMIN_EMAIL (optional)
#   SECRET_KEY (long random)
docker compose up -d --build
```

Then open <http://127.0.0.1:8080/login> and log in as the initial superadmin.

The app listens on `127.0.0.1:8080` by default (only the host loopback). PostgreSQL data is in a
named Docker volume `db_data`. Uploaded audio is bind-mounted under `./data/uploads` so it is
trivial to back up.

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `APP_NAME` | `Exam Audio Relay` | Title shown in UI |
| `DATABASE_URL` | `postgresql+psycopg://exam:exam_password@db:5432/exam_audio` | SQLAlchemy URL |
| `INITIAL_ADMIN_USERNAME` | `admin` | Created on first start if missing |
| `INITIAL_ADMIN_PASSWORD` | `change_me_now` | **Change before first run** |
| `INITIAL_ADMIN_EMAIL` | (empty) | Optional |
| `DATA_DIR` | `/data` | Inside the container |
| `UPLOAD_DIR` | `/data/uploads` | Inside the container |
| `MAX_UPLOAD_MB` | `250` | Per-file upload limit |
| `HOST` | `0.0.0.0` | Inside container only — host port-binds to 127.0.0.1 |
| `PORT` | `8080` | |
| `SECRET_KEY` | `replace_me` | **Change in production**. Used to sign session cookies. |
| `SESSION_COOKIE_SECURE` | `false` | Set to `true` behind HTTPS |
| `BASE_URL` | (empty) | If set, dashboard renders absolute student links |
| `TZ` | `Europe/Rome` | Display timezone |

## Exposing via Tailscale Funnel

The app binds the container port to `127.0.0.1:8080` on the host, so the only public path is
through Tailscale Funnel.

```bash
# Once on the host, after `tailscale up` and Funnel-enabled tailnet:
sudo tailscale funnel 8080
```

Then set `BASE_URL=https://<your-machine>.<your-tailnet>.ts.net` in `.env` and
`SESSION_COOKIE_SECURE=true`, and `docker compose up -d` to apply.

Tailscale Funnel terminates TLS for you — the app itself stays plain HTTP on loopback.

## Typical workflow

### Superadmin creates teachers

1. Log in at `/login` with `INITIAL_ADMIN_USERNAME` / `INITIAL_ADMIN_PASSWORD`
2. Go to **Teachers → New teacher**
3. Set username, role (`teacher` by default), and an initial password (≥8 chars)
4. Share the credentials with the teacher out-of-band

### Teacher uploads audio and creates a session

1. Teacher logs in at `/login`
2. **Upload** → pick `.mp3 / .wav / .m4a / .ogg`, give it a display name
3. **New session** → choose the file, set either:
   - a fixed start/end datetime, or
   - "Start now for N minutes" (15, 30, 45, 60, 90, 120)
   - optional max access count, optional notes shown to the student
4. Copy the link `https://.../s/<token>` and share it with students
5. During the window, students can play the audio. Outside the window, the link returns a
   generic "session unavailable" page.
6. Click **Revoke** on the session detail page to immediately stop further access.

## Backups

PostgreSQL:
```bash
docker compose exec -T db pg_dump -U exam exam_audio > backup-$(date +%F).sql
# restore:
docker compose exec -T db psql -U exam -d exam_audio < backup-2026-04-28.sql
```

Audio files:
```bash
tar czf uploads-$(date +%F).tgz ./data/uploads
```

## Development without Docker

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=sqlite:///./data/dev.db
export SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(48))')
export INITIAL_ADMIN_USERNAME=admin INITIAL_ADMIN_PASSWORD=devpass
export DATA_DIR=./data UPLOAD_DIR=./data/uploads
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

Run the tests:
```bash
pip install pytest httpx
pytest -q
```

## Known limitations

- No in-app rate limiting (use Tailscale ACLs / Caddy / fail2ban). TODO.
- No email verification or password recovery. Superadmin resets passwords manually.
- No QR code generation in the dashboard. TODO.
- No batch upload UI; one file at a time. TODO.
- Audio MIME validation is by extension; no `magic` byte sniffing. TODO.
- Single-instance app. No horizontal scaling primitives (sessions are signed cookies, but
  upload directory is local).

## Future improvements

- Rate limiting and login throttling (in-app, not just at the edge)
- QR code per session link
- Per-teacher disk quota
- Soft-delete of files instead of hard delete
- Audit log export to CSV
- Email notifications on revoke / max access reached
- Multi-language UI (it/en)

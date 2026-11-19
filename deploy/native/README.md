# Native deployment (no Docker)

The same application on an existing Linux server, next to the server's other sites (for example a Plesk server).
systemd runs the three app processes and the server's own nginx takes the place of Caddy. The settings, `.env`
values and Super Admin setup are the same as in the Docker deployment (`docs/phase8/runbook.md`).

| Process | Listens on | Unit |
|---|---|---|
| Website, panels, Super Admin, API (gunicorn) | `127.0.0.1:8100` | `aiemployee-web` |
| Scheduled jobs | none | `aiemployee-scheduler` |
| Voice Gateway | `127.0.0.1:8765` | `aiemployee-voice` |
| Daily database dump to `/opt/ai-employee/backups` | none | `aiemployee-backup.timer` |

All three app units run in `aiemployee.slice`, which caps them together at 8 CPU cores and 16 GB of memory so the
server's other sites keep the rest. Change the cap in that file.

## One-time server preparation (root)

On a server that hosts other sites, install only new packages and never run `apt upgrade` as part of this.

1. PostgreSQL 14 or newer with the pgvector extension, and Redis with a password (`requirepass`). Both listen on
   localhost only (their package defaults).
2. Database: a login role `aiemployee` that owns the database `aiemployee`, then, as the postgres superuser,
   `CREATE EXTENSION vector;` in that database. The least-privilege app role is created by `update.sh`.
3. The app user and its tools: `useradd --system --create-home --home-dir /opt/ai-employee --shell /usr/sbin/nologin aiemployee`,
   then `uv` in `/opt/ai-employee/bin` and Python 3.12 with
   `sudo -u aiemployee env HOME=/opt/ai-employee UV_PYTHON_INSTALL_DIR=/opt/ai-employee/python /opt/ai-employee/bin/uv python install 3.12`.
   The server's own Python is not touched.

## First deployment

1. `sudo -u aiemployee git clone -b main <repository URL> /opt/ai-employee/app`
2. `/opt/ai-employee/app/.env` (owner `aiemployee`), from `deploy/.env.production.example`, with these native values:

   ```
   OWNER_DATABASE_URL=postgres://aiemployee:<POSTGRES_PASSWORD>@127.0.0.1:5432/aiemployee
   DATABASE_URL=postgres://aiemployee_app:<APP_DB_PASSWORD>@127.0.0.1:5432/aiemployee
   REDIS_URL=redis://:<REDIS_PASSWORD>@127.0.0.1:6379/0
   VOICE_GATEWAY_BIND=127.0.0.1:8765
   # empty skips the upload scan; 127.0.0.1:3310 with a local clamd
   CLAMAV_ADDRESS=
   ```

   A staging / demo server adds `ENVIRONMENT=staging` and `VOICE_REQUIREMENTS=voice-local.txt` (free Whisper + Kokoro).
3. `sh /opt/ai-employee/app/deploy/native/update.sh`
4. nginx, with HTTPS certificates for the three names:
   - `<domain>` with `admin.<domain>` as an alias: the lines in `nginx-site.conf`.
   - `voice.<domain>`: the lines in `nginx-voice.conf`.

   In Plesk: add `admin.<domain>` as a domain alias and `voice.<domain>` as a subdomain, issue Let's Encrypt for
   them, turn "Proxy mode" off in Apache & nginx Settings and paste the file into "Additional nginx directives".
   Plesk checks the configuration before it applies it and reloads nginx without dropping connections.

## Updates

`sh /opt/ai-employee/app/deploy/native/update.sh` pulls the checked-out branch, installs, migrates and restarts. Calls in progress get
up to 10 minutes to finish. Logs: `journalctl -u aiemployee-web -u aiemployee-scheduler -u aiemployee-voice -f`.

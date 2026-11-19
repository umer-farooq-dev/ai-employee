#!/bin/sh
# Native (no Docker) install and update, run as root on the server:  sh /opt/ai-employee/app/deploy/native/update.sh
# Pulls the code, installs packages, migrates, collects static files and (re)starts the services.
# One-time server preparation and the first deployment: deploy/native/README.md
set -eu
BASE=/opt/ai-employee
APP=$BASE/app
VENV=$BASE/venv
as_app() { sudo -E -u aiemployee env HOME="$BASE" "$@"; }

cd "$APP"
as_app git pull --ff-only
set -a; . ./.env; set +a  # values without spaces or quotes
export DJANGO_SETTINGS_MODULE=config.settings.production

[ -x "$VENV/bin/python" ] || as_app env UV_PYTHON_INSTALL_DIR="$BASE/python" "$BASE/bin/uv" venv --seed --python 3.12 "$VENV"
# gateway requirements first, then the web pins on top (Pillow 13 over pipecat's pin): the Dockerfile's order
as_app "$VENV/bin/pip" install -q -r "backend/requirements/${VOICE_REQUIREMENTS:-voice.txt}"
as_app "$VENV/bin/pip" install -q -r backend/requirements/prod.txt

cd backend
as_app env DATABASE_URL="$OWNER_DATABASE_URL" "$VENV/bin/python" manage.py migrate --noinput
as_app env DATABASE_URL="$OWNER_DATABASE_URL" "$VENV/bin/python" manage.py setup_app_db_role --role="$APP_DB_USER" --password="$APP_DB_PASSWORD"
as_app "$VENV/bin/python" manage.py collectstatic --noinput -v 0

# nginx reads static and public media; company files, backups and .env stay private to the app user
as_app mkdir -p "$APP/media" "$APP/private_media"
chmod 711 "$BASE" "$APP"
chmod -R a+rX "$APP/staticfiles" "$APP/media"
chmod 700 "$APP/private_media"
chmod 600 "$APP/.env"

cp "$APP"/deploy/native/aiemployee.slice "$APP"/deploy/native/aiemployee-*.service "$APP"/deploy/native/aiemployee-*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable -q --now aiemployee-backup.timer
systemctl enable -q aiemployee-web aiemployee-scheduler aiemployee-voice
systemctl restart aiemployee-web aiemployee-scheduler aiemployee-voice
systemctl is-active aiemployee-web aiemployee-scheduler aiemployee-voice

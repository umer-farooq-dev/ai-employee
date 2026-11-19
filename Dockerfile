# ENGR-04: one image definition, two targets. Build once, promote the same image digest from staging to production.
#   docker build --target web   -t aiemployee-web .     # website, panels, API, webhooks, scheduler
#   docker build --target voice -t aiemployee-voice .   # Voice Gateway (Pipecat; its own Pillow pin, see voice.txt)

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production
# security updates of the Debian base packages (Trivy fails the build on fixable HIGH / CRITICAL)
RUN apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 app \
    && mkdir -p /app/media /app/private_media /app/staticfiles && chown -R app /app
WORKDIR /app
COPY backend/requirements /app/backend/requirements

FROM base AS web
RUN pip install -r backend/requirements/prod.txt
COPY backend /app/backend
# static files are collected at build time; the build values below exist only for this step
RUN SECRET_KEY=build-only-not-a-secret-build-only-not-a-secret-xx FIELD_ENCRYPTION_KEY=build-only ALLOWED_HOSTS=build \
    DATABASE_URL=sqlite:////tmp/build.db \
    python backend/manage.py collectstatic --noinput -v 0 && chown -R app /app/staticfiles
USER app
WORKDIR /app/backend
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os,urllib.request as u; u.urlopen(u.Request('http://127.0.0.1:8000/healthz/', headers={'Host': os.environ['ALLOWED_HOSTS'].split(',')[0]}), timeout=4)"
CMD ["gunicorn", "config.wsgi", "--bind", "0.0.0.0:8000", "--worker-class", "gthread", "--workers", "3", "--threads", "8", \
     "--timeout", "60", "--graceful-timeout", "30", "--access-logfile", "-", "--forwarded-allow-ips", "*"]

FROM base AS voice
# voice-local.txt adds the free local Whisper + Kokoro engines (staging / demo only; test-only providers are blocked in production)
ARG VOICE_REQUIREMENTS=voice.txt
# gateway requirements, then the web pins on top: Pillow 13 (security fixes) over pipecat's Pillow<13 pin, see voice.txt
RUN pip install -r backend/requirements/${VOICE_REQUIREMENTS} && pip install -r backend/requirements/base.txt
COPY backend /app/backend
USER app
WORKDIR /app/backend
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8765/healthz', timeout=4)"
# --bind 0.0.0.0:8765 inside the container; the stop grace period in compose lets active calls finish
CMD ["python", "manage.py", "run_voice_gateway", "--bind", "0.0.0.0:8765"]

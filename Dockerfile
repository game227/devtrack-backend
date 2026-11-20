FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# The application never runs as root (see docker-entrypoint.sh).
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=app:app . .

# Static files are collected at build time (production uses a hashed manifest, and an image that has
# not collected them would answer 500 for every admin/static request). The build needs *a* SECRET_KEY
# to start Django; this throwaway value is never used at runtime.
RUN SECRET_KEY=build-time-only-not-a-secret-0123456789abcdef \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    python manage.py collectstatic --noinput \
 && mkdir -p /app/media \
 && chown -R app:app /app/media /app/staticfiles \
 && chmod +x /app/docker-entrypoint.sh

EXPOSE 8000

# A plain TCP check: the HTTP endpoint insists on HTTPS and a whitelisted Host, neither of which a
# container-local probe has. (Render and compose run their own HTTP health checks.)
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import socket, os; socket.create_connection(('127.0.0.1', int(os.environ.get('PORT', '8000'))), 3).close()"

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]

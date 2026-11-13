#!/bin/sh
# Starts as root only long enough to make the uploads directory writable — a mounted volume or Render
# disk arrives owned by root — then runs the real command as the unprivileged `app` user.
set -e
if [ "$(id -u)" = "0" ]; then
    mkdir -p /app/media
    chown -R app:app /app/media
    exec setpriv --reuid=app --regid=app --init-groups "$@"
fi
exec "$@"

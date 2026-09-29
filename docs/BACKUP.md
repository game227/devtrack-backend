# Backup and restore

DevTrack's only durable state is the Postgres database (`devtrack-db` in
`render.yaml`) plus the media disk (user avatars). This is not yet
scheduled anywhere — set it up once the database is a real production
database with real data in it.

## Backing up

```bash
DATABASE_URL=<production connection string> ./scripts/backup.sh
```

Writes a gzip-compressed `pg_dump` to `./backups/devtrack-<UTC timestamp>.sql.gz`
(override the directory with `BACKUP_DIR`). Run this from any machine with
network access to the database — a local shell, a CI job, or a Render cron
job pointed at the same `DATABASE_URL` the web service uses.

**Suggested schedule once live:** daily, kept for at least 14 days.
Render's own Postgres offers point-in-time recovery on paid plans — check
the plan's retention window before relying solely on this script's manual
snapshots.

**Media**: avatars live on a mounted disk (`devtrack-media` in
`render.yaml`), not in the database. Render's paid disks support
snapshots; there is no separate script for this yet — take a Render disk
snapshot on the same schedule as the database backup, or add S3/R2 object
storage (item 7 of the production plan), which removes the need to back
up a disk at all.

## Restoring

```bash
gunzip -c backups/devtrack-<timestamp>.sql.gz | psql <target connection string>
```

Restore into an **empty** database — `psql` will error on conflicting
objects if you restore into one that already has the DevTrack schema.
To rehearse a restore safely:

```bash
createdb devtrack_restore_test
gunzip -c backups/devtrack-<timestamp>.sql.gz | psql postgres://localhost/devtrack_restore_test
python manage.py shell -c "from django.contrib.auth import get_user_model; print(get_user_model().objects.count())"
dropdb devtrack_restore_test
```

Do this after setting up the schedule above, and periodically afterward —
an untested backup is not a backup.

"""Dump the database with pg_dump and keep the copy somewhere that outlives the database.

    python manage.py backup_database                  # upload to BACKUP_BUCKET (S3/R2), prune old ones
    python manage.py backup_database --local-dir DIR  # just write the file locally

Runs daily as the `devtrack-db-backup` cron job in render.yaml. The dump is pg_dump's custom format
(compressed, restorable with pg_restore — see docs/BACKUP.md).
"""

import datetime as dt
import os
import subprocess  # noqa: S404 — runs pg_dump with arguments we build, never through a shell
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

PREFIX = "backups/"


def database_url():
    db = settings.DATABASES["default"]
    if "postgresql" not in db["ENGINE"]:
        raise CommandError("Only PostgreSQL databases can be backed up with this command.")
    return db


def run_pg_dump(target):
    db = database_url()
    env = {**os.environ, "PGPASSWORD": str(db.get("PASSWORD") or "")}  # not on the command line
    command = [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        f"--host={db.get('HOST') or 'localhost'}",
        f"--port={db.get('PORT') or 5432}",
        f"--username={db.get('USER') or ''}",
        f"--file={target}",
        db["NAME"],
    ]
    result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        # pg_dump creates the file before it fails: never leave an empty "backup" behind.
        Path(target).unlink(missing_ok=True)
        raise CommandError(f"pg_dump failed: {result.stderr.strip()[:500]}")


def bucket_client():
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("BACKUP_ENDPOINT_URL") or None,
        aws_access_key_id=os.environ.get("BACKUP_ACCESS_KEY") or None,
        aws_secret_access_key=os.environ.get("BACKUP_SECRET_KEY") or None,
        region_name=os.environ.get("BACKUP_REGION") or "auto",
    )


class Command(BaseCommand):
    help = "Back up the database (pg_dump) to BACKUP_BUCKET, or to a local directory with --local-dir."

    def add_arguments(self, parser):
        parser.add_argument("--local-dir", help="Write the dump here instead of uploading it.")
        parser.add_argument(
            "--keep-days",
            type=int,
            default=int(os.environ.get("BACKUP_RETENTION_DAYS") or 14),
            help="Delete uploaded backups older than this (default 14, or BACKUP_RETENTION_DAYS).",
        )

    def handle(self, *args, **options):
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        name = f"devtrack-{stamp}.dump"

        if options["local_dir"]:
            directory = Path(options["local_dir"])
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / name
            run_pg_dump(target)
            target.chmod(0o600)
            self.stdout.write(f"Wrote {target}")
            return

        bucket = os.environ.get("BACKUP_BUCKET")
        if not bucket:
            raise CommandError("Set BACKUP_BUCKET (and its credentials), or pass --local-dir.")
        client = bucket_client()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / name
            run_pg_dump(target)
            client.upload_file(str(target), bucket, PREFIX + name)
        self.stdout.write(f"Uploaded s3://{bucket}/{PREFIX}{name}")

        cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=options["keep_days"])
        listing = client.list_objects_v2(Bucket=bucket, Prefix=PREFIX)
        stale = [item["Key"] for item in listing.get("Contents", []) if item["LastModified"] < cutoff]
        if stale and options["keep_days"] > 0:
            client.delete_objects(Bucket=bucket, Delete={"Objects": [{"Key": key} for key in stale]})
            self.stdout.write(f"Deleted {len(stale)} backup(s) older than {options['keep_days']} days")

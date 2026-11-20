import datetime as dt
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase


def fake_pg_dump(command, env, **kwargs):
    target = next(arg.split("=", 1)[1] for arg in command if arg.startswith("--file="))
    Path(target).write_bytes(b"PGDMP")
    fake_pg_dump.seen = (command, env)
    return MagicMock(returncode=0, stderr="")


class BackupDatabaseTests(SimpleTestCase):
    @patch(
        "apps.common.management.commands.backup_database.database_url",
        return_value={"ENGINE": "django.db.backends.postgresql", "NAME": "prod", "USER": "app", "PASSWORD": "s3cret-pw", "HOST": "db.internal", "PORT": 5432},
    )
    @patch("apps.common.management.commands.backup_database.subprocess.run", side_effect=fake_pg_dump)
    def test_writes_a_private_local_dump_without_the_password_on_the_command_line(self, _run, _db):
        with tempfile.TemporaryDirectory() as tmp:
            call_command("backup_database", "--local-dir", tmp, stdout=MagicMock())
            files = list(Path(tmp).glob("devtrack-*.dump"))
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].stat().st_mode & 0o777, 0o600)
        command, env = fake_pg_dump.seen
        self.assertIn("--format=custom", command)
        self.assertEqual(env["PGPASSWORD"], "s3cret-pw")
        self.assertFalse(any("s3cret-pw" in arg for arg in command))
        self.assertIn("--host=db.internal", command)

    @patch("apps.common.management.commands.backup_database.subprocess.run", side_effect=fake_pg_dump)
    @patch("apps.common.management.commands.backup_database.bucket_client")
    def test_uploads_and_prunes_only_old_backups(self, client_factory, _run):
        client = client_factory.return_value
        now = dt.datetime.now(dt.UTC)
        client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "backups/old.dump", "LastModified": now - dt.timedelta(days=30)},
                {"Key": "backups/recent.dump", "LastModified": now - dt.timedelta(days=2)},
            ]
        }
        with patch.dict(os.environ, {"BACKUP_BUCKET": "devtrack-backups"}):
            call_command("backup_database", stdout=MagicMock())
        bucket, key = client.upload_file.call_args.args[1:]
        self.assertEqual(bucket, "devtrack-backups")
        self.assertRegex(key, r"^backups/devtrack-\d{8}T\d{6}Z\.dump$")
        client.delete_objects.assert_called_once_with(
            Bucket="devtrack-backups", Delete={"Objects": [{"Key": "backups/old.dump"}]}
        )

    def test_refuses_without_a_destination(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BACKUP_BUCKET", None)
            with self.assertRaises(CommandError):
                call_command("backup_database", stdout=MagicMock())

    @patch("apps.common.management.commands.backup_database.subprocess.run", return_value=MagicMock(returncode=1, stderr="connection refused"))
    def test_a_failed_dump_is_an_error_not_an_empty_backup(self, _run):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(CommandError):
                call_command("backup_database", "--local-dir", tmp, stdout=MagicMock())
            self.assertEqual(list(Path(tmp).iterdir()), [])

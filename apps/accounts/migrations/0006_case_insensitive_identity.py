"""Usernames and emails unique regardless of letter case.

Fails with a clear message (instead of a bare IntegrityError) if existing accounts already collide, so a
deploy stops before anything changes and the duplicates can be merged by hand first.
"""

from django.db import migrations, models
from django.db.models import Count
from django.db.models.functions import Lower


def refuse_existing_duplicates(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    problems = []
    for field in ("username", "email"):
        rows = (
            User.objects.exclude(**{field: ""})
            .annotate(key=Lower(field))
            .values("key")
            .annotate(n=Count("id"))
            .filter(n__gt=1)
        )
        problems += [f"{field} {row['key']!r} ({row['n']} accounts)" for row in rows]
    if problems:
        raise RuntimeError(
            "Accounts differing only by letter case must be merged before this migration can run: "
            + "; ".join(problems)
        )


class Migration(migrations.Migration):
    dependencies = [("accounts", "0005_avatar_random_upload_path")]

    operations = [
        migrations.RunPython(refuse_existing_duplicates, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(Lower("username"), name="accounts_user_username_ci_unique"),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.UniqueConstraint(
                Lower("email"), condition=models.Q(("email", ""), _negated=True), name="accounts_user_email_ci_unique"
            ),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_alter_user_email"),
    ]

    operations = [
        # Backfilled as True (existing accounts are grandfathered in as
        # verified — email verification only gates NEW registrations, not
        # already-existing ones); preserve_default=False means Django uses
        # the model's real default (False) for every row created after
        # this migration runs, not this one-time backfill value.
        migrations.AddField(
            model_name="user",
            name="email_verified",
            field=models.BooleanField(default=True),
            preserve_default=False,
        ),
    ]

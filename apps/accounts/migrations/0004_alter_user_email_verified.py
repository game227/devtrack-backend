from django.db import migrations, models


class Migration(migrations.Migration):
    # No-op at the database level — 0003 already backfilled every existing
    # row as True. This only flips the *future* default new rows get
    # (email_verified=False) to match models.py, completing the pattern
    # 0003 started with preserve_default=False.

    dependencies = [
        ('accounts', '0003_user_email_verified'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='email_verified',
            field=models.BooleanField(default=False),
        ),
    ]

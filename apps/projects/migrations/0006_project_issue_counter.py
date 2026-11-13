from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0005_projectmember_specialty"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="issue_counter",
            field=models.PositiveIntegerField(default=0, editable=False),
        ),
    ]

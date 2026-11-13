from django.db import migrations, models
from django.db.models import F


def stamp_finished_issues(apps, schema_editor):
    # The best record of when existing finished issues were completed is their last update.
    apps.get_model("issues", "Issue").objects.filter(status="done").update(completed_at=F("updated_at"))


class Migration(migrations.Migration):
    dependencies = [("issues", "0006_issue_number_required")]

    operations = [
        migrations.AddField(
            model_name="issue",
            name="completed_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.RunPython(stamp_finished_issues, migrations.RunPython.noop),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("issues", "0005_issue_number"),
    ]

    operations = [
        migrations.AlterField(
            model_name="issue",
            name="number",
            field=models.PositiveIntegerField(editable=False),
        ),
        migrations.AddConstraint(
            model_name="issue",
            constraint=models.UniqueConstraint(fields=("project", "number"), name="issues_issue_unique_number_per_project"),
        ),
    ]

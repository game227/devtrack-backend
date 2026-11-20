"""Give every issue a number that is unique within its project (``#1``, ``#2``, ...).

Step 1 of 2: add the column (nullable) and number the issues that already exist. The column becomes
required, with its uniqueness constraint, in the next migration — schema changes and data changes are
kept in separate migrations so PostgreSQL never has pending trigger events when it alters the table.
"""

from django.db import migrations, models


def number_existing_issues(apps, schema_editor):
    Issue = apps.get_model("issues", "Issue")
    Project = apps.get_model("projects", "Project")

    for project in Project.objects.all().iterator():
        issues = list(Issue.objects.filter(project=project).order_by("created_at", "id"))
        taken = set()
        # Issues imported from GitHub keep GitHub's own number: that is what people type in commit
        # messages and pull requests ("fixes #12"), so renumbering them would silently break the link.
        for issue in issues:
            if issue.github_number and issue.github_number not in taken:
                issue.number = issue.github_number
                taken.add(issue.github_number)
        # Everything else continues after the highest number in use, oldest first.
        counter = max(taken, default=0)
        for issue in issues:
            if issue.number is None:
                counter += 1
                issue.number = counter
        Issue.objects.bulk_update(issues, ["number"], batch_size=500)
        Project.objects.filter(pk=project.pk).update(issue_counter=counter)


class Migration(migrations.Migration):
    dependencies = [
        ("issues", "0004_issue_github_number_issue_github_url"),
        ("projects", "0006_project_issue_counter"),
    ]

    operations = [
        migrations.AddField(
            model_name="issue",
            name="number",
            field=models.PositiveIntegerField(editable=False, null=True),
        ),
        migrations.RunPython(number_existing_issues, migrations.RunPython.noop),
    ]

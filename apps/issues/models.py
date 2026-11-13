from django.conf import settings
from django.db import models, transaction


class Issue(models.Model):
    class Type(models.TextChoices):
        TASK = "task", "Task"
        BUG = "bug", "Bug"
        FEATURE = "feature", "Feature"
        IMPROVEMENT = "improvement", "Improvement"
        CHORE = "chore", "Chore"

    class Status(models.TextChoices):
        BACKLOG = "backlog", "Backlog"
        TODO = "todo", "Todo"
        IN_PROGRESS = "in_progress", "In Progress"
        IN_REVIEW = "in_review", "In Review"
        DONE = "done", "Done"

    class Priority(models.TextChoices):
        NONE = "none", "No priority"
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="issues")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    type = models.CharField(max_length=15, choices=Type.choices, default=Type.TASK)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.BACKLOG)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NONE)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="assigned_issues",
        null=True,
        blank=True,
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reported_issues"
    )
    cycle = models.ForeignKey(
        "cycles.Cycle", on_delete=models.SET_NULL, related_name="issues", null=True, blank=True
    )
    milestone = models.ForeignKey(
        "milestones.Milestone", on_delete=models.SET_NULL, related_name="issues", null=True, blank=True
    )
    labels = models.ManyToManyField("projects.Label", related_name="issues", blank=True)
    due_date = models.DateField(null=True, blank=True)
    # The issue's number within its project (#1, #2, ...): what people see and what `#12` in a commit or
    # pull request refers to. Assigned on creation; an issue imported from GitHub keeps GitHub's number.
    number = models.PositiveIntegerField(editable=False)
    # Set on issues imported from GitHub (informational: `number` already equals it).
    github_number = models.PositiveIntegerField(null=True, blank=True)
    github_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["project", "number"], name="issues_issue_unique_number_per_project"),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self._state.adding and self.number is None:
            # Allocation and insert are one transaction, with the project row locked, so two issues
            # created at the same moment can never get the same number.
            with transaction.atomic():
                self.number = allocate_issue_number(self.project_id)
                super().save(*args, **kwargs)
            return
        super().save(*args, **kwargs)


def allocate_issue_number(project_id):
    """The next free number in a project. Call inside ``transaction.atomic()``."""
    from apps.projects.models import Project

    project = Project.objects.select_for_update().only("id", "issue_counter").get(pk=project_id)
    project.issue_counter += 1
    project.save(update_fields=["issue_counter"])
    return project.issue_counter

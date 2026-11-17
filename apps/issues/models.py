from django.conf import settings
from django.core.validators import MaxValueValidator
from django.db import models, transaction
from django.utils import timezone


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
    # Story points: how big the work is, on whatever scale the team uses (1, 2, 3, 5, 8...). Optional.
    estimate = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(100)])
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
    # When the issue last reached Done (cleared if it is reopened). Kept by save() whatever path changed
    # the status (API, board, bot, GitHub automation), so "recently completed" means just that.
    completed_at = models.DateTimeField(null=True, blank=True, editable=False)
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
        done = self.status == self.Status.DONE
        if done != (self.completed_at is not None):
            self.completed_at = timezone.now() if done else None
            update_fields = kwargs.get("update_fields")
            if update_fields is not None and "completed_at" not in update_fields:
                kwargs["update_fields"] = [*update_fields, "completed_at"]
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


class SavedView(models.Model):
    """A named set of issue-list filters, private to the person who saved it.

    It belongs to a workspace (the workspace-wide issue list) or to one project (that project's list).
    `filters` holds only the keys the issue list understands (see `SAVED_VIEW_FILTER_KEYS`).
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_issue_views")
    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE, related_name="saved_issue_views")
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE, null=True, blank=True, related_name="saved_issue_views")
    name = models.CharField(max_length=60)
    filters = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]
        # Two constraints, because PostgreSQL treats NULL project ids as distinct: one name per person
        # for the workspace-wide list, and one per person in each project.
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "workspace", "name"],
                condition=models.Q(project__isnull=True),
                name="issues_savedview_unique_workspace_name",
            ),
            models.UniqueConstraint(
                fields=["owner", "project", "name"],
                condition=models.Q(project__isnull=False),
                name="issues_savedview_unique_project_name",
            ),
        ]

    def __str__(self):
        return self.name


SAVED_VIEW_FILTER_KEYS = ("status", "type", "priority", "assignee", "label")


class ChecklistItem(models.Model):
    """One step of an issue's checklist ("- [ ] write tests"), ticked off as the work goes."""

    issue = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="checklist_items")
    text = models.CharField(max_length=200)
    done = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return self.text


class IssueRelation(models.Model):
    """A link between two issues of the same workspace, stored once and shown from both ends.

    "#3 blocks #7" is shown on #7 as "blocked by #3"; "duplicates" reads "duplicated by" from the other
    end; "relates to" reads the same both ways.
    """

    class Kind(models.TextChoices):
        BLOCKS = "blocks", "Blocks"
        DUPLICATES = "duplicates", "Duplicates"
        RELATES = "relates", "Relates to"

    source = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="relations_out")
    target = models.ForeignKey(Issue, on_delete=models.CASCADE, related_name="relations_in")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["kind", "id"]
        constraints = [
            models.UniqueConstraint(fields=["source", "target", "kind"], name="issues_relation_unique"),
            models.CheckConstraint(condition=~models.Q(source=models.F("target")), name="issues_relation_not_self"),
        ]

    def __str__(self):
        return f"{self.source_id} {self.kind} {self.target_id}"

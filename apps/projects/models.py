from django.conf import settings
from django.db import models


class Project(models.Model):
    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        COMPLETED = "completed", "Completed"
        ARCHIVED = "archived", "Archived"

    class Priority(models.TextChoices):
        NONE = "none", "No priority"
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="projects"
    )
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    icon = models.CharField(max_length=32, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PLANNED)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.NONE)
    start_date = models.DateField(null=True, blank=True)
    target_date = models.DateField(null=True, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="owned_projects"
    )
    team = models.ForeignKey(
        "teams.Team", on_delete=models.SET_NULL, related_name="projects", null=True, blank=True
    )
    repository_url = models.URLField(blank=True)
    tech_stack = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class ProjectMember(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="project_memberships"
    )
    role = models.CharField(max_length=20, blank=True)

    class Specialty(models.TextChoices):
        FRONTEND = "frontend", "Frontend developer"
        BACKEND = "backend", "Backend developer"
        DEBUGGER = "debugger", "Debugger"
        DESIGNER = "designer", "Designer"

    # What the person does on this project. Separate from `role` (permission level) on purpose:
    # someone can be an admin and a designer, and be backend on one project and a debugger on another.
    specialty = models.CharField(max_length=20, choices=Specialty.choices, blank=True)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("project", "user")
        ordering = ["added_at"]

    def __str__(self):
        return f"{self.user} @ {self.project}"


class Label(models.Model):
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="labels"
    )
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="labels", null=True, blank=True
    )
    name = models.CharField(max_length=50)
    color = models.CharField(max_length=7, default="#6b7280")

    def __str__(self):
        return self.name


class Note(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="notes")
    title = models.CharField(max_length=150)
    body = models.TextField(blank=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notes")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title

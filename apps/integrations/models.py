import uuid

from django.conf import settings
from django.db import models

from .fields import EncryptedCharField


class GitHubAccount(models.Model):
    """One DevTrack user's connected GitHub OAuth identity."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="github_account"
    )
    github_user_id = models.BigIntegerField(unique=True)
    github_username = models.CharField(max_length=255)
    # Encrypted at rest (Fernet, see fields.py) — application code reads/writes
    # this exactly like a plain CharField; only the DB column holds ciphertext.
    # Also never serialized in any API response and excluded from the admin form.
    access_token = EncryptedCharField(max_length=500)
    scope = models.CharField(max_length=255, blank=True)
    connected_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


    class Meta:
        verbose_name = "GitHub account"

    def __str__(self):
        return f"{self.user} -> github:{self.github_username}"


class GitHubPendingConnection(models.Model):
    """A GitHub authorization that came back from GitHub but is not linked to anyone yet.

    GitHub redirects a *browser* to the callback, without any proof of which DevTrack user that browser
    belongs to. Linking there would let anyone send a victim their own authorization link and receive the
    victim's GitHub token on their account. So the callback only parks the result here, and the SPA in the
    browser that started the flow claims it with that user's own credentials and a secret only that
    browser holds (see GitHubCompleteView).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="github_pending_connections"
    )
    nonce_hash = models.CharField(max_length=64)
    github_user_id = models.BigIntegerField()
    github_username = models.CharField(max_length=255)
    access_token = EncryptedCharField(max_length=500)
    scope = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


    class Meta:
        verbose_name = "pending GitHub connection"

    def __str__(self):
        return f"pending github:{self.github_username} for {self.user}"


class GitHubRepositoryLink(models.Model):
    """A DevTrack Project linked 1:1 to a GitHub repo (webhook already provisioned)."""

    project = models.OneToOneField(
        "projects.Project", on_delete=models.CASCADE, related_name="github_link"
    )
    github_repo_id = models.BigIntegerField(unique=True)
    full_name = models.CharField(max_length=255)
    webhook_id = models.BigIntegerField(null=True, blank=True)
    # Kept in step with every delivery (GitHub includes it in each payload): a PR merged into
    # this branch closes its issues, a merge into any other branch only moves them to review.
    default_branch = models.CharField(max_length=255, blank=True)
    # When GitHub last delivered anything / when a manual sync last ran: tells the UI whether the
    # webhook is really alive rather than merely installed.
    last_event_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    connected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="linked_github_repos"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


    class Meta:
        verbose_name = "GitHub repository link"

    def __str__(self):
        return f"{self.project} -> {self.full_name}"


class GitHubPullRequest(models.Model):
    class State(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

    repo_link = models.ForeignKey(
        GitHubRepositoryLink, on_delete=models.CASCADE, related_name="pull_requests"
    )
    github_pr_id = models.BigIntegerField()
    number = models.PositiveIntegerField()
    title = models.CharField(max_length=255)
    state = models.CharField(max_length=10, choices=State.choices, default=State.OPEN)
    merged = models.BooleanField(default=False)
    author_username = models.CharField(max_length=255, blank=True)
    url = models.URLField()
    head_ref = models.CharField(max_length=255, blank=True)
    base_ref = models.CharField(max_length=255, blank=True)
    draft = models.BooleanField(default=False)
    # GitHub's own timestamps (created_at/updated_at below are when *DevTrack* stored the row).
    opened_at = models.DateTimeField(null=True, blank=True)
    merged_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    issues = models.ManyToManyField("issues.Issue", related_name="linked_pull_requests", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "GitHub pull request"
        unique_together = [("repo_link", "github_pr_id")]
        ordering = ["-updated_at"]

    def __str__(self):
        return f"PR #{self.number} on {self.repo_link}"


class GitHubCommit(models.Model):
    repo_link = models.ForeignKey(GitHubRepositoryLink, on_delete=models.CASCADE, related_name="commits")
    sha = models.CharField(max_length=40)
    message = models.TextField()
    author_username = models.CharField(max_length=255, blank=True)
    author_name = models.CharField(max_length=255, blank=True)
    url = models.URLField()
    branch = models.CharField(max_length=255, blank=True)
    # When the commit was authored on GitHub; created_at is only when DevTrack heard about it.
    committed_at = models.DateTimeField(null=True, blank=True)
    issues = models.ManyToManyField("issues.Issue", related_name="linked_commits", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "GitHub commit"
        unique_together = [("repo_link", "sha")]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.sha[:7]} on {self.repo_link}"

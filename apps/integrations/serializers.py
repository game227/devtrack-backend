from rest_framework import serializers

from apps.workspaces.serializers import UserBriefSerializer

from .models import GitHubCommit, GitHubPullRequest, GitHubRepositoryLink


class GitHubRepositoryLinkSerializer(serializers.ModelSerializer):
    connected_by = UserBriefSerializer(read_only=True)
    # False when the webhook could not be installed (e.g. the server is not publicly reachable):
    # the repo is still linked and can be refreshed with a manual sync.
    webhook_installed = serializers.SerializerMethodField()

    class Meta:
        model = GitHubRepositoryLink
        fields = [
            "id",
            "project",
            "github_repo_id",
            "full_name",
            "webhook_installed",
            "default_branch",
            "last_event_at",
            "last_synced_at",
            "connected_by",
            "created_at",
        ]
        read_only_fields = fields

    def get_webhook_installed(self, obj):
        return obj.webhook_id is not None


# owner/repo as GitHub allows them. The name is spliced into API URLs, so "." and ".." (path traversal)
# and anything outside GitHub's own character set are refused outright.
REPO_FULL_NAME = r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/(?!\.{1,2}$)[A-Za-z0-9._-]{1,100}$"


class GitHubImportSerializer(serializers.Serializer):
    workspace = serializers.IntegerField()
    github_repo_id = serializers.IntegerField(min_value=1)
    full_name = serializers.RegexField(regex=REPO_FULL_NAME, max_length=140)
    import_issues = serializers.BooleanField(required=False, default=True)


class GitHubRepositoryLinkCreateSerializer(serializers.Serializer):
    github_repo_id = serializers.IntegerField(min_value=1)
    full_name = serializers.RegexField(regex=REPO_FULL_NAME, max_length=140)


class GitHubPullRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = GitHubPullRequest
        fields = [
            "id",
            "number",
            "title",
            "state",
            "merged",
            "author_username",
            "url",
            "head_ref",
            "base_ref",
            "draft",
            "opened_at",
            "merged_at",
            "closed_at",
            "created_at",
            "updated_at",
        ]


class GitHubCommitSerializer(serializers.ModelSerializer):
    class Meta:
        model = GitHubCommit
        fields = ["id", "sha", "message", "author_username", "author_name", "url", "branch", "committed_at", "created_at"]

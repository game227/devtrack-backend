from rest_framework import serializers

from apps.workspaces.serializers import UserBriefSerializer

from .models import GitHubCommit, GitHubPullRequest, GitHubRepositoryLink


class GitHubRepositoryLinkSerializer(serializers.ModelSerializer):
    connected_by = UserBriefSerializer(read_only=True)

    class Meta:
        model = GitHubRepositoryLink
        fields = ["id", "project", "github_repo_id", "full_name", "connected_by", "created_at"]
        read_only_fields = fields


class GitHubRepositoryLinkCreateSerializer(serializers.Serializer):
    github_repo_id = serializers.IntegerField()
    full_name = serializers.RegexField(regex=r"^[\w.-]+/[\w.-]+$", max_length=255)


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
            "created_at",
            "updated_at",
        ]


class GitHubCommitSerializer(serializers.ModelSerializer):
    class Meta:
        model = GitHubCommit
        fields = ["id", "sha", "message", "author_username", "author_name", "url", "created_at"]

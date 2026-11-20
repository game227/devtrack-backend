from django.contrib import admin
from django.utils.html import format_html

from apps.adminui.display import chip, excerpt, key

from .models import GitHubAccount, GitHubCommit, GitHubPullRequest, GitHubRepositoryLink


@admin.register(GitHubAccount)
class GitHubAccountAdmin(admin.ModelAdmin):
    list_display = ["user", "github_username", "connected_at"]
    exclude = ["access_token"]


@admin.register(GitHubRepositoryLink)
class GitHubRepositoryLinkAdmin(admin.ModelAdmin):
    list_display = ["full_name", "project", "default_branch", "last_event_at", "last_synced_at"]
    search_fields = ["full_name", "project__name"]
    list_select_related = ["project"]
    raw_id_fields = ["project", "connected_by"]


@admin.register(GitHubPullRequest)
class GitHubPullRequestAdmin(admin.ModelAdmin):
    list_display = ["pr_key", "title", "repo_link", "state_chip", "author_username", "opened_at"]
    list_display_links = ["pr_key", "title"]
    list_filter = ["state", "merged", "draft"]
    search_fields = ["title", "author_username", "head_ref"]
    list_select_related = ["repo_link"]
    raw_id_fields = ["repo_link"]
    filter_horizontal = ["issues"]

    @admin.display(description="#", ordering="number")
    def pr_key(self, obj):
        return key(obj.number)

    @admin.display(description="State", ordering="state")
    def state_chip(self, obj):
        if obj.merged:
            return chip("dt-st-in_review", "Merged")
        return chip("dt-tone-success" if obj.state == "open" else "dt-tone-danger", obj.state.capitalize())


@admin.register(GitHubCommit)
class GitHubCommitAdmin(admin.ModelAdmin):
    list_display = ["short_sha", "short_message", "repo_link", "author_username", "branch", "committed_at"]
    search_fields = ["sha", "message", "author_username", "branch"]
    list_select_related = ["repo_link"]
    raw_id_fields = ["repo_link"]
    filter_horizontal = ["issues"]

    @admin.display(description="Commit", ordering="sha")
    def short_sha(self, obj):
        return format_html('<span class="dt-key">{}</span>', obj.sha[:7])

    @admin.display(description="Message")
    def short_message(self, obj):
        return excerpt(obj.message.splitlines()[0] if obj.message else "")

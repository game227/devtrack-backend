from django.contrib import admin

from .models import GitHubAccount, GitHubCommit, GitHubPullRequest, GitHubRepositoryLink


@admin.register(GitHubAccount)
class GitHubAccountAdmin(admin.ModelAdmin):
    list_display = ["user", "github_username", "connected_at"]
    exclude = ["access_token"]


admin.site.register(GitHubRepositoryLink)
admin.site.register(GitHubPullRequest)
admin.site.register(GitHubCommit)

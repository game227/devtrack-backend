from django.urls import path

from .views import (
    GitHubCallbackView,
    GitHubCompleteView,
    GitHubConnectView,
    GitHubDisconnectView,
    GitHubImportView,
    GitHubRepoListView,
    GitHubStatusView,
    GitHubWebhookView,
    IssueGitHubLinksView,
    ProjectGitHubLinkView,
    ProjectGitHubSyncView,
)

urlpatterns = [
    path("github/connect/", GitHubConnectView.as_view(), name="github-connect"),
    path("github/callback/", GitHubCallbackView.as_view(), name="github-callback"),
    path("github/complete/", GitHubCompleteView.as_view(), name="github-complete"),
    path("github/status/", GitHubStatusView.as_view(), name="github-status"),
    path("github/disconnect/", GitHubDisconnectView.as_view(), name="github-disconnect"),
    path("github/repos/", GitHubRepoListView.as_view(), name="github-repo-list"),
    path("github/webhook/", GitHubWebhookView.as_view(), name="github-webhook"),
    path("github/import/", GitHubImportView.as_view(), name="github-import"),
    path("projects/<int:project_id>/github-link/", ProjectGitHubLinkView.as_view(), name="project-github-link"),
    path("projects/<int:project_id>/github-sync/", ProjectGitHubSyncView.as_view(), name="project-github-sync"),
    path("issues/<int:issue_id>/github-links/", IssueGitHubLinksView.as_view(), name="issue-github-links"),
]

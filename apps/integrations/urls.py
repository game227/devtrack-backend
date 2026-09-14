from django.urls import path

from .views import (
    GitHubCallbackView,
    GitHubConnectView,
    GitHubDisconnectView,
    GitHubRepoListView,
    GitHubStatusView,
    GitHubWebhookView,
    IssueGitHubLinksView,
    ProjectGitHubLinkView,
)

urlpatterns = [
    path("github/connect/", GitHubConnectView.as_view(), name="github-connect"),
    path("github/callback/", GitHubCallbackView.as_view(), name="github-callback"),
    path("github/status/", GitHubStatusView.as_view(), name="github-status"),
    path("github/disconnect/", GitHubDisconnectView.as_view(), name="github-disconnect"),
    path("github/repos/", GitHubRepoListView.as_view(), name="github-repo-list"),
    path("github/webhook/", GitHubWebhookView.as_view(), name="github-webhook"),
    path("projects/<int:project_id>/github-link/", ProjectGitHubLinkView.as_view(), name="project-github-link"),
    path("issues/<int:issue_id>/github-links/", IssueGitHubLinksView.as_view(), name="issue-github-links"),
]

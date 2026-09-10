from django.urls import path

from apps.comments.views import IssueCommentsView

from .views import IssueDetailView, IssueListCreateView

urlpatterns = [
    path("", IssueListCreateView.as_view(), name="issue-list"),
    path("<int:pk>/", IssueDetailView.as_view(), name="issue-detail"),
    path("<int:pk>/comments/", IssueCommentsView.as_view(), name="issue-comments"),
]

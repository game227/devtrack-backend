from django.urls import path

from apps.comments.views import IssueCommentsView

from .views import (
    ChecklistItemDetailView,
    ChecklistListCreateView,
    IssueDetailView,
    IssueExportView,
    IssueListCreateView,
    IssueRelationDetailView,
    IssueRelationListCreateView,
    SavedViewDetailView,
    SavedViewListCreateView,
)

urlpatterns = [
    path("", IssueListCreateView.as_view(), name="issue-list"),
    path("export/", IssueExportView.as_view(), name="issue-export"),
    path("views/", SavedViewListCreateView.as_view(), name="saved-view-list"),
    path("views/<int:pk>/", SavedViewDetailView.as_view(), name="saved-view-detail"),
    path("<int:pk>/", IssueDetailView.as_view(), name="issue-detail"),
    path("<int:pk>/comments/", IssueCommentsView.as_view(), name="issue-comments"),
    path("<int:issue_pk>/checklist/", ChecklistListCreateView.as_view(), name="issue-checklist"),
    path("checklist/<int:pk>/", ChecklistItemDetailView.as_view(), name="checklist-item"),
    path("<int:issue_pk>/relations/", IssueRelationListCreateView.as_view(), name="issue-relations"),
    path("relations/<int:pk>/", IssueRelationDetailView.as_view(), name="issue-relation"),
]

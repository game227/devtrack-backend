from django.urls import path

from apps.comments.views import IssueCommentsView

from .tools import (
    BulkUpdateView,
    PublicIssueView,
    RecurringDetailView,
    RecurringListCreateView,
    ShareLinkRevokeView,
    ShareLinksView,
    TimeEntriesView,
    TimeEntryDeleteView,
)
from .views import (
    ChecklistItemDetailView,
    ChecklistListCreateView,
    IssueAttachmentDetailView,
    IssueAttachmentDownloadView,
    IssueAttachmentListCreateView,
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
    path("bulk/", BulkUpdateView.as_view(), name="issue-bulk"),
    path("shared/<str:token>/", PublicIssueView.as_view(), name="issue-public"),
    path("share-links/<int:pk>/", ShareLinkRevokeView.as_view(), name="issue-share-link"),
    path("time/<int:pk>/", TimeEntryDeleteView.as_view(), name="issue-time-entry"),
    path("recurring/project/<int:project_pk>/", RecurringListCreateView.as_view(), name="recurring-list"),
    path("recurring/<int:pk>/", RecurringDetailView.as_view(), name="recurring-detail"),
    path("views/", SavedViewListCreateView.as_view(), name="saved-view-list"),
    path("views/<int:pk>/", SavedViewDetailView.as_view(), name="saved-view-detail"),
    path("<int:pk>/", IssueDetailView.as_view(), name="issue-detail"),
    path("<int:pk>/comments/", IssueCommentsView.as_view(), name="issue-comments"),
    path("<int:pk>/share/", ShareLinksView.as_view(), name="issue-share"),
    path("<int:pk>/time/", TimeEntriesView.as_view(), name="issue-time"),
    path("<int:issue_pk>/checklist/", ChecklistListCreateView.as_view(), name="issue-checklist"),
    path("checklist/<int:pk>/", ChecklistItemDetailView.as_view(), name="checklist-item"),
    path("<int:issue_pk>/relations/", IssueRelationListCreateView.as_view(), name="issue-relations"),
    path("relations/<int:pk>/", IssueRelationDetailView.as_view(), name="issue-relation"),
    path("<int:issue_pk>/attachments/", IssueAttachmentListCreateView.as_view(), name="issue-attachments"),
    path("attachments/<int:pk>/", IssueAttachmentDetailView.as_view(), name="issue-attachment"),
    path("attachments/<int:pk>/download/", IssueAttachmentDownloadView.as_view(), name="issue-attachment-download"),
]

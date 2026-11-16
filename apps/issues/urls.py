from django.urls import path

from apps.comments.views import IssueCommentsView

from .views import IssueDetailView, IssueExportView, IssueListCreateView, SavedViewDetailView, SavedViewListCreateView

urlpatterns = [
    path("", IssueListCreateView.as_view(), name="issue-list"),
    path("export/", IssueExportView.as_view(), name="issue-export"),
    path("views/", SavedViewListCreateView.as_view(), name="saved-view-list"),
    path("views/<int:pk>/", SavedViewDetailView.as_view(), name="saved-view-detail"),
    path("<int:pk>/", IssueDetailView.as_view(), name="issue-detail"),
    path("<int:pk>/comments/", IssueCommentsView.as_view(), name="issue-comments"),
]

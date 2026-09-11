from django.urls import path

from apps.analytics.views import ProjectHealthView
from apps.comments.views import ProjectCommentsView

from .views import (
    ProjectDetailView,
    ProjectListCreateView,
    ProjectMemberDetailView,
    ProjectMembersView,
    ProjectNotesView,
)

urlpatterns = [
    path("", ProjectListCreateView.as_view(), name="project-list"),
    path("<int:pk>/", ProjectDetailView.as_view(), name="project-detail"),
    path("<int:pk>/members/", ProjectMembersView.as_view(), name="project-members"),
    path(
        "<int:pk>/members/<int:user_id>/",
        ProjectMemberDetailView.as_view(),
        name="project-member-detail",
    ),
    path("<int:pk>/comments/", ProjectCommentsView.as_view(), name="project-comments"),
    path("<int:pk>/notes/", ProjectNotesView.as_view(), name="project-notes"),
    path("<int:pk>/health/", ProjectHealthView.as_view(), name="project-health"),
]

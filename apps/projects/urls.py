from django.urls import path

from .views import (
    ProjectDetailView,
    ProjectListCreateView,
    ProjectMemberDetailView,
    ProjectMembersView,
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
]

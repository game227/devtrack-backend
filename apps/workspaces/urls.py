from django.urls import path

from .views import (
    WorkspaceDetailView,
    WorkspaceListCreateView,
    WorkspaceMemberDetailView,
    WorkspaceMembersView,
)

urlpatterns = [
    path("", WorkspaceListCreateView.as_view(), name="workspace-list"),
    path("<int:pk>/", WorkspaceDetailView.as_view(), name="workspace-detail"),
    path("<int:pk>/members/", WorkspaceMembersView.as_view(), name="workspace-members"),
    path(
        "<int:pk>/members/<int:user_id>/",
        WorkspaceMemberDetailView.as_view(),
        name="workspace-member-detail",
    ),
]

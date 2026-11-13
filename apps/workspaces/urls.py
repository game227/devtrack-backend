from django.urls import path

from .views import (
    InvitationResponseView,
    MyInvitationsView,
    WorkspaceDetailView,
    WorkspaceInvitationDetailView,
    WorkspaceInvitationsView,
    WorkspaceLeaveView,
    WorkspaceListCreateView,
    WorkspaceMemberDetailView,
    WorkspaceMembersView,
    WorkspaceTransferOwnershipView,
)

urlpatterns = [
    path("", WorkspaceListCreateView.as_view(), name="workspace-list"),
    path("invitations/", MyInvitationsView.as_view(), name="my-invitations"),
    path(
        "invitations/<int:invitation_id>/accept/",
        InvitationResponseView.as_view(accept=True),
        name="invitation-accept",
    ),
    path(
        "invitations/<int:invitation_id>/decline/",
        InvitationResponseView.as_view(accept=False),
        name="invitation-decline",
    ),
    path("<int:pk>/invitations/", WorkspaceInvitationsView.as_view(), name="workspace-invitations"),
    path("<int:pk>/leave/", WorkspaceLeaveView.as_view(), name="workspace-leave"),
    path("<int:pk>/transfer-ownership/", WorkspaceTransferOwnershipView.as_view(), name="workspace-transfer-ownership"),
    path(
        "<int:pk>/invitations/<int:invitation_id>/",
        WorkspaceInvitationDetailView.as_view(),
        name="workspace-invitation-detail",
    ),
    path("<int:pk>/", WorkspaceDetailView.as_view(), name="workspace-detail"),
    path("<int:pk>/members/", WorkspaceMembersView.as_view(), name="workspace-members"),
    path(
        "<int:pk>/members/<int:user_id>/",
        WorkspaceMemberDetailView.as_view(),
        name="workspace-member-detail",
    ),
]

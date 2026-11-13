from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.throttling import MemberAddRateThrottle

from .models import Invitation, Membership, Workspace
from .permissions import IsWorkspaceAdminOrOwner, IsWorkspaceMember, IsWorkspaceOwner
from .serializers import (
    InvitationSerializer,
    MembershipCreateSerializer,
    MembershipSerializer,
    WorkspaceSerializer,
)

User = get_user_model()


class WorkspaceListCreateView(generics.ListCreateAPIView):
    serializer_class = WorkspaceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Workspace.objects.filter(memberships__user=self.request.user).order_by("-created_at")

    def perform_create(self, serializer):
        workspace = serializer.save(owner=self.request.user)
        Membership.objects.create(workspace=workspace, user=self.request.user, role=Membership.Role.OWNER)


class WorkspaceDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Workspace.objects.all()
    serializer_class = WorkspaceSerializer

    def get_permissions(self):
        if self.request.method == "DELETE":
            return [IsAuthenticated(), IsWorkspaceOwner()]
        if self.request.method in ("PUT", "PATCH"):
            return [IsAuthenticated(), IsWorkspaceAdminOrOwner()]
        return [IsAuthenticated(), IsWorkspaceMember()]


class WorkspaceMembersView(generics.ListCreateAPIView):
    serializer_class = MembershipSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsWorkspaceAdminOrOwner()]
        return [IsAuthenticated(), IsWorkspaceMember()]

    def get_throttles(self):
        throttles = super().get_throttles()
        return throttles + [MemberAddRateThrottle()] if self.request.method == "POST" else throttles

    def get_workspace(self):
        workspace = get_object_or_404(Workspace, pk=self.kwargs["pk"])
        self.check_object_permissions(self.request, workspace)
        return workspace

    def get_queryset(self):
        workspace = self.get_workspace()
        return Membership.objects.filter(workspace=workspace).select_related("user")

    def create(self, request, *args, **kwargs):
        # Adding someone sends an invitation: they only join (and see the workspace) once they accept.
        workspace = self.get_workspace()
        serializer = MembershipCreateSerializer(
            data=request.data, context={"workspace": workspace, "invited_by": request.user}
        )
        serializer.is_valid(raise_exception=True)
        invitation = serializer.save()
        return Response(InvitationSerializer(invitation).data, status=status.HTTP_201_CREATED)


class WorkspaceMemberDetailView(APIView):
    permission_classes = [IsAuthenticated, IsWorkspaceAdminOrOwner]

    def delete(self, request, pk, user_id):
        workspace = get_object_or_404(Workspace, pk=pk)
        self.check_object_permissions(request, workspace)
        membership = get_object_or_404(Membership, workspace=workspace, user_id=user_id)

        if membership.role == Membership.Role.OWNER:
            return Response(
                {"detail": "The workspace owner cannot be removed."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        membership.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkspaceInvitationsView(generics.ListAPIView):
    """Pending invitations of a workspace (admins and owners)."""

    serializer_class = InvitationSerializer
    permission_classes = [IsAuthenticated, IsWorkspaceAdminOrOwner]

    def get_queryset(self):
        workspace = get_object_or_404(Workspace, pk=self.kwargs["pk"])
        self.check_object_permissions(self.request, workspace)
        return Invitation.objects.filter(workspace=workspace).select_related("workspace", "user", "invited_by")


class WorkspaceInvitationDetailView(APIView):
    """An admin or owner withdraws a pending invitation."""

    permission_classes = [IsAuthenticated, IsWorkspaceAdminOrOwner]

    def delete(self, request, pk, invitation_id):
        workspace = get_object_or_404(Workspace, pk=pk)
        self.check_object_permissions(request, workspace)
        get_object_or_404(Invitation, pk=invitation_id, workspace=workspace).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyInvitationsView(generics.ListAPIView):
    """The invitations waiting for the signed-in user."""

    serializer_class = InvitationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            Invitation.objects.valid()
            .filter(user=self.request.user)
            .select_related("workspace", "user", "invited_by")
        )


class InvitationResponseView(APIView):
    """The invitee accepts (becomes a member with the offered role) or declines. Only the invitee can."""

    permission_classes = [IsAuthenticated]
    accept = False

    def post(self, request, invitation_id):
        # 404 for anyone else's invitation: its existence is not theirs to know.
        invitation = get_object_or_404(Invitation, pk=invitation_id, user=request.user)
        if self.accept and not Invitation.objects.valid().filter(pk=invitation.pk).exists():
            # Expired, or whoever sent it is no longer an admin here: it cannot grant anything any more.
            invitation.delete()
            return Response({"detail": "This invitation is no longer valid."}, status=status.HTTP_404_NOT_FOUND)
        with transaction.atomic():
            if self.accept:
                membership, _ = Membership.objects.get_or_create(
                    workspace=invitation.workspace, user=request.user, defaults={"role": invitation.role}
                )
            invitation.delete()
        if self.accept:
            return Response(MembershipSerializer(membership).data, status=status.HTTP_201_CREATED)
        return Response(status=status.HTTP_204_NO_CONTENT)

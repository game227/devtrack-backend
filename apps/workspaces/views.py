from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.throttling import MemberAddRateThrottle
from apps.common.lookup import body_value, parse_id

from .membership import end_membership, record, transfer_ownership
from .models import Invitation, Membership, Workspace
from .permissions import IsWorkspaceAdminOrOwner, IsWorkspaceMember, IsWorkspaceOwner, get_membership
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
            data=request.data,
            context={
                "workspace": workspace,
                "invited_by": request.user,
                "inviter_role": get_membership(request.user, workspace).role,
            },
        )
        serializer.is_valid(raise_exception=True)
        invitation = serializer.save()
        return Response(InvitationSerializer(invitation).data, status=status.HTTP_201_CREATED)


class WorkspaceMemberDetailView(APIView):
    """PATCH changes someone's role (owner only); DELETE removes them (see the table in membership.py)."""

    permission_classes = [IsAuthenticated, IsWorkspaceAdminOrOwner]

    def get_target(self, request, pk, user_id):
        workspace = get_object_or_404(Workspace, pk=pk)
        self.check_object_permissions(request, workspace)
        mine = get_membership(request.user, workspace)
        target = get_object_or_404(Membership.objects.select_related("user"), workspace=workspace, user_id=user_id)
        return workspace, mine, target

    def patch(self, request, pk, user_id):
        workspace, mine, target = self.get_target(request, pk, user_id)
        if mine.role != Membership.Role.OWNER:
            return Response({"detail": "Only the owner can change roles."}, status=status.HTTP_403_FORBIDDEN)
        role = request.data.get("role") if hasattr(request.data, "get") else None
        if role not in (Membership.Role.ADMIN, Membership.Role.MEMBER):
            return Response({"role": ["Choose admin or member."]}, status=status.HTTP_400_BAD_REQUEST)
        if target.role == Membership.Role.OWNER:
            return Response(
                {"detail": "The owner's role changes only by handing the workspace over."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if target.role != role:
            previous = target.role
            target.role = role
            target.save(update_fields=["role"])
            record(workspace, request.user, "role_changed", target.user, role=role, previous=previous)
        return Response(MembershipSerializer(target).data)

    def delete(self, request, pk, user_id):
        workspace, mine, target = self.get_target(request, pk, user_id)
        if target.role == Membership.Role.OWNER:
            return Response({"detail": "The workspace owner cannot be removed."}, status=status.HTTP_400_BAD_REQUEST)
        if target.user_id == request.user.id:
            return Response({"detail": "Use leave to leave a workspace."}, status=status.HTTP_400_BAD_REQUEST)
        if mine.role == Membership.Role.ADMIN and target.role != Membership.Role.MEMBER:
            return Response({"detail": "Admins can remove members only."}, status=status.HTTP_403_FORBIDDEN)
        end_membership(target, request.user, "member_removed")
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkspaceLeaveView(APIView):
    """A member or admin leaves; the owner has to hand the workspace over first."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        workspace = get_object_or_404(Workspace, pk=pk)
        membership = get_membership(request.user, workspace)
        if membership is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        if membership.role == Membership.Role.OWNER:
            return Response(
                {"detail": "Hand the workspace over to someone else before leaving it."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        end_membership(membership, request.user, "member_left")
        return Response(status=status.HTTP_204_NO_CONTENT)


class WorkspaceTransferOwnershipView(APIView):
    """The owner hands the workspace to another member, and stays on as an admin."""

    permission_classes = [IsAuthenticated, IsWorkspaceOwner]

    def post(self, request, pk):
        workspace = get_object_or_404(Workspace, pk=pk)
        self.check_object_permissions(request, workspace)
        if workspace.is_personal:
            return Response({"detail": "A personal workspace cannot change hands."}, status=status.HTTP_400_BAD_REQUEST)
        user_id = parse_id(body_value(request, "user_id"), "user_id")
        target = Membership.objects.filter(workspace=workspace, user_id=user_id, user__is_active=True).first()
        if target is None or target.user_id == request.user.id:
            return Response({"user_id": ["Choose another member of this workspace."]}, status=status.HTTP_400_BAD_REQUEST)
        transfer_ownership(workspace, request.user, target)
        return Response(MembershipSerializer(target).data)


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
                membership, joined = Membership.objects.get_or_create(
                    workspace=invitation.workspace, user=request.user, defaults={"role": invitation.role}
                )
                if joined:
                    record(invitation.workspace, request.user, "member_joined", request.user, role=membership.role)
            invitation.delete()
        if self.accept:
            return Response(MembershipSerializer(membership).data, status=status.HTTP_201_CREATED)
        return Response(status=status.HTTP_204_NO_CONTENT)

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Membership, Workspace
from .permissions import IsWorkspaceAdminOrOwner, IsWorkspaceMember, IsWorkspaceOwner
from .serializers import MembershipCreateSerializer, MembershipSerializer, WorkspaceSerializer

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

    def get_workspace(self):
        workspace = get_object_or_404(Workspace, pk=self.kwargs["pk"])
        self.check_object_permissions(self.request, workspace)
        return workspace

    def get_queryset(self):
        workspace = self.get_workspace()
        return Membership.objects.filter(workspace=workspace).select_related("user")

    def create(self, request, *args, **kwargs):
        workspace = self.get_workspace()
        serializer = MembershipCreateSerializer(data=request.data, context={"workspace": workspace})
        serializer.is_valid(raise_exception=True)
        membership = serializer.save()
        return Response(MembershipSerializer(membership).data, status=status.HTTP_201_CREATED)


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

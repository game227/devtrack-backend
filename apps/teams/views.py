from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.throttling import MemberAddRateThrottle
from apps.common.lookup import body_value, parse_id
from apps.workspaces.models import Workspace
from apps.workspaces.permissions import get_membership

from .models import Team, TeamMembership
from .serializers import TeamMembershipCreateSerializer, TeamMembershipSerializer, TeamSerializer


def _require_workspace_member(user, workspace):
    if get_membership(user, workspace) is None:
        raise PermissionDenied("You are not a member of this workspace.")


def _require_workspace_admin(user, workspace):
    membership = get_membership(user, workspace)
    if membership is None or membership.role not in ("owner", "admin"):
        raise PermissionDenied("Only a workspace admin/owner can do that.")


class TeamListCreateView(generics.ListCreateAPIView):
    serializer_class = TeamSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        workspace_id = self.request.query_params.get("workspace")
        if not workspace_id:
            raise ValidationError({"workspace": "This query parameter is required."})
        workspace = get_object_or_404(Workspace, pk=parse_id(workspace_id, "workspace"))
        _require_workspace_member(self.request.user, workspace)
        return Team.objects.filter(workspace=workspace)

    def get_target_workspace(self):
        if not hasattr(self, "_target_workspace"):
            workspace = get_object_or_404(Workspace, pk=parse_id(body_value(self.request, "workspace"), "workspace"))
            _require_workspace_admin(self.request.user, workspace)
            self._target_workspace = workspace
        return self._target_workspace

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.method == "POST":
            context["workspace"] = self.get_target_workspace()
        return context

    def perform_create(self, serializer):
        team = serializer.save(workspace=self.get_target_workspace())
        TeamMembership.objects.create(team=team, user=self.request.user)


class TeamDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Team.objects.all()
    serializer_class = TeamSerializer
    permission_classes = [IsAuthenticated]

    def check_object_permissions(self, request, obj):
        super().check_object_permissions(request, obj)
        if request.method in ("PUT", "PATCH", "DELETE"):
            _require_workspace_admin(request.user, obj.workspace)
        else:
            _require_workspace_member(request.user, obj.workspace)


class TeamMembersView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]

    def get_team(self):
        team = get_object_or_404(Team, pk=self.kwargs["pk"])
        if self.request.method == "POST":
            _require_workspace_admin(self.request.user, team.workspace)
        else:
            _require_workspace_member(self.request.user, team.workspace)
        return team

    def get_serializer_class(self):
        return TeamMembershipSerializer

    def get_throttles(self):
        throttles = super().get_throttles()
        return throttles + [MemberAddRateThrottle()] if self.request.method == "POST" else throttles

    def get_queryset(self):
        team = self.get_team()
        return TeamMembership.objects.filter(team=team).select_related("user")

    def create(self, request, *args, **kwargs):
        team = self.get_team()
        serializer = TeamMembershipCreateSerializer(data=request.data, context={"team": team})
        serializer.is_valid(raise_exception=True)
        membership = serializer.save()
        return Response(TeamMembershipSerializer(membership).data, status=status.HTTP_201_CREATED)


class TeamMemberDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk, user_id):
        team = get_object_or_404(Team, pk=pk)
        _require_workspace_admin(request.user, team.workspace)
        membership = get_object_or_404(TeamMembership, team=team, user_id=user_id)
        membership.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.common.lookup import body_value, parse_id
from apps.projects.models import Project
from apps.workspaces.permissions import get_membership

from .burndown import burndown
from .models import Cycle
from .serializers import CycleSerializer


class CycleListCreateView(generics.ListCreateAPIView):
    serializer_class = CycleSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        project_id = self.request.query_params.get("project")
        if not project_id:
            raise ValidationError({"project": "This query parameter is required."})
        project = get_object_or_404(Project, pk=parse_id(project_id, "project"))
        if get_membership(self.request.user, project.workspace) is None:
            raise PermissionDenied("You are not a member of this project's workspace.")
        return Cycle.objects.filter(project=project)

    def perform_create(self, serializer):
        project = get_object_or_404(Project, pk=parse_id(body_value(self.request, "project"), "project"))
        if get_membership(self.request.user, project.workspace) is None:
            raise PermissionDenied("You are not a member of this project's workspace.")
        serializer.save(project=project)


class CycleDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Cycle.objects.all()
    serializer_class = CycleSerializer
    permission_classes = [IsAuthenticated]

    def check_object_permissions(self, request, obj):
        super().check_object_permissions(request, obj)
        if get_membership(request.user, obj.project.workspace) is None:
            raise PermissionDenied("You are not a member of this project's workspace.")


class CycleBurndownView(generics.GenericAPIView):
    """GET: remaining work per day of the cycle, with the ideal straight line (see burndown.py)."""

    queryset = Cycle.objects.select_related("project__workspace")
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        cycle = get_object_or_404(self.get_queryset(), pk=pk)
        if get_membership(request.user, cycle.project.workspace) is None:
            raise NotFound()
        return Response(burndown(cycle))

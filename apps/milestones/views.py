from django.shortcuts import get_object_or_404
from rest_framework import generics
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated

from apps.projects.models import Project
from apps.workspaces.permissions import get_membership

from .models import Milestone
from .serializers import MilestoneSerializer


class MilestoneListCreateView(generics.ListCreateAPIView):
    serializer_class = MilestoneSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        project_id = self.request.query_params.get("project")
        if not project_id:
            raise ValidationError({"project": "This query parameter is required."})
        project = get_object_or_404(Project, pk=project_id)
        if get_membership(self.request.user, project.workspace) is None:
            raise PermissionDenied("You are not a member of this project's workspace.")
        return Milestone.objects.filter(project=project)

    def perform_create(self, serializer):
        project = get_object_or_404(Project, pk=self.request.data.get("project"))
        if get_membership(self.request.user, project.workspace) is None:
            raise PermissionDenied("You are not a member of this project's workspace.")
        serializer.save(project=project)


class MilestoneDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Milestone.objects.all()
    serializer_class = MilestoneSerializer
    permission_classes = [IsAuthenticated]

    def check_object_permissions(self, request, obj):
        super().check_object_permissions(request, obj)
        if get_membership(request.user, obj.project.workspace) is None:
            raise PermissionDenied("You are not a member of this project's workspace.")

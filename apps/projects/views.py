from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.throttling import MemberAddRateThrottle
from apps.common.lookup import body_value, parse_id
from apps.workspaces.models import Membership, Workspace
from apps.workspaces.permissions import get_membership

from .models import Label, Note, Project, ProjectMember
from .permissions import CanManageProject, IsProjectWorkspaceMember
from .serializers import (
    LabelSerializer,
    NoteSerializer,
    ProjectMemberCreateSerializer,
    ProjectMemberSerializer,
    ProjectMemberUpdateSerializer,
    ProjectSerializer,
)


class ProjectListCreateView(generics.ListCreateAPIView):
    serializer_class = ProjectSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["status", "priority"]

    def get_queryset(self):
        workspace_id = self.request.query_params.get("workspace")
        if not workspace_id:
            raise ValidationError({"workspace": "This query parameter is required."})
        workspace = get_object_or_404(Workspace, pk=parse_id(workspace_id, "workspace"))
        if get_membership(self.request.user, workspace) is None:
            raise PermissionDenied("You are not a member of this workspace.")
        return Project.objects.filter(workspace=workspace).select_related("owner").order_by("-created_at")

    def get_target_workspace(self):
        """The workspace a new project goes into, resolved and authorized before the body is validated."""
        if not hasattr(self, "_target_workspace"):
            workspace = get_object_or_404(Workspace, pk=parse_id(body_value(self.request, "workspace"), "workspace"))
            if get_membership(self.request.user, workspace) is None:
                raise PermissionDenied("You are not a member of this workspace.")
            self._target_workspace = workspace
        return self._target_workspace

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.method == "POST":
            context["workspace"] = self.get_target_workspace()
        return context

    def perform_create(self, serializer):
        project = serializer.save(workspace=self.get_target_workspace(), owner=self.request.user)
        ProjectMember.objects.create(project=project, user=self.request.user, role="owner")


class ProjectDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Project.objects.select_related("owner", "workspace").all()
    serializer_class = ProjectSerializer

    def get_permissions(self):
        if self.request.method in ("PUT", "PATCH", "DELETE"):
            return [IsAuthenticated(), CanManageProject()]
        return [IsAuthenticated(), IsProjectWorkspaceMember()]


class ProjectMembersView(generics.ListCreateAPIView):
    serializer_class = ProjectMemberSerializer

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), CanManageProject()]
        return [IsAuthenticated(), IsProjectWorkspaceMember()]

    def get_throttles(self):
        throttles = super().get_throttles()
        return throttles + [MemberAddRateThrottle()] if self.request.method == "POST" else throttles

    def get_project(self):
        project = get_object_or_404(Project, pk=self.kwargs["pk"])
        self.check_object_permissions(self.request, project)
        return project

    def get_queryset(self):
        project = self.get_project()
        return ProjectMember.objects.filter(project=project).select_related("user")

    def create(self, request, *args, **kwargs):
        project = self.get_project()
        serializer = ProjectMemberCreateSerializer(data=request.data, context={"project": project})
        serializer.is_valid(raise_exception=True)
        member = serializer.save()
        return Response(ProjectMemberSerializer(member).data, status=status.HTTP_201_CREATED)


class ProjectMemberDetailView(APIView):
    permission_classes = [IsAuthenticated, CanManageProject]

    def patch(self, request, pk, user_id):
        project = get_object_or_404(Project, pk=pk)
        self.check_object_permissions(request, project)
        member = get_object_or_404(ProjectMember, project=project, user_id=user_id)
        serializer = ProjectMemberUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        member.specialty = serializer.validated_data["specialty"]
        member.save(update_fields=["specialty"])
        return Response(ProjectMemberSerializer(member).data)

    def delete(self, request, pk, user_id):
        project = get_object_or_404(Project, pk=pk)
        self.check_object_permissions(request, project)
        member = get_object_or_404(ProjectMember, project=project, user_id=user_id)
        member.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class LabelListCreateView(generics.ListCreateAPIView):
    serializer_class = LabelSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        workspace_id = self.request.query_params.get("workspace")
        project_id = self.request.query_params.get("project")
        if not workspace_id:
            raise ValidationError({"workspace": "This query parameter is required."})
        workspace = get_object_or_404(Workspace, pk=parse_id(workspace_id, "workspace"))
        if get_membership(self.request.user, workspace) is None:
            raise PermissionDenied("You are not a member of this workspace.")
        qs = Label.objects.filter(workspace=workspace)
        if project_id:
            qs = qs.filter(project_id=parse_id(project_id, "project"))
        return qs.order_by("name")

    def get_target_workspace(self):
        if not hasattr(self, "_target_workspace"):
            workspace = get_object_or_404(Workspace, pk=parse_id(body_value(self.request, "workspace"), "workspace"))
            if get_membership(self.request.user, workspace) is None:
                raise PermissionDenied("You are not a member of this workspace.")
            self._target_workspace = workspace
        return self._target_workspace

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.method == "POST":
            context["workspace"] = self.get_target_workspace()
        return context

    def perform_create(self, serializer):
        serializer.save(workspace=self.get_target_workspace())


class LabelDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Label.objects.select_related("workspace").all()
    serializer_class = LabelSerializer
    permission_classes = [IsAuthenticated]

    def check_object_permissions(self, request, obj):
        super().check_object_permissions(request, obj)
        membership = get_membership(request.user, obj.workspace)
        if membership is None:
            raise PermissionDenied("You are not a member of this workspace.")
        if request.method in ("PUT", "PATCH", "DELETE") and membership.role not in ("owner", "admin"):
            raise PermissionDenied("Only a workspace admin or owner can modify labels.")


class ProjectNotesView(generics.ListCreateAPIView):
    serializer_class = NoteSerializer
    permission_classes = [IsAuthenticated]

    def get_project(self):
        project = get_object_or_404(Project, pk=self.kwargs["pk"])
        if get_membership(self.request.user, project.workspace) is None:
            raise PermissionDenied("You are not a member of this project's workspace.")
        return project

    def get_queryset(self):
        return Note.objects.filter(project=self.get_project()).select_related("author")

    def perform_create(self, serializer):
        serializer.save(project=self.get_project(), author=self.request.user)


class NoteDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Note.objects.select_related("project__workspace", "author").all()
    serializer_class = NoteSerializer
    permission_classes = [IsAuthenticated]

    def check_object_permissions(self, request, obj):
        super().check_object_permissions(request, obj)
        workspace = obj.project.workspace
        membership = get_membership(request.user, workspace)
        if membership is None:
            raise PermissionDenied("You are not a member of this workspace.")
        if request.method in ("PUT", "PATCH", "DELETE"):
            is_author = obj.author_id == request.user.id
            is_admin = membership.role in (Membership.Role.OWNER, Membership.Role.ADMIN)
            if not (is_author or is_admin):
                raise PermissionDenied("Only the note's author or a workspace admin/owner can do that.")

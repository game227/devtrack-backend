from django.db import transaction
from django.db.models import Count, Max, Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from apps.common.filters import StableOrderingFilter
from apps.common.lookup import body_value, parse_id
from apps.live.models import touch
from apps.projects.models import Project
from apps.workspaces.models import Membership, Workspace
from apps.workspaces.permissions import get_membership

from .attachments import MAX_ATTACHMENTS_PER_ISSUE, check_upload
from .export import issues_csv_response
from .filters import IssueFilter
from .models import ChecklistItem, Issue, IssueAttachment, IssueRelation, SavedView
from .permissions import CanDeleteIssue, CanEditIssue, CanWorkOnIssue, IsIssueWorkspaceMember
from .serializers import (
    MAX_CHECKLIST_ITEMS,
    ChecklistItemSerializer,
    IssueAttachmentSerializer,
    IssueRelationSerializer,
    IssueSerializer,
    SavedViewSerializer,
)


def with_checklist_counts(queryset):
    return queryset.annotate(
        checklist_total=Count("checklist_items"),
        checklist_done=Count("checklist_items", filter=Q(checklist_items__done=True)),
    )


class IssueScopeMixin:
    """The issues of one project (?project=) or of a whole workspace (?workspace=), for its members only.

    Shared by the issue list and the CSV export, so both answer exactly the same filters.
    """

    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, StableOrderingFilter]
    filterset_class = IssueFilter
    ordering_fields = ["completed_at", "created_at", "updated_at", "number", "due_date"]

    def get_queryset(self):
        project_id = self.request.query_params.get("project")
        workspace_id = self.request.query_params.get("workspace")
        base = with_checklist_counts(Issue.objects.select_related("assignee", "reporter").prefetch_related("labels"))

        if project_id:
            project = get_object_or_404(Project, pk=parse_id(project_id, "project"))
            if get_membership(self.request.user, project.workspace) is None:
                raise PermissionDenied("You are not a member of this project's workspace.")
            return base.filter(project=project)

        if workspace_id:
            workspace = get_object_or_404(Workspace, pk=parse_id(workspace_id, "workspace"))
            if get_membership(self.request.user, workspace) is None:
                raise PermissionDenied("You are not a member of this workspace.")
            return base.filter(project__workspace=workspace)

        raise ValidationError({"project": "Either 'project' or 'workspace' query parameter is required."})


class IssueListCreateView(IssueScopeMixin, generics.ListCreateAPIView):
    serializer_class = IssueSerializer

    def get_target_project(self):
        """The project a new issue goes into, resolved and authorized *before* the body is validated."""
        if not hasattr(self, "_target_project"):
            project = get_object_or_404(
                Project.objects.select_related("workspace"),
                pk=parse_id(body_value(self.request, "project"), "project"),
            )
            if get_membership(self.request.user, project.workspace) is None:
                raise PermissionDenied("You are not a member of this project's workspace.")
            self._target_project = project
        return self._target_project

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.method == "POST":
            context["project"] = self.get_target_project()
        return context

    def perform_create(self, serializer):
        serializer.save(project=self.get_target_project(), reporter=self.request.user)


class IssueDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = with_checklist_counts(
        Issue.objects.select_related("assignee", "reporter", "project__workspace").prefetch_related("labels")
    )
    serializer_class = IssueSerializer

    def perform_update(self, serializer):
        # Lets the activity/notification signals attribute the change to whoever
        # made it rather than to the issue's original reporter.
        serializer.instance._actor = self.request.user
        serializer.save()

    def get_permissions(self):
        if self.request.method == "DELETE":
            return [IsAuthenticated(), CanDeleteIssue()]
        # Edits: the creator may change anything, the assignee only status and priority (see
        # CanEditIssue). Anyone in the workspace can still read the issue.
        if self.request.method in ("PUT", "PATCH"):
            return [IsAuthenticated(), CanEditIssue()]
        return [IsAuthenticated(), IsIssueWorkspaceMember()]


class IssueExportThrottle(UserRateThrottle):
    scope = "issue_export"


class IssueExportView(IssueScopeMixin, generics.GenericAPIView):
    """GET: the same issues the list would return (same filters), as a CSV file."""

    throttle_classes = [IssueExportThrottle]

    def get(self, request):
        queryset = self.filter_queryset(self.get_queryset())
        if request.query_params.get("project"):
            project = Project.objects.get(pk=parse_id(request.query_params["project"], "project"))
            scope_name = slugify(project.name) or f"project-{project.pk}"
        else:
            workspace = Workspace.objects.get(pk=parse_id(request.query_params["workspace"], "workspace"))
            scope_name = slugify(workspace.name) or f"workspace-{workspace.pk}"
        filename = f"{scope_name[:40]}-issues-{timezone.localdate():%Y-%m-%d}.csv"
        response = issues_csv_response(queryset, request.query_params.get("lang", "en"), filename)
        response["Cache-Control"] = "no-store"
        return response


class SavedViewListCreateView(generics.ListCreateAPIView):
    """Your saved filter sets for one workspace's list (?workspace=) or one project's list (?project=)."""

    serializer_class = SavedViewSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def _scope(self):
        if self.request.method == "GET":
            project_id = self.request.query_params.get("project")
            workspace_id = self.request.query_params.get("workspace")
        else:
            project_id = body_value(self.request, "project")
            workspace_id = body_value(self.request, "workspace")
        if project_id not in (None, ""):
            project = get_object_or_404(Project.objects.select_related("workspace"), pk=parse_id(project_id, "project"))
            workspace = project.workspace
        else:
            if workspace_id in (None, ""):
                raise ValidationError({"workspace": "Either 'project' or 'workspace' is required."})
            project = None
            workspace = get_object_or_404(Workspace, pk=parse_id(workspace_id, "workspace"))
        if get_membership(self.request.user, workspace) is None:
            raise PermissionDenied("You are not a member of this workspace.")
        return workspace, project

    def get_queryset(self):
        workspace, project = self._scope()
        return SavedView.objects.filter(owner=self.request.user, workspace=workspace, project=project)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.request.method == "POST":
            context["workspace"], context["project"] = self._scope()
        return context

    def perform_create(self, serializer):
        workspace, project = serializer.context["workspace"], serializer.context["project"]
        serializer.save(owner=self.request.user, workspace=workspace, project=project)


class SavedViewDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Rename, change or delete one of your own saved views. Other people's do not exist for you."""

    serializer_class = SavedViewSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "delete"]

    def get_queryset(self):
        return SavedView.objects.filter(owner=self.request.user).select_related("workspace", "project")


class IssueChildMixin:
    """Views of something that hangs off one issue (/issues/<issue_pk>/...), checked with CanWorkOnIssue."""

    permission_classes = [IsAuthenticated]

    def get_issue(self):
        if not hasattr(self, "_issue"):
            issue = get_object_or_404(Issue.objects.select_related("project__workspace"), pk=self.kwargs["issue_pk"])
            permission = CanWorkOnIssue()
            if not permission.has_object_permission(self.request, self, issue):
                if get_membership(self.request.user, issue.project.workspace) is None:
                    raise NotFound()
                raise PermissionDenied("Only the issue's creator or assignee can change this.")
            self._issue = issue
        return self._issue

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if "issue_pk" in self.kwargs:
            context["issue"] = self.get_issue()
        return context


class ChecklistListCreateView(IssueChildMixin, generics.ListCreateAPIView):
    serializer_class = ChecklistItemSerializer
    pagination_class = None

    def get_queryset(self):
        return ChecklistItem.objects.filter(issue=self.get_issue())

    def perform_create(self, serializer):
        issue = self.get_issue()
        with transaction.atomic():
            Issue.objects.select_for_update().filter(pk=issue.pk).first()
            items = ChecklistItem.objects.filter(issue=issue)
            if items.count() >= MAX_CHECKLIST_ITEMS:
                raise ValidationError(f"A checklist can hold up to {MAX_CHECKLIST_ITEMS} items.")
            position = (items.aggregate(top=Max("position"))["top"] or 0) + 1
            serializer.save(issue=issue, created_by=self.request.user, position=position)
        touch(issue.project.workspace_id, "issues")


class ChecklistItemDetailView(IssueChildMixin, generics.UpdateAPIView, generics.DestroyAPIView):
    serializer_class = ChecklistItemSerializer
    http_method_names = ["patch", "delete"]

    def get_object(self):
        item = get_object_or_404(ChecklistItem.objects.select_related("issue__project__workspace"), pk=self.kwargs["pk"])
        self.kwargs["issue_pk"] = item.issue_id
        self.get_issue()
        return item

    def get_serializer_context(self):
        return generics.GenericAPIView.get_serializer_context(self)

    def perform_update(self, serializer):
        serializer.save()
        touch(serializer.instance.issue.project.workspace_id, "issues")

    def perform_destroy(self, instance):
        workspace_id = instance.issue.project.workspace_id
        instance.delete()
        touch(workspace_id, "issues")


class IssueRelationListCreateView(IssueChildMixin, generics.ListCreateAPIView):
    serializer_class = IssueRelationSerializer
    pagination_class = None

    def get_queryset(self):
        issue = self.get_issue()
        return IssueRelation.objects.filter(Q(source=issue) | Q(target=issue)).select_related("source", "target")

    def perform_create(self, serializer):
        issue = self.get_issue()
        serializer.save(source=issue, created_by=self.request.user)
        touch(issue.project.workspace_id, "issues")


class IssueRelationDetailView(IssueChildMixin, generics.DestroyAPIView):
    """Remove a link. Either end's creator or assignee may, since it shows on both issues."""

    def get_object(self):
        relation = get_object_or_404(IssueRelation.objects.select_related("source__project__workspace", "target"), pk=self.kwargs["pk"])
        allowed = CanWorkOnIssue()
        if not any(allowed.has_object_permission(self.request, self, end) for end in (relation.source, relation.target)):
            if get_membership(self.request.user, relation.source.project.workspace) is None:
                raise NotFound()
            raise PermissionDenied("Only the creator or assignee of one of the issues can remove this link.")
        return relation

    def perform_destroy(self, instance):
        workspace_id = instance.source.project.workspace_id
        instance.delete()
        touch(workspace_id, "issues")


class AttachmentUploadThrottle(UserRateThrottle):
    scope = "attachment_upload"


def _member_issue(request, pk):
    issue = get_object_or_404(Issue.objects.select_related("project__workspace"), pk=pk)
    membership = get_membership(request.user, issue.project.workspace)
    if membership is None:
        raise NotFound()
    return issue, membership


class IssueAttachmentListCreateView(generics.ListCreateAPIView):
    """Files on an issue. Anyone in the workspace can see and add them, as with comments."""

    serializer_class = IssueAttachmentSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = None
    parser_classes = [MultiPartParser]

    def get_throttles(self):
        return [AttachmentUploadThrottle()] if self.request.method == "POST" else super().get_throttles()

    def get_queryset(self):
        issue, _ = _member_issue(self.request, self.kwargs["issue_pk"])
        return IssueAttachment.objects.filter(issue=issue).select_related("uploaded_by")

    def create(self, request, *args, **kwargs):
        issue, _ = _member_issue(request, self.kwargs["issue_pk"])
        upload = request.FILES.get("file")
        if upload is None:
            raise ValidationError({"file": "Choose a file to attach."})
        try:
            name, content_type = check_upload(upload)
        except ValidationError as error:
            raise ValidationError({"file": error.detail}) from error
        with transaction.atomic():
            Issue.objects.select_for_update().filter(pk=issue.pk).first()
            if IssueAttachment.objects.filter(issue=issue).count() >= MAX_ATTACHMENTS_PER_ISSUE:
                raise ValidationError({"file": f"An issue can hold up to {MAX_ATTACHMENTS_PER_ISSUE} files."})
            attachment = IssueAttachment.objects.create(
                issue=issue, file=upload, name=name, content_type=content_type, size=upload.size, uploaded_by=request.user
            )
        touch(issue.project.workspace_id, "issues")
        return Response(self.get_serializer(attachment).data, status=201)


class IssueAttachmentDetailView(generics.DestroyAPIView):
    """DELETE: by whoever uploaded it, the issue's creator, or a workspace admin/owner."""

    permission_classes = [IsAuthenticated]

    def get_object(self):
        attachment = get_object_or_404(IssueAttachment.objects.select_related("issue"), pk=self.kwargs["pk"])
        issue, membership = _member_issue(self.request, attachment.issue_id)
        allowed = self.request.user.id in (attachment.uploaded_by_id, issue.reporter_id) or membership.role in (
            Membership.Role.OWNER,
            Membership.Role.ADMIN,
        )
        if not allowed:
            raise PermissionDenied("Only the uploader, the issue's creator or a workspace admin can remove this file.")
        return attachment

    def perform_destroy(self, instance):
        workspace_id = instance.issue.project.workspace_id
        instance.delete()
        touch(workspace_id, "issues")


class IssueAttachmentDownloadView(generics.GenericAPIView):
    """GET: the file itself, always as a download, with the type decided at upload time."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        attachment = get_object_or_404(IssueAttachment.objects.select_related("issue"), pk=pk)
        _member_issue(request, attachment.issue_id)
        response = FileResponse(attachment.file.open("rb"), as_attachment=True, filename=attachment.name, content_type=attachment.content_type)
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        response["Cache-Control"] = "private, no-store"
        return response

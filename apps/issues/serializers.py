from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import serializers

from apps.cycles.models import Cycle
from apps.milestones.models import Milestone
from apps.projects.models import Label
from apps.workspaces.serializers import UserBriefSerializer

from .models import Issue

User = get_user_model()


class LabelBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Label
        fields = ["id", "name", "color"]


class IssueSerializer(serializers.ModelSerializer):
    """An issue always belongs to exactly one project, and everything it points at (assignee, labels,
    cycle, milestone) must belong to that project's workspace.

    The project is never taken from the request body: on create the view resolves it (and checks the
    caller may use it) and passes it in the serializer context; afterwards it cannot change. The
    related-object fields below are scoped to it, so an id from another workspace is rejected with the
    same "does not exist" error as an id that was never there.
    """

    assignee = UserBriefSerializer(read_only=True)
    reporter = UserBriefSerializer(read_only=True)
    labels = LabelBriefSerializer(many=True, read_only=True)
    assignee_id = serializers.PrimaryKeyRelatedField(
        source="assignee", queryset=User.objects.none(), write_only=True, required=False, allow_null=True
    )
    label_ids = serializers.PrimaryKeyRelatedField(
        source="labels", queryset=Label.objects.none(), write_only=True, required=False, many=True
    )

    class Meta:
        model = Issue
        fields = [
            "id",
            "project",
            "number",
            "title",
            "description",
            "type",
            "status",
            "priority",
            "assignee",
            "assignee_id",
            "reporter",
            "cycle",
            "milestone",
            "labels",
            "label_ids",
            "due_date",
            "github_number",
            "github_url",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "project",
            "number",
            "reporter",
            "github_number",
            "github_url",
            "created_at",
            "updated_at",
        ]

    def _project(self):
        if self.instance is not None and hasattr(self.instance, "project"):
            return self.instance.project
        return self.context.get("project")

    def get_fields(self):
        fields = super().get_fields()
        project = self._project()
        if project is None:
            # No project in scope (e.g. the browsable API rendering a blank form): nothing is selectable.
            users, labels = User.objects.none(), Label.objects.none()
            cycles, milestones = Cycle.objects.none(), Milestone.objects.none()
        else:
            users = User.objects.filter(
                is_active=True, workspace_memberships__workspace_id=project.workspace_id
            )
            labels = Label.objects.filter(workspace_id=project.workspace_id).filter(
                Q(project__isnull=True) | Q(project=project)
            )
            cycles = Cycle.objects.filter(project=project)
            milestones = Milestone.objects.filter(project=project)
        fields["assignee_id"].queryset = users
        fields["label_ids"].child_relation.queryset = labels
        fields["cycle"].queryset = cycles
        fields["milestone"].queryset = milestones
        return fields

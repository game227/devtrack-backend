from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import serializers

from apps.cycles.models import Cycle
from apps.milestones.models import Milestone
from apps.projects.models import Label
from apps.workspaces.serializers import UserBriefSerializer

from .models import SAVED_VIEW_FILTER_KEYS, Issue, SavedView

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
            "completed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "completed_at",
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


MAX_SAVED_VIEWS_PER_LIST = 30
CHOICE_FILTERS = {
    "status": Issue.Status.values,
    "type": Issue.Type.values,
    "priority": Issue.Priority.values,
}


class SavedViewSerializer(serializers.ModelSerializer):
    """A named filter set. Only the issue list's own filters are kept, each checked like the list would."""

    class Meta:
        model = SavedView
        fields = ["id", "name", "filters", "workspace", "project", "created_at"]
        read_only_fields = ["workspace", "project", "created_at"]

    def _scope(self):
        if self.instance is not None:
            return self.instance.workspace, self.instance.project
        return self.context["workspace"], self.context["project"]

    def validate_name(self, value):
        name = " ".join(value.split())
        if not name:
            raise serializers.ValidationError("Give the view a name.")
        return name

    def validate_filters(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Filters must be an object.")
        unknown = sorted(set(value) - set(SAVED_VIEW_FILTER_KEYS))
        if unknown:
            raise serializers.ValidationError(f"Unknown filter: {', '.join(unknown)}.")
        workspace, project = self._scope()
        cleaned = {}
        for key, raw in value.items():
            if raw in (None, ""):
                continue
            if key in CHOICE_FILTERS:
                if raw not in CHOICE_FILTERS[key]:
                    raise serializers.ValidationError(f"'{raw}' is not a valid {key}.")
                cleaned[key] = raw
            elif key == "assignee":
                if raw == "me":
                    cleaned[key] = "me"
                    continue
                user_id = _positive_int(raw)
                if user_id is None or not workspace.memberships.filter(user_id=user_id).exists():
                    raise serializers.ValidationError("The assignee must be a member of this workspace.")
                cleaned[key] = str(user_id)
            elif key == "label":
                label_id = _positive_int(raw)
                labels = Label.objects.filter(workspace=workspace)
                if project is not None:
                    labels = labels.filter(Q(project__isnull=True) | Q(project=project))
                if label_id is None or not labels.filter(pk=label_id).exists():
                    raise serializers.ValidationError("That label is not available here.")
                cleaned[key] = str(label_id)
        return cleaned

    def validate(self, attrs):
        workspace, project = self._scope()
        mine = SavedView.objects.filter(owner=self.context["request"].user, workspace=workspace, project=project)
        if self.instance is not None:
            mine = mine.exclude(pk=self.instance.pk)
        elif mine.count() >= MAX_SAVED_VIEWS_PER_LIST:
            raise serializers.ValidationError(f"You can keep up to {MAX_SAVED_VIEWS_PER_LIST} saved views per list.")
        name = attrs.get("name")
        if name and mine.filter(name__iexact=name).exists():
            raise serializers.ValidationError({"name": "You already have a view with this name."})
        return attrs


def _positive_int(raw):
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, str) and raw.isascii() and raw.isdigit():
        value = int(raw)
    else:
        return None
    return value if 0 < value <= 2**63 - 1 else None

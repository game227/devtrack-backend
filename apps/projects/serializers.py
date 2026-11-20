from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.teams.models import Team
from apps.workspaces.serializers import UserBriefSerializer

from .models import Label, Note, Project, ProjectMember

User = get_user_model()


class ProjectSerializer(serializers.ModelSerializer):
    owner = UserBriefSerializer(read_only=True)
    # How much work there is and how much is finished, for list rows ("12 open · 40% done").
    issue_count = serializers.SerializerMethodField()
    done_count = serializers.SerializerMethodField()
    # Whether the person asking keeps this project in their sidebar.
    is_favorite = serializers.SerializerMethodField()
    # Issues finished per week over the last eight weeks, oldest first (project lists only).
    weekly_done = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = [
            "id",
            "workspace",
            "name",
            "description",
            "icon",
            "status",
            "priority",
            "start_date",
            "target_date",
            "owner",
            "team",
            "repository_url",
            "tech_stack",
            "wip_limits",
            "issue_count",
            "done_count",
            "is_favorite",
            "weekly_done",
            "created_at",
            "updated_at",
        ]
        # The workspace is fixed when the project is created (the view passes it in) and never changes:
        # letting it be patched would let a project owner drop a project into anyone's workspace.
        read_only_fields = ["id", "workspace", "owner", "created_at", "updated_at"]

    def get_issue_count(self, obj):
        value = getattr(obj, "issue_total", None)
        return value if value is not None else obj.issues.count()

    def get_weekly_done(self, obj):
        if not hasattr(obj, "done_week_0"):
            return None
        weeks = []
        index = 0
        while hasattr(obj, f"done_week_{index}"):
            weeks.append(getattr(obj, f"done_week_{index}"))
            index += 1
        return weeks

    def get_is_favorite(self, obj):
        value = getattr(obj, "favorited", None)
        if value is not None:
            return value
        request = self.context.get("request")
        if request is None or not request.user.is_authenticated:
            return False
        return obj.favorites.filter(user=request.user).exists()

    def get_done_count(self, obj):
        value = getattr(obj, "issue_done", None)
        return value if value is not None else obj.issues.filter(status="done").count()

    def validate_wip_limits(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Expected an object of column: limit.")
        allowed = {"backlog", "todo", "in_progress", "in_review"}
        cleaned = {}
        for column, limit in value.items():
            if column not in allowed:
                raise serializers.ValidationError(f"'{column}' has no limit.")
            if limit in (None, "", 0):
                continue
            if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 99:
                raise serializers.ValidationError("A limit is a whole number from 1 to 99.")
            cleaned[column] = limit
        return cleaned

    def validate(self, attrs):
        # On a partial update, compare with the date that is not being changed.
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        target = attrs.get("target_date", getattr(self.instance, "target_date", None))
        if start and target and target < start:
            raise serializers.ValidationError({"target_date": "The target date cannot be before the start date."})
        return attrs

    def get_fields(self):
        fields = super().get_fields()
        # A project can only be assigned to a team of its own workspace.
        workspace = self.instance.workspace if getattr(self.instance, "workspace", None) else self.context.get("workspace")
        fields["team"].queryset = (
            Team.objects.filter(workspace=workspace) if workspace is not None else Team.objects.none()
        )
        return fields


class ProjectMemberSerializer(serializers.ModelSerializer):
    user = UserBriefSerializer(read_only=True)

    class Meta:
        model = ProjectMember
        fields = ["id", "user", "role", "specialty", "added_at"]
        read_only_fields = ["id", "added_at"]


class ProjectMemberCreateSerializer(serializers.Serializer):
    username = serializers.CharField()
    role = serializers.CharField(required=False, allow_blank=True, default="")
    specialty = serializers.ChoiceField(choices=ProjectMember.Specialty.choices, required=False, allow_blank=True, default="")

    def validate_username(self, value):
        # Only people who are already in the project's workspace can be added to the project — the
        # lookup is scoped, so this endpoint cannot be used to probe which usernames exist elsewhere.
        project = self.context["project"]
        self._user = User.objects.filter(
            username=value, is_active=True, workspace_memberships__workspace_id=project.workspace_id
        ).first()
        if self._user is None:
            raise serializers.ValidationError("No member of this workspace has that username.")
        return value

    def validate(self, attrs):
        project = self.context["project"]
        if ProjectMember.objects.filter(project=project, user=self._user).exists():
            raise serializers.ValidationError({"username": "User is already a member of this project."})
        attrs["user"] = self._user
        return attrs

    def save(self):
        project = self.context["project"]
        return ProjectMember.objects.create(
            project=project,
            user=self.validated_data["user"],
            role=self.validated_data.get("role", ""),
            specialty=self.validated_data.get("specialty", ""),
        )


class ProjectMemberUpdateSerializer(serializers.Serializer):
    specialty = serializers.ChoiceField(choices=ProjectMember.Specialty.choices, allow_blank=True)


class LabelSerializer(serializers.ModelSerializer):
    color = serializers.RegexField(
        r"^#[0-9a-fA-F]{6}$", max_length=7, required=False, error_messages={"invalid": "Use a #rrggbb colour."}
    )

    class Meta:
        model = Label
        fields = ["id", "workspace", "project", "name", "color"]
        # Fixed at creation (the view passes the workspace in); a label can never be moved to another workspace.
        read_only_fields = ["id", "workspace"]

    def get_fields(self):
        fields = super().get_fields()
        workspace = self.instance.workspace if getattr(self.instance, "workspace", None) else self.context.get("workspace")
        # A label can be scoped to a project, but only to one in its own workspace.
        fields["project"].queryset = (
            Project.objects.filter(workspace=workspace) if workspace is not None else Project.objects.none()
        )
        return fields


class NoteSerializer(serializers.ModelSerializer):
    author = UserBriefSerializer(read_only=True)

    class Meta:
        model = Note
        fields = ["id", "project", "title", "body", "author", "created_at", "updated_at"]
        read_only_fields = ["id", "project", "author", "created_at", "updated_at"]

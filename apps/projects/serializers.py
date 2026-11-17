from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.teams.models import Team
from apps.workspaces.serializers import UserBriefSerializer

from .models import Label, Note, Project, ProjectMember

User = get_user_model()


class ProjectSerializer(serializers.ModelSerializer):
    owner = UserBriefSerializer(read_only=True)

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
            "created_at",
            "updated_at",
        ]
        # The workspace is fixed when the project is created (the view passes it in) and never changes:
        # letting it be patched would let a project owner drop a project into anyone's workspace.
        read_only_fields = ["id", "workspace", "owner", "created_at", "updated_at"]

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

from django.contrib.auth import get_user_model
from rest_framework import serializers

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
        read_only_fields = ["id", "owner", "created_at", "updated_at"]


class ProjectMemberSerializer(serializers.ModelSerializer):
    user = UserBriefSerializer(read_only=True)

    class Meta:
        model = ProjectMember
        fields = ["id", "user", "role", "added_at"]
        read_only_fields = ["id", "added_at"]


class ProjectMemberCreateSerializer(serializers.Serializer):
    username = serializers.CharField()
    role = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_username(self, value):
        try:
            self._user = User.objects.get(username=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("No user with that username exists.")
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
            project=project, user=self.validated_data["user"], role=self.validated_data.get("role", "")
        )


class LabelSerializer(serializers.ModelSerializer):
    class Meta:
        model = Label
        fields = ["id", "workspace", "project", "name", "color"]
        read_only_fields = ["id"]


class NoteSerializer(serializers.ModelSerializer):
    author = UserBriefSerializer(read_only=True)

    class Meta:
        model = Note
        fields = ["id", "project", "title", "body", "author", "created_at", "updated_at"]
        read_only_fields = ["id", "project", "author", "created_at", "updated_at"]

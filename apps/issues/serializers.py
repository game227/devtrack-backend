from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.projects.models import Label
from apps.workspaces.serializers import UserBriefSerializer

from .models import Issue

User = get_user_model()


class LabelBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Label
        fields = ["id", "name", "color"]


class IssueSerializer(serializers.ModelSerializer):
    assignee = UserBriefSerializer(read_only=True)
    reporter = UserBriefSerializer(read_only=True)
    labels = LabelBriefSerializer(many=True, read_only=True)
    assignee_id = serializers.PrimaryKeyRelatedField(
        source="assignee", queryset=User.objects.all(), write_only=True, required=False, allow_null=True
    )
    label_ids = serializers.PrimaryKeyRelatedField(
        source="labels", queryset=Label.objects.all(), write_only=True, required=False, many=True
    )

    class Meta:
        model = Issue
        fields = [
            "id",
            "project",
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
        read_only_fields = ["id", "reporter", "github_number", "github_url", "created_at", "updated_at"]

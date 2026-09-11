from rest_framework import serializers

from apps.issues.models import Issue

from .models import Milestone


class MilestoneSerializer(serializers.ModelSerializer):
    issue_count = serializers.SerializerMethodField()
    completed_count = serializers.SerializerMethodField()
    completion_percent = serializers.SerializerMethodField()

    class Meta:
        model = Milestone
        fields = [
            "id",
            "project",
            "name",
            "description",
            "target_date",
            "issue_count",
            "completed_count",
            "completion_percent",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def get_issue_count(self, obj):
        return obj.issues.count()

    def get_completed_count(self, obj):
        return obj.issues.filter(status=Issue.Status.DONE).count()

    def get_completion_percent(self, obj):
        total = obj.issues.count()
        if not total:
            return 0
        done = obj.issues.filter(status=Issue.Status.DONE).count()
        return round(done / total * 100)

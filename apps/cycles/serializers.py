from django.utils import timezone
from rest_framework import serializers

from apps.issues.models import Issue

from .models import Cycle


class CycleSerializer(serializers.ModelSerializer):
    issue_count = serializers.SerializerMethodField()
    completed_count = serializers.SerializerMethodField()
    completion_percent = serializers.SerializerMethodField()
    is_active = serializers.SerializerMethodField()

    class Meta:
        model = Cycle
        fields = [
            "id",
            "project",
            "name",
            "start_date",
            "end_date",
            "issue_count",
            "completed_count",
            "completion_percent",
            "is_active",
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

    def get_is_active(self, obj):
        today = timezone.localdate()
        return obj.start_date <= today <= obj.end_date

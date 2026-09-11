from rest_framework import serializers

from apps.workspaces.serializers import UserBriefSerializer

from .models import Activity


class ActivitySerializer(serializers.ModelSerializer):
    actor = UserBriefSerializer(read_only=True)
    target_type = serializers.SerializerMethodField()
    target_id = serializers.IntegerField(source="object_id", read_only=True)
    target_display = serializers.SerializerMethodField()

    class Meta:
        model = Activity
        fields = [
            "id",
            "actor",
            "verb",
            "target_type",
            "target_id",
            "target_display",
            "metadata",
            "created_at",
        ]

    def get_target_type(self, obj):
        return obj.content_type.model

    def get_target_display(self, obj):
        target = obj.target
        if target is None:
            return None
        if hasattr(target, "title"):
            return target.title
        if hasattr(target, "name"):
            return target.name
        if hasattr(target, "body"):
            return target.body[:80]
        return str(target)

from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    target_type = serializers.SerializerMethodField()
    target_id = serializers.IntegerField(source="object_id", read_only=True)
    target_display = serializers.SerializerMethodField()
    # Who did it and on which issue, so a notification reads "alex commented on #12 Fix login".
    actor = serializers.SerializerMethodField()
    issue = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ["id", "verb", "target_type", "target_id", "target_display", "actor", "issue", "is_read", "created_at"]

    def _issue_of(self, obj):
        target = obj.target
        if target is not None and hasattr(target, "content_object") and hasattr(target, "body"):
            target = target.content_object
        return target if target is not None and hasattr(target, "number") and hasattr(target, "title") else None

    def get_actor(self, obj):
        target = obj.target
        author = getattr(target, "author", None) if target is not None and hasattr(target, "body") else None
        return author.username if author is not None else None

    def get_issue(self, obj):
        issue = self._issue_of(obj)
        return {"id": issue.pk, "number": issue.number, "title": issue.title} if issue else None

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

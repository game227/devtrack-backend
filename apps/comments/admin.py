from django.contrib import admin

from apps.adminui.display import excerpt

from .models import Comment


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ["author", "short_body", "content_type", "object_id", "created_at"]
    list_filter = ["content_type"]
    search_fields = ["body", "author__username"]
    list_select_related = ["author", "content_type"]
    raw_id_fields = ["author"]
    ordering = ["-created_at"]

    @admin.display(description="Comment")
    def short_body(self, obj):
        return excerpt(obj.body)

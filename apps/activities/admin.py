from django.contrib import admin

from .models import Activity


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    """The activity feed is a record of what happened: readable here, never edited."""

    list_display = ["created_at", "actor", "verb", "workspace", "content_type", "object_id"]
    list_filter = ["verb"]
    search_fields = ["actor__username", "workspace__name"]
    list_select_related = ["actor", "workspace", "content_type"]
    date_hierarchy = "created_at"
    ordering = ["-created_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

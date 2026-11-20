from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """Notifications are delivered by the app; the admin can read and delete them, not write them."""

    list_display = ["created_at", "recipient", "verb", "is_read", "content_type", "object_id"]
    list_filter = ["verb", "is_read"]
    search_fields = ["recipient__username"]
    list_select_related = ["recipient", "content_type"]
    date_hierarchy = "created_at"
    ordering = ["-created_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

from django.contrib import admin

from .models import Milestone


@admin.register(Milestone)
class MilestoneAdmin(admin.ModelAdmin):
    list_display = ["name", "project", "target_date", "created_at"]
    search_fields = ["name", "project__name"]
    list_select_related = ["project"]
    raw_id_fields = ["project"]

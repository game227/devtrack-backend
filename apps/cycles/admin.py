from django.contrib import admin

from .models import Cycle


@admin.register(Cycle)
class CycleAdmin(admin.ModelAdmin):
    list_display = ["name", "project", "start_date", "end_date"]
    search_fields = ["name", "project__name"]
    list_select_related = ["project"]
    raw_id_fields = ["project"]
    date_hierarchy = "start_date"

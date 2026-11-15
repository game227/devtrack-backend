from django.contrib import admin

from .models import Team, TeamMembership


class TeamMembershipInline(admin.TabularInline):
    model = TeamMembership
    raw_id_fields = ["user"]
    extra = 0


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ["name", "workspace", "created_at"]
    search_fields = ["name", "workspace__name"]
    list_select_related = ["workspace"]
    raw_id_fields = ["workspace"]
    inlines = [TeamMembershipInline]

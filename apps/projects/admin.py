from django.contrib import admin

from apps.adminui.display import chip, excerpt

from .models import Label, Note, Project, ProjectFavorite, ProjectMember


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["name", "workspace", "status_chip", "priority_chip", "owner", "target_date", "updated_at"]
    list_filter = ["status", "priority"]
    search_fields = ["name", "description"]
    list_select_related = ["workspace", "owner"]
    raw_id_fields = ["workspace", "owner", "team"]
    readonly_fields = ["issue_counter", "created_at", "updated_at"]
    ordering = ["-updated_at"]

    @admin.display(description="Status", ordering="status")
    def status_chip(self, obj):
        return chip(f"dt-pr-{obj.status}", obj.get_status_display())

    @admin.display(description="Priority", ordering="priority")
    def priority_chip(self, obj):
        return chip(f"dt-pri-{obj.priority}", obj.get_priority_display())


@admin.register(ProjectMember)
class ProjectMemberAdmin(admin.ModelAdmin):
    list_display = ["user", "project", "role", "specialty", "added_at"]
    list_filter = ["role", "specialty"]
    search_fields = ["user__username", "project__name"]
    list_select_related = ["user", "project"]
    raw_id_fields = ["user", "project"]


@admin.register(Label)
class LabelAdmin(admin.ModelAdmin):
    list_display = ["name", "workspace", "project", "color"]
    search_fields = ["name"]
    list_select_related = ["workspace", "project"]
    raw_id_fields = ["workspace", "project"]


@admin.register(Note)
class NoteAdmin(admin.ModelAdmin):
    list_display = ["title", "project", "author", "short_body", "updated_at"]
    search_fields = ["title", "body"]
    list_select_related = ["project", "author"]
    raw_id_fields = ["project", "author"]

    @admin.display(description="Note")
    def short_body(self, obj):
        return excerpt(obj.body)


@admin.register(ProjectFavorite)
class ProjectFavoriteAdmin(admin.ModelAdmin):
    list_display = ("user", "project", "created_at")
    raw_id_fields = ("user", "project")

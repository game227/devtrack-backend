from django.contrib import admin

from apps.adminui.display import chip, key

from .models import ChecklistItem, Issue, IssueRelation, IssueShareLink, RecurringIssue, SavedView, TimeEntry


class ChecklistItemInline(admin.TabularInline):
    model = ChecklistItem
    fields = ["text", "done", "position"]
    extra = 0


class IssueRelationInline(admin.TabularInline):
    model = IssueRelation
    fk_name = "source"
    fields = ["kind", "target"]
    raw_id_fields = ["target"]
    extra = 0
    verbose_name = "link"
    verbose_name_plural = "links from this issue"


@admin.register(Issue)
class IssueAdmin(admin.ModelAdmin):
    inlines = [ChecklistItemInline, IssueRelationInline]
    list_display = ["issue_key", "title", "project", "status_chip", "priority_chip", "assignee", "due_date", "updated_at"]
    list_display_links = ["issue_key", "title"]
    list_filter = ["status", "priority", "type", ("project", admin.RelatedOnlyFieldListFilter)]
    search_fields = ["title", "description"]
    list_select_related = ["project", "assignee"]
    # Raw id inputs: a large install would otherwise load every user/project into each dropdown.
    raw_id_fields = ["project", "assignee", "reporter", "cycle", "milestone"]
    filter_horizontal = ["labels"]
    # The number is the project's counter (assigned on save), and the timestamps are the system's.
    readonly_fields = ["number", "completed_at", "created_at", "updated_at"]
    date_hierarchy = "created_at"
    ordering = ["-updated_at"]

    @admin.display(description="#", ordering="number")
    def issue_key(self, obj):
        return key(obj.number)

    @admin.display(description="Status", ordering="status")
    def status_chip(self, obj):
        return chip(f"dt-st-{obj.status}", obj.get_status_display())

    @admin.display(description="Priority", ordering="priority")
    def priority_chip(self, obj):
        return chip(f"dt-pri-{obj.priority}", obj.get_priority_display())


@admin.register(SavedView)
class SavedViewAdmin(admin.ModelAdmin):
    list_display = ["name", "owner", "workspace", "project", "created_at"]
    list_select_related = ["owner", "workspace", "project"]
    search_fields = ["name", "owner__username"]
    raw_id_fields = ["owner", "workspace", "project"]
    readonly_fields = ["created_at"]


@admin.register(RecurringIssue)
class RecurringIssueAdmin(admin.ModelAdmin):
    list_display = ["title", "project", "frequency", "next_run", "active"]
    list_filter = ["frequency", "active"]
    raw_id_fields = ["project", "assignee", "created_by"]


@admin.register(IssueShareLink)
class IssueShareLinkAdmin(admin.ModelAdmin):
    list_display = ["issue", "created_by", "expires_at", "revoked"]
    raw_id_fields = ["issue", "created_by"]
    readonly_fields = ["token"]


@admin.register(TimeEntry)
class TimeEntryAdmin(admin.ModelAdmin):
    list_display = ["issue", "user", "minutes", "spent_on"]
    raw_id_fields = ["issue", "user"]

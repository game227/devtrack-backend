from django.contrib import admin
from django.db.models import Count

from apps.adminui.display import chip

from .models import Invitation, Membership, Workspace

ROLE_TONE = {"owner": "dt-tone-brand", "admin": "dt-tone-warning", "member": ""}


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ["name", "owner", "personal", "member_total", "created_at"]
    list_filter = ["is_personal"]
    search_fields = ["name", "slug", "owner__username"]
    list_select_related = ["owner"]
    raw_id_fields = ["owner"]
    readonly_fields = ["created_at"]
    ordering = ["-created_at"]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(member_total=Count("memberships", distinct=True))

    @admin.display(boolean=True, description="Personal", ordering="is_personal")
    def personal(self, obj):
        return obj.is_personal

    @admin.display(description="Members", ordering="member_total")
    def member_total(self, obj):
        return obj.member_total


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ["user", "workspace", "role_chip", "joined_at"]
    list_filter = ["role"]
    search_fields = ["user__username", "workspace__name"]
    list_select_related = ["user", "workspace"]
    raw_id_fields = ["user", "workspace"]

    @admin.display(description="Role", ordering="role")
    def role_chip(self, obj):
        return chip(ROLE_TONE.get(obj.role, ""), obj.get_role_display())


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ["user", "workspace", "role", "invited_by", "created_at"]
    list_filter = ["role"]
    search_fields = ["user__username", "workspace__name", "invited_by__username"]
    list_select_related = ["user", "workspace", "invited_by"]
    raw_id_fields = ["user", "workspace", "invited_by"]

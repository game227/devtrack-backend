from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    # Django's fieldsets are kept on purpose: they never show the two-factor secret or recovery codes.
    list_display = ["username", "email", "first_name", "last_name", "is_staff", "is_active", "two_factor", "date_joined", "last_login"]
    list_filter = ["is_staff", "is_superuser", "is_active", "totp_enabled", "email_verified", "groups"]
    ordering = ["-date_joined"]

    @admin.display(boolean=True, description="2FA", ordering="totp_enabled")
    def two_factor(self, obj):
        return obj.totp_enabled

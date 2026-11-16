"""The admin's sign-in: the same second factor as the web app, and a cap on failed attempts.

Django's admin login checks only the password, so an account with two-factor authentication on could be
opened there with the password alone, and nothing slowed down guessing. This form closes both gaps.
"""

import logging

from django import forms
from django.contrib.admin.forms import AdminAuthenticationForm
from django.core.cache import cache
from django.core.exceptions import ValidationError
from rest_framework.throttling import BaseThrottle

from apps.accounts.two_factor import accept_second_factor

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 15 * 60
MAX_FAILURES_PER_ACCOUNT = 5
MAX_FAILURES_PER_IP = 20


class DevTrackAdminAuthenticationForm(AdminAuthenticationForm):
    otp = forms.CharField(
        label="Two-factor code",
        required=False,
        max_length=64,
        help_text="Only if two-factor authentication is on for this account (or use a recovery code).",
        widget=forms.TextInput(attrs={"autocomplete": "one-time-code", "inputmode": "numeric"}),
    )

    def _keys(self):
        # The client address the API throttles use too (honours NUM_PROXIES).
        ident = BaseThrottle().get_ident(self.request) if self.request is not None else "unknown"
        username = (self.data.get("username") or "").strip().lower()
        return f"admin-login:ip:{ident}", f"admin-login:account:{username}"

    @staticmethod
    def _count_failure(key):
        if not cache.add(key, 1, WINDOW_SECONDS):
            try:
                cache.incr(key)
            except ValueError:  # expired between add() and incr()
                cache.set(key, 1, WINDOW_SECONDS)

    def clean(self):
        ip_key, account_key = self._keys()
        if cache.get(account_key, 0) >= MAX_FAILURES_PER_ACCOUNT or cache.get(ip_key, 0) >= MAX_FAILURES_PER_IP:
            raise ValidationError("Too many sign-in attempts. Try again in 15 minutes.", code="throttled")
        try:
            cleaned = super().clean()
            user = self.get_user()
            if user is not None and user.totp_enabled:
                if not accept_second_factor(user, (self.cleaned_data.get("otp") or "").strip()):
                    raise ValidationError(
                        "Enter a valid code from your authenticator app, or an unused recovery code.", code="otp"
                    )
        except ValidationError:
            self._count_failure(ip_key)
            self._count_failure(account_key)
            logger.warning("Admin sign-in refused for %r", self.data.get("username"))
            raise
        cache.delete(account_key)
        return cleaned

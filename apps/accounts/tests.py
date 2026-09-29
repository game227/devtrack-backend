from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from apps.telegram_bot.services import BotServiceError

from .throttling import AccountLoginRateThrottle, EmailVerifyResendThrottle
from .tokens import email_verification_token

User = get_user_model()


class PasswordResetChannelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="reset_user", email="reset_user@example.com", password="pw"
        )
        self.client = APIClient()
        self.url = reverse("password_reset")

    @patch("apps.accounts.views.telegram_services.send_message")
    def test_prefers_telegram_and_sends_no_email_when_it_succeeds(self, mock_send_message):
        mock_send_message.return_value = {"detail": "sent"}
        self.client.post(self.url, {"email": self.user.email}, format="json")
        mock_send_message.assert_called_once()
        self.assertEqual(mock_send_message.call_args[0][0], self.user.id)
        self.assertEqual(len(mail.outbox), 0)

    @patch("apps.accounts.views.telegram_services.send_message")
    def test_falls_back_to_email_when_telegram_is_not_linked_or_fails(self, mock_send_message):
        mock_send_message.side_effect = BotServiceError("not linked")
        self.client.post(self.url, {"email": self.user.email}, format="json")
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])

    def test_unknown_email_sends_nothing_but_still_returns_200(self):
        response = self.client.post(self.url, {"email": "nobody@example.com"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)


class PasswordResetLanguageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="lang_user", email="lang_user@example.com", password="pw"
        )
        self.client = APIClient()
        self.url = reverse("password_reset")

    @patch("apps.accounts.views.telegram_services.send_message", side_effect=BotServiceError("not linked"))
    def test_email_is_sent_in_the_requested_language(self, _send):
        self.client.post(self.url, {"email": self.user.email, "lang": "uz"}, format="json")
        self.assertEqual(mail.outbox[0].subject, "DevTrack parolini tiklash")
        self.assertIn("/reset-password/", mail.outbox[0].body)

    @patch("apps.accounts.views.telegram_services.send_message", side_effect=BotServiceError("not linked"))
    def test_defaults_to_english(self, _send):
        self.client.post(self.url, {"email": self.user.email}, format="json")
        self.assertEqual(mail.outbox[0].subject, "Reset your DevTrack password")

    @patch("apps.accounts.views.telegram_services.send_message")
    def test_telegram_message_is_localized_too(self, mock_send_message):
        mock_send_message.return_value = {"detail": "sent"}
        self.client.post(self.url, {"email": self.user.email, "lang": "uz"}, format="json")
        self.assertIn("DevTrack parolini tiklash", mock_send_message.call_args[0][1])

    def test_rejects_an_unsupported_language(self):
        response = self.client.post(self.url, {"email": self.user.email, "lang": "xx"}, format="json")
        self.assertEqual(response.status_code, 400)

    @override_settings(PASSWORD_RESET_ASYNC=True)
    @patch("apps.accounts.views.threading.Thread")
    def test_delivery_moves_to_a_background_thread_when_async(self, mock_thread):
        response = self.client.post(self.url, {"email": self.user.email}, format="json")
        self.assertEqual(response.status_code, 200)
        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()
        self.assertEqual(len(mail.outbox), 0)  # nothing was delivered inline


class AccountLoginThrottleTests(TestCase):
    # DRF's SimpleRateThrottle reads DEFAULT_THROTTLE_RATES into a class
    # attribute once, at import time — override_settings doesn't reach
    # already-imported throttle classes, so the rate is patched directly.
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        original_rates = AccountLoginRateThrottle.THROTTLE_RATES
        AccountLoginRateThrottle.THROTTLE_RATES = {**original_rates, "login_account": "3/min"}
        self.addCleanup(setattr, AccountLoginRateThrottle, "THROTTLE_RATES", original_rates)
        self.user = User.objects.create_user(
            username="throttle_user", email="throttle_user@example.com", password="right-pass"
        )
        self.client = APIClient()
        self.url = reverse("login")

    def test_repeated_attempts_on_one_account_get_throttled_regardless_of_ip(self):
        for _ in range(3):
            self.client.post(self.url, {"username": "throttle_user", "password": "wrong"}, format="json")
        response = self.client.post(
            self.url, {"username": "throttle_user", "password": "wrong"}, format="json"
        )
        self.assertEqual(response.status_code, 429)

    def test_a_different_account_is_not_affected_by_another_accounts_throttling(self):
        for _ in range(3):
            self.client.post(self.url, {"username": "throttle_user", "password": "wrong"}, format="json")
        other = User.objects.create_user(username="other_user", email="other@example.com", password="pw")
        response = self.client.post(self.url, {"username": "other_user", "password": "pw"}, format="json")
        self.assertEqual(response.status_code, 200)


class AccountDeleteTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user(
            username="delete_me", email="delete_me@example.com", password="right-pass",
            first_name="Jane", bio="hi",
        )
        self.client = APIClient()
        refresh = RefreshToken.for_user(self.user)
        self.refresh = refresh
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
        self.url = reverse("account_delete")

    def test_wrong_password_is_rejected_and_account_stays_active(self):
        response = self.client.post(self.url, {"password": "wrong"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_correct_password_deactivates_and_scrubs_the_account(self):
        response = self.client.post(self.url, {"password": "right-pass"}, format="json")
        self.assertEqual(response.status_code, 204)
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertEqual(self.user.email, f"deleted-user-{self.user.pk}@devtrack.invalid")
        self.assertEqual(self.user.first_name, "")
        self.assertEqual(self.user.bio, "")
        self.assertFalse(self.user.has_usable_password())

    def test_outstanding_tokens_are_blacklisted(self):
        OutstandingToken.objects.get_or_create(
            user=self.user,
            jti=self.refresh["jti"],
            defaults={
                "token": str(self.refresh),
                "created_at": self.refresh.current_time,
                "expires_at": self.refresh.current_time,
            },
        )
        self.client.post(self.url, {"password": "right-pass"}, format="json")
        outstanding = OutstandingToken.objects.filter(user=self.user)
        self.assertTrue(outstanding.exists())
        for token in outstanding:
            self.assertTrue(BlacklistedToken.objects.filter(token=token).exists())


class EmailVerificationRegisterTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = reverse("register")

    def test_new_users_start_unverified_and_get_an_email(self):
        response = self.client.post(
            self.url,
            {
                "username": "newbie",
                "email": "newbie@example.com",
                "password": "S0me-Str0ng-Pass",
                "password_confirm": "S0me-Str0ng-Pass",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(username="newbie")
        self.assertFalse(user.email_verified)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["newbie@example.com"])
        self.assertIn("/verify-email/", mail.outbox[0].body)

    def test_verification_email_is_localized(self):
        self.client.post(
            self.url,
            {
                "username": "uzbek_user",
                "email": "uzbek@example.com",
                "password": "S0me-Str0ng-Pass",
                "password_confirm": "S0me-Str0ng-Pass",
                "lang": "uz",
            },
            format="json",
        )
        self.assertEqual(mail.outbox[0].subject, "DevTrack email manzilini tasdiqlang")


class EmailVerificationConfirmTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="unverified", email="unverified@example.com", password="pw"
        )
        self.user.email_verified = False
        self.user.save(update_fields=["email_verified"])
        self.client = APIClient()
        self.url = reverse("email_verify_confirm")
        self.uid = urlsafe_base64_encode(force_bytes(self.user.pk))

    def test_valid_token_verifies_the_account(self):
        token = email_verification_token.make_token(self.user)
        response = self.client.post(self.url, {"uid": self.uid, "token": token}, format="json")
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.email_verified)

    def test_a_used_token_cannot_be_replayed(self):
        token = email_verification_token.make_token(self.user)
        self.client.post(self.url, {"uid": self.uid, "token": token}, format="json")
        response = self.client.post(self.url, {"uid": self.uid, "token": token}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_garbage_token_is_rejected(self):
        response = self.client.post(self.url, {"uid": self.uid, "token": "not-a-real-token"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.email_verified)

    def test_unknown_uid_is_rejected(self):
        bogus_uid = urlsafe_base64_encode(force_bytes(999999))
        response = self.client.post(self.url, {"uid": bogus_uid, "token": "whatever"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_a_password_reset_token_cannot_be_used_to_verify_email(self):
        # The two token generators are scoped with different salts, so a
        # token minted for one purpose must not work for the other.
        reset_token = PasswordResetTokenGenerator().make_token(self.user)
        response = self.client.post(self.url, {"uid": self.uid, "token": reset_token}, format="json")
        self.assertEqual(response.status_code, 400)


class EmailVerificationResendTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        original_rates = EmailVerifyResendThrottle.THROTTLE_RATES
        EmailVerifyResendThrottle.THROTTLE_RATES = {**original_rates, "email_verify_resend": "2/min"}
        self.addCleanup(setattr, EmailVerifyResendThrottle, "THROTTLE_RATES", original_rates)

        self.user = User.objects.create_user(
            username="resend_me", email="resend_me@example.com", password="pw"
        )
        self.user.email_verified = False
        self.user.save(update_fields=["email_verified"])
        self.client = APIClient()
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
        self.url = reverse("email_verify_resend")

    def test_requires_authentication(self):
        anon_client = APIClient()
        response = anon_client.post(self.url, {}, format="json")
        self.assertEqual(response.status_code, 401)

    def test_sends_a_new_verification_email(self):
        response = self.client.post(self.url, {}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

    def test_already_verified_accounts_are_rejected(self):
        self.user.email_verified = True
        self.user.save(update_fields=["email_verified"])
        response = self.client.post(self.url, {}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(mail.outbox), 0)

    def test_repeated_requests_are_throttled(self):
        self.client.post(self.url, {}, format="json")
        self.client.post(self.url, {}, format="json")
        response = self.client.post(self.url, {}, format="json")
        self.assertEqual(response.status_code, 429)

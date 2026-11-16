from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from apps.accounts import totp

User = get_user_model()
PASSWORD = "pw-for-tests-only-7"


class AdminSignInTests(TestCase):
    def setUp(self):
        cache.clear()
        self.url = reverse("admin:login")
        self.plain = User.objects.create_superuser(username="plain", email="plain@example.com", password=PASSWORD)
        self.guarded = User.objects.create_superuser(username="guarded", email="guarded@example.com", password=PASSWORD)
        self.guarded.totp_secret = totp.new_secret()
        self.guarded.totp_enabled = True
        self.guarded.save()

    def sign_in(self, username, password=PASSWORD, otp=""):
        return self.client.post(self.url, {"username": username, "password": password, "otp": otp, "next": "/admin/"})

    def code(self):
        return totp._code_at(self.guarded.totp_secret, totp.current_step())

    def test_account_without_two_factor_signs_in_with_its_password(self):
        self.assertEqual(self.sign_in("plain").status_code, 302)

    def test_two_factor_account_needs_a_valid_code(self):
        response = self.sign_in("guarded")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "authenticator app")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.sign_in("guarded", otp="000000").status_code, 200)

    def test_valid_code_signs_in_once_and_cannot_be_replayed(self):
        code = self.code()
        self.assertEqual(self.sign_in("guarded", otp=code).status_code, 302)
        self.client.logout()
        self.assertEqual(self.sign_in("guarded", otp=code).status_code, 200)

    def test_repeated_failures_lock_the_account_for_a_while(self):
        for _ in range(5):
            self.sign_in("plain", password="wrong")
        response = self.sign_in("plain")  # even the right password is refused now
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Too many sign-in attempts")
        cache.clear()
        self.assertEqual(self.sign_in("plain").status_code, 302)

    def test_sign_in_page_offers_the_code_field(self):
        self.assertContains(self.client.get(self.url), 'name="otp"')

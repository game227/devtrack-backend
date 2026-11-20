import threading

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, TransactionTestCase
from rest_framework.test import APIClient

from . import totp
from .two_factor import accept_second_factor

User = get_user_model()
PASSWORD = "Zx9-unique-pass-77"


class TotpAlgorithmTests(TestCase):
    def test_rfc6238_reference_vector(self):
        # RFC 6238 appendix B, SHA-1, T = 59 s -> 94287082 (8 digits); our 6-digit code is its last six.
        secret = __import__("base64").b32encode(b"12345678901234567890").decode()
        self.assertEqual(totp._code_at(secret, 59 // 30), "287082")

    def test_accepts_one_step_of_drift_and_nothing_else(self):
        secret = totp.new_secret()
        now = 1_800_000_000
        for offset, accepted in ((-60, False), (-30, True), (0, True), (30, True), (60, False)):
            code = totp._code_at(secret, totp.current_step(now + offset))
            self.assertEqual(totp.matching_step(secret, code, now=now) is not None, accepted, offset)
        for junk in ("", "12345", "1234567", "abcdef", None, "١٢٣٤٥٦"):
            self.assertIsNone(totp.matching_step(secret, junk, now=now), junk)


class TwoFactorFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="tf", email="tf@example.com", password=PASSWORD)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def login(self, **extra):
        return APIClient().post("/api/v1/auth/login/", {"username": "tf", "password": PASSWORD, **extra}, format="json")

    def enable(self):
        secret = self.client.post("/api/v1/auth/2fa/setup/", {"password": PASSWORD}, format="json").data["secret"]
        code = totp._code_at(secret, totp.current_step())
        response = self.client.post("/api/v1/auth/2fa/enable/", {"code": code}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        return secret, response.data["recovery_codes"]

    def test_setup_needs_the_password_and_is_inactive_until_confirmed(self):
        self.assertEqual(self.client.post("/api/v1/auth/2fa/setup/", {"password": "wrong"}, format="json").status_code, 400)
        data = self.client.post("/api/v1/auth/2fa/setup/", {"password": PASSWORD}, format="json").data
        self.assertTrue(data["otpauth_uri"].startswith("otpauth://totp/DevTrack%3Atf?secret="))
        self.assertEqual(self.login().status_code, 200)  # not on yet
        self.assertEqual(self.client.post("/api/v1/auth/2fa/enable/", {"code": "000000"}, format="json").status_code, 400)

    def test_once_on_sign_in_needs_a_fresh_code_and_each_code_works_once(self):
        secret, _ = self.enable()
        self.assertTrue(User.objects.get(pk=self.user.pk).totp_enabled)
        missing = self.login()
        self.assertEqual(missing.status_code, 400)
        self.assertIn("otp", missing.data)
        self.assertNotIn("access", missing.data)
        self.assertEqual(self.login(otp="123456").status_code, 400)
        self.assertEqual(self.login(username="tf", password="wrong", otp="123456").status_code, 401)

        # The step used to enable it is spent; the next one works, once.
        next_code = totp._code_at(secret, totp.current_step() + 1)
        ok = self.login(otp=next_code)
        self.assertEqual(ok.status_code, 200, ok.data)
        self.assertTrue(ok.data["user"]["totp_enabled"])
        self.assertEqual(self.login(otp=next_code).status_code, 400)  # replayed

    def test_recovery_codes_work_once(self):
        _, codes = self.enable()
        self.assertEqual(len(codes), 10)
        self.assertEqual(self.login(otp=codes[0].upper()).status_code, 200)
        self.assertEqual(self.login(otp=codes[0]).status_code, 400)

    def test_enabling_ends_password_only_sessions(self):
        from rest_framework_simplejwt.tokens import RefreshToken

        old = str(RefreshToken.for_user(self.user))
        self.enable()
        self.assertEqual(APIClient().post("/api/v1/auth/token/refresh/", {"refresh": old}, format="json").status_code, 401)

    def test_turning_it_off_needs_password_and_code(self):
        secret, codes = self.enable()
        url = "/api/v1/auth/2fa/disable/"
        self.assertEqual(self.client.post(url, {"password": PASSWORD, "code": "000000"}, format="json").status_code, 400)
        self.assertEqual(self.client.post(url, {"password": "wrong", "code": codes[1]}, format="json").status_code, 400)
        self.assertEqual(self.client.post(url, {"password": PASSWORD, "code": codes[1]}, format="json").status_code, 204)
        user = User.objects.get(pk=self.user.pk)
        self.assertEqual((user.totp_enabled, user.totp_secret, user.totp_recovery_codes), (False, None, []))
        self.assertEqual(self.login().status_code, 200)

    def test_the_secret_is_encrypted_at_rest(self):
        secret, _ = self.enable()
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("select totp_secret from accounts_user where id = %s", [self.user.pk])
            stored = cursor.fetchone()[0]
        self.assertNotIn(secret, stored)




class RecoveryCodeStorageTests(TestCase):
    def test_codes_carry_80_bits_and_are_stored_salted(self):
        codes = totp.new_recovery_codes()
        self.assertEqual(len(set(codes)), 10)
        for code in codes:
            self.assertRegex(code, r"^[0-9a-f]{10}-[0-9a-f]{10}$")
        first, second = totp.hash_recovery_code(codes[0]), totp.hash_recovery_code(codes[0])
        self.assertNotEqual(first, second)  # a fresh salt each time: no shared table across accounts
        self.assertNotIn(codes[0].replace("-", ""), first)

    def test_consuming_matches_spacing_and_case_variants_and_nothing_else(self):
        codes = totp.new_recovery_codes(3)
        stored = [totp.hash_recovery_code(code) for code in codes]
        variant = codes[1].upper().replace("-", " - ")
        self.assertEqual(totp.consume_recovery_code(stored, variant), [stored[0], stored[2]])
        for wrong in ("123456", "", "zz" * 10, codes[1][:-1]):
            self.assertIsNone(totp.consume_recovery_code(stored, wrong), wrong)


class TwoFactorEndpointRulesTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user(username="rules", email="rules@example.com", password=PASSWORD)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_setup_twice_returns_the_same_pending_key(self):
        first = self.client.post("/api/v1/auth/2fa/setup/", {"password": PASSWORD}, format="json").data
        second = self.client.post("/api/v1/auth/2fa/setup/", {"password": PASSWORD}, format="json").data
        self.assertEqual(first["secret"], second["secret"])

    def test_enable_when_already_on_says_so(self):
        secret = self.client.post("/api/v1/auth/2fa/setup/", {"password": PASSWORD}, format="json").data["secret"]
        self.client.post("/api/v1/auth/2fa/enable/", {"code": totp._code_at(secret, totp.current_step())}, format="json")
        again = self.client.post("/api/v1/auth/2fa/enable/", {"code": "123456"}, format="json")
        self.assertEqual((again.status_code, str(again.data["detail"])), (400, "Two-factor authentication is already on."))

    def test_password_checking_endpoints_are_rate_limited(self):
        from .throttling import AccountTwoFactorThrottle, PasswordCheckRateThrottle

        for throttle, scope in ((AccountTwoFactorThrottle, "two_factor"), (PasswordCheckRateThrottle, "password_check")):
            original = throttle.THROTTLE_RATES
            throttle.THROTTLE_RATES = {**original, scope: "2/min"}
            self.addCleanup(setattr, throttle, "THROTTLE_RATES", original)
        for url, body in (
            ("/api/v1/auth/2fa/setup/", {"password": "guess"}),
            ("/api/v1/auth/password/change/", {"old_password": "guess", "new_password": "x", "new_password_confirm": "x"}),
            ("/api/v1/auth/me/delete/", {"password": "guess"}),
        ):
            cache.clear()
            codes = [self.client.post(url, body, format="json").status_code for _ in range(3)]
            self.assertEqual(codes, [400, 400, 429], url)


class ConcurrentSecondFactorTests(TransactionTestCase):
    """Real threads and connections: one code, two simultaneous sign-ins, exactly one may succeed."""

    def setUp(self):
        self.user = User.objects.create_user(username="race", email="race@example.com", password=PASSWORD)
        self.secret = totp.new_secret()
        self.codes = totp.new_recovery_codes(4)
        User.objects.filter(pk=self.user.pk).update(
            totp_enabled=True,
            totp_secret=None,
            totp_recovery_codes=[totp.hash_recovery_code(code) for code in self.codes],
        )
        user = User.objects.get(pk=self.user.pk)
        user.totp_secret = self.secret  # through the model, so it is stored encrypted
        user.save(update_fields=["totp_secret"])

    def race(self, codes):
        barrier = threading.Barrier(len(codes))
        results = []

        def attempt(code):
            try:
                user = User.objects.get(pk=self.user.pk)
                barrier.wait()
                results.append(accept_second_factor(user, code))
            finally:
                connection.close()

        threads = [threading.Thread(target=attempt, args=(code,)) for code in codes]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return results

    def test_the_same_authenticator_code_works_once(self):
        code = totp._code_at(self.secret, totp.current_step())
        self.assertEqual(sorted(self.race([code, code, code])), [False, False, True])

    def test_the_same_recovery_code_works_once(self):
        self.assertEqual(sorted(self.race([self.codes[0], self.codes[0]])), [False, True])

    def test_two_different_recovery_codes_are_both_consumed(self):
        self.assertEqual(self.race([self.codes[1], self.codes[2]]), [True, True])
        left = User.objects.get(pk=self.user.pk).totp_recovery_codes
        self.assertEqual(len(left), 2)  # neither write undid the other

import shutil
import tempfile
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from .throttling import PasswordResetEmailThrottle

User = get_user_model()
STRONG = "Zx9-unique-pass-77"
NEWER = "N3w-strong-pass-42"


def register(client, **overrides):
    body = {"username": "newbie", "email": "newbie@example.com", "password": STRONG, "password_confirm": STRONG}
    body.update(overrides)
    return client.post("/api/v1/auth/register/", body, format="json")


class RegistrationIdentityTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_a_normal_registration_works_and_lowercases_the_email(self):  # positive control
        response = register(self.client, email="Newbie@Example.COM")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(User.objects.get(username="newbie").email, "newbie@example.com")

    def test_usernames_that_differ_only_by_case_collide(self):
        register(self.client, username="Jane", email="jane@example.com")
        self.assertEqual(register(self.client, username="jane", email="other@example.com").status_code, 400)
        self.assertEqual(register(self.client, username="JANE", email="other@example.com").status_code, 400)

    def test_emails_that_differ_only_by_case_collide(self):
        register(self.client, username="one", email="same@example.com")
        self.assertEqual(register(self.client, username="two", email="SAME@example.com").status_code, 400)

    def test_look_alike_usernames_from_other_scripts_are_refused(self):
        self.assertEqual(register(self.client, username="аdmin").status_code, 400)  # Cyrillic "а"

    def test_an_email_is_required(self):
        response = self.client.post(
            "/api/v1/auth/register/",
            {"username": "noemail", "password": STRONG, "password_confirm": STRONG},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_login_with_a_non_string_username_is_a_400_not_a_crash(self):
        client = APIClient(raise_request_exception=False)
        for body in ({"username": ["a"], "password": "x"}, {"username": {"a": 1}, "password": "x"}, [1, 2]):
            self.assertEqual(client.post("/api/v1/auth/login/", body, format="json").status_code, 400, body)


class SessionsEndWithThePasswordTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sess", email="sess@example.com", password=STRONG)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def refresh(self, token):
        return APIClient().post("/api/v1/auth/token/refresh/", {"refresh": token}, format="json").status_code

    def change_password(self):
        return self.client.post(
            "/api/v1/auth/password/change/",
            {"old_password": STRONG, "new_password": NEWER, "new_password_confirm": NEWER},
            format="json",
        )

    def test_changing_the_password_revokes_other_sessions_and_issues_a_fresh_pair(self):
        stolen = str(RefreshToken.for_user(self.user))
        self.assertEqual(self.refresh(stolen), 200)  # (rotation: this one is now spent, mint another)
        stolen = str(RefreshToken.for_user(self.user))
        response = self.change_password()
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.refresh(stolen), 401)
        self.assertEqual(self.refresh(response.data["refresh"]), 200)  # the current session carries on

    def test_resetting_the_password_revokes_every_session(self):
        from django.contrib.auth.tokens import PasswordResetTokenGenerator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        old = str(RefreshToken.for_user(self.user))
        response = APIClient().post(
            "/api/v1/auth/password/reset/confirm/",
            {
                "uid": urlsafe_base64_encode(force_bytes(self.user.pk)),
                "token": PasswordResetTokenGenerator().make_token(self.user),
                "new_password": NEWER,
                "new_password_confirm": NEWER,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.refresh(old), 401)

    def test_deleting_the_account_revokes_every_session(self):
        old = str(RefreshToken.for_user(self.user))
        self.assertEqual(self.client.post("/api/v1/auth/me/delete/", {"password": STRONG}, format="json").status_code, 204)
        self.assertEqual(self.refresh(old), 401)


class PasswordResetFloodTests(TestCase):
    """One person's inbox must not be floodable by rotating the caller's IP (or forging X-Forwarded-For)."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        original = PasswordResetEmailThrottle.THROTTLE_RATES
        PasswordResetEmailThrottle.THROTTLE_RATES = {**original, "password_reset_email": "2/hour"}
        self.addCleanup(setattr, PasswordResetEmailThrottle, "THROTTLE_RATES", original)
        User.objects.create_user(username="victim", email="victim@example.com", password=STRONG)

    def request_reset(self, email, forwarded_for):
        return APIClient().post(
            "/api/v1/auth/password/reset/", {"email": email}, format="json", HTTP_X_FORWARDED_FOR=forwarded_for
        )

    def test_the_target_address_is_capped_whatever_the_callers_ip(self):
        codes = [self.request_reset("victim@example.com", f"10.0.0.{i}").status_code for i in range(5)]
        self.assertEqual(codes, [200, 200, 429, 429, 429])
        self.assertEqual(len(mail.outbox), 2)

    def test_case_variations_of_the_address_share_one_budget(self):
        codes = [self.request_reset(e, "1.1.1.1").status_code for e in ("victim@example.com", "VICTIM@example.com", "Victim@Example.com")]
        self.assertEqual(codes, [200, 200, 429])

    def test_other_addresses_are_unaffected_and_unknown_ones_are_limited_the_same_way(self):
        self.assertEqual(self.request_reset("victim@example.com", "2.2.2.2").status_code, 200)
        self.assertEqual([self.request_reset("ghost@example.com", "3.3.3.3").status_code for _ in range(3)], [200, 200, 429])


def png_bytes(size=(8, 8), colour="red"):
    buffer = BytesIO()
    Image.new("RGB", size, colour).save(buffer, "PNG")
    return buffer.getvalue()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="devtrack-test-media-"))
class AvatarUploadTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        from django.conf import settings

        shutil.rmtree(settings.MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.user = User.objects.create_user(username="pic", email="pic@example.com", password=STRONG)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def upload(self, content, name="me.png", content_type="image/png"):
        return self.client.patch("/api/v1/auth/me/", {"avatar": SimpleUploadedFile(name, content, content_type)}, format="multipart")

    def test_a_valid_image_is_stored_under_a_random_name(self):
        response = self.upload(png_bytes(), name="../../evil name.png")
        self.assertEqual(response.status_code, 200, response.data)
        self.user.refresh_from_db()
        stored = self.user.avatar.name
        self.assertRegex(stored, r"^avatars/[0-9a-f]{32}\.png$")
        self.assertNotIn("evil", stored)

    def test_exif_metadata_is_stripped(self):
        exif = Image.Exif()
        exif[0x010F] = "SecretCameraMaker"  # Make
        buffer = BytesIO()
        Image.new("RGB", (8, 8), "blue").save(buffer, "JPEG", exif=exif)
        self.assertEqual(Image.open(BytesIO(buffer.getvalue())).getexif().get(0x010F), "SecretCameraMaker")  # control

        self.assertEqual(self.upload(buffer.getvalue(), "p.jpg", "image/jpeg").status_code, 200)
        self.user.refresh_from_db()
        with self.user.avatar.open("rb") as stored:
            self.assertNotIn(b"SecretCameraMaker", stored.read())

    def test_things_that_are_not_safe_images_are_refused(self):
        buffer = BytesIO()
        Image.new("RGB", (8, 8)).save(buffer, "GIF")
        cases = {
            "not an image": (b"<script>alert(1)</script>", "x.png", "image/png"),
            "svg": (b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>', "x.svg", "image/svg+xml"),
            "gif": (buffer.getvalue(), "x.gif", "image/gif"),
            "html disguised as png": (b"<html><body>hi</body></html>", "x.png", "image/png"),
        }
        for label, (content, name, content_type) in cases.items():
            self.assertEqual(self.upload(content, name, content_type).status_code, 400, label)
        self.user.refresh_from_db()
        self.assertFalse(self.user.avatar)

    def test_too_large_in_bytes_or_pixels_is_refused(self):
        self.assertEqual(self.upload(png_bytes() + b"0" * (2 * 1024 * 1024 + 1)).status_code, 400)
        self.assertEqual(self.upload(png_bytes(size=(4001, 4001))).status_code, 400)

    @override_settings(MAX_UPLOAD_BYTES=1000)
    def test_an_oversized_request_is_refused_before_it_is_read(self):
        response = self.upload(png_bytes(size=(200, 200)) + b"0" * 5000)
        self.assertEqual(response.status_code, 400)
        self.user.refresh_from_db()
        self.assertFalse(self.user.avatar)

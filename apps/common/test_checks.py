from django.test import SimpleTestCase, override_settings
from rest_framework.exceptions import ValidationError

from .checks import check_required_secrets
from .lookup import parse_id

HEALTHY = dict(
    SECRET_KEY="k" * 50,
    FIELD_ENCRYPTION_KEY="some-key",
    TELEGRAM_BOT_USERNAME="bot",
    TELEGRAM_LINK_SECRET="link",
    BOT_SERVICE_API_KEY="bot-key",
    GITHUB_CLIENT_ID="gh",
    GITHUB_WEBHOOK_SECRET="hook",
    ALLOWED_HOSTS=["devtrack.example.com"],
)


def failing_checks(**overrides):
    with override_settings(**{**HEALTHY, **overrides}):
        return {error.id for error in check_required_secrets(None)}


class DeploymentChecksTests(SimpleTestCase):
    def test_a_complete_configuration_passes(self):
        self.assertEqual(failing_checks(), set())

    def test_a_short_or_placeholder_signing_key_is_an_error(self):
        for key in ("short", "change-me-in-production-" + "x" * 30, "django-insecure-" + "x" * 40):
            self.assertIn("devtrack.E001", failing_checks(SECRET_KEY=key), key)

    def test_a_missing_encryption_key_is_an_error(self):
        self.assertIn("devtrack.E002", failing_checks(FIELD_ENCRYPTION_KEY="  "))

    def test_a_configured_bot_needs_both_of_its_secrets(self):
        self.assertIn("devtrack.E003", failing_checks(TELEGRAM_LINK_SECRET=""))
        self.assertIn("devtrack.E003", failing_checks(BOT_SERVICE_API_KEY=""))
        self.assertEqual(failing_checks(TELEGRAM_BOT_USERNAME="", TELEGRAM_LINK_SECRET="", BOT_SERVICE_API_KEY=""), set())

    def test_github_without_a_webhook_secret_is_an_error(self):
        self.assertIn("devtrack.E004", failing_checks(GITHUB_WEBHOOK_SECRET=""))

    def test_wildcard_hosts_and_open_cors_are_errors(self):
        self.assertIn("devtrack.E005", failing_checks(ALLOWED_HOSTS=["*"]))
        self.assertIn("devtrack.E006", failing_checks(CORS_ALLOW_ALL_ORIGINS=True))


class ParseIdTests(SimpleTestCase):
    def test_accepts_positive_integers_and_digit_strings(self):
        self.assertEqual((parse_id(5, "x"), parse_id("17", "x")), (5, 17))

    def test_everything_else_is_a_validation_error_for_that_field(self):
        for bad in (None, "", "abc", "1.5", "-3", "0", 0, -1, 1.5, True, [1], {"a": 1}, "١٢", "9" * 30, 2**63):
            with self.assertRaises(ValidationError, msg=repr(bad)) as caught:
                parse_id(bad, "project")
            self.assertIn("project", caught.exception.detail)

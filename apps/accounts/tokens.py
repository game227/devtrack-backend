from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    # A distinct salt scopes this generator's tokens away from password-reset
    # tokens (same base algorithm, different secret derivation) — one can
    # never be replayed as the other. Mixing in email_verified means a token
    # stops working the moment it's used once, same as the base class does
    # with is_active/last_login.
    key_salt = "apps.accounts.email_verification"

    def _make_hash_value(self, user, timestamp):
        return f"{user.pk}{user.email}{user.email_verified}{timestamp}"


email_verification_token = EmailVerificationTokenGenerator()

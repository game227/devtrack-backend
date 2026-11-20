from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication

from .models import DemoAccount

# What a demo visitor may not do: anything that reaches people or services outside the demo
# (invitations, GitHub, Telegram, email) or fills storage (uploads), or that would hand the account over.
BLOCKED = [
    ("/api/v1/integrations/", None),
    ("/api/v1/telegram/", None),
    ("/api/v1/auth/password/", None),
    ("/api/v1/auth/email/", None),
    ("/api/v1/auth/2fa/", None),
    ("/api/v1/auth/me/", {"PUT", "PATCH"}),
]
BLOCKED_WRITE_SUFFIXES = ("/members/", "/transfer-ownership/", "/attachments/", "/share/")
SAFE = {"GET", "HEAD", "OPTIONS"}


def demo_blocked(request):
    path, method = request.path, request.method
    for prefix, methods in BLOCKED:
        if path.startswith(prefix) and (methods is None or method in methods):
            return True
    return method not in SAFE and path.startswith("/api/v1/") and path.endswith(BLOCKED_WRITE_SUFFIXES) and "/projects/" not in path


class DemoAwareJWTAuthentication(JWTAuthentication):
    """JWT authentication that also keeps demo accounts inside the demo (see BLOCKED)."""

    def authenticate(self, request):
        result = super().authenticate(request)
        # The path test is free; only on a blocked path is the account looked up.
        if result is not None and demo_blocked(request) and DemoAccount.objects.filter(user=result[0]).exists():
            raise PermissionDenied("This is not available in the demo.")
        return result

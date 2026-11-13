from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle, UserRateThrottle


def _clean(value):
    """A comparable identifier from request input. Non-strings (a JSON list/object sent on purpose)
    count as "no identifier" instead of crashing the throttle with an AttributeError."""
    return value.strip().lower() if isinstance(value, str) else ""


def _body(request):
    data = request.data
    return data if hasattr(data, "get") else {}


class AccountLoginRateThrottle(SimpleRateThrottle):
    """Rate-limits login attempts by the submitted account, not the caller's
    IP — the existing AnonRateThrottle stops a single IP from hammering the
    endpoint, but not a distributed brute-force against one specific account
    from many IPs. Requests with no username/email in the body pass through
    unthrottled by this class (still limited by AnonRateThrottle)."""

    scope = "login_account"

    def get_cache_key(self, request, view):
        body = _body(request)
        identifier = _clean(body.get("username")) or _clean(body.get("email"))
        if not identifier:
            return None
        return self.cache_format % {"scope": self.scope, "ident": identifier}


class PasswordResetEmailThrottle(SimpleRateThrottle):
    """Caps password-reset requests per *target address*, whoever asks and from wherever.

    The per-IP limit alone cannot stop someone from flooding one person's inbox: the client address can
    be rotated (or forged, when X-Forwarded-For is trusted too widely). This key is the email itself, so
    it holds regardless. It applies to every address, existing or not, so it leaks nothing about accounts.
    """

    scope = "password_reset_email"

    def get_cache_key(self, request, view):
        email = _clean(_body(request).get("email"))
        if not email:
            return None
        return self.cache_format % {"scope": self.scope, "ident": email}


class RegisterRateThrottle(AnonRateThrottle):
    scope = "register"


class EmailVerifyResendThrottle(UserRateThrottle):
    scope = "email_verify_resend"


class MemberAddRateThrottle(UserRateThrottle):
    """Adding people to a workspace/project/team is instant and notifies them, so it is capped per user."""

    scope = "member_add"


class GithubSyncRateThrottle(UserRateThrottle):
    """A manual GitHub sync spends the connector's GitHub API quota; keep one user from burning it."""

    scope = "github_sync"

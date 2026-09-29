from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle


class AccountLoginRateThrottle(SimpleRateThrottle):
    """Rate-limits login attempts by the submitted account, not the caller's
    IP — the existing AnonRateThrottle stops a single IP from hammering the
    endpoint, but not a distributed brute-force against one specific account
    from many IPs. Requests with no username/email in the body pass through
    unthrottled by this class (still limited by AnonRateThrottle)."""

    scope = "login_account"

    def get_cache_key(self, request, view):
        identifier = (request.data.get("username") or request.data.get("email") or "").strip().lower()
        if not identifier:
            return None
        return self.cache_format % {"scope": self.scope, "ident": identifier}


class EmailVerifyResendThrottle(UserRateThrottle):
    scope = "email_verify_resend"

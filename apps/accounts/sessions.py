from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken


def revoke_all_sessions(user):
    """Blacklist every refresh token the user has outstanding — after a password change or reset, a
    stolen or forgotten refresh token must stop working, not keep minting access tokens for two weeks."""
    BlacklistedToken.objects.bulk_create(
        [BlacklistedToken(token=token) for token in OutstandingToken.objects.filter(user=user).exclude(blacklistedtoken__isnull=False)],
        ignore_conflicts=True,
    )

"""Second factor checks shared by sign-in and by turning two-factor authentication off."""

from django.contrib.auth import get_user_model
from django.db import transaction

from . import totp


def accept_second_factor(user, code):
    """True if `code` is a fresh authenticator code or an unused recovery code; consumes it either way.

    A code is good for one use: the time step it belongs to is remembered, so a code seen over someone's
    shoulder (or replayed from a log) cannot be used again within its 30-second life, and a recovery code
    is removed once used. The check and the consumption happen on the locked user row, so two requests
    carrying the same code at the same moment cannot both pass, and two different recovery codes used at
    once are both removed (neither write can undo the other).
    """
    if not code:
        return False
    with transaction.atomic():
        locked = get_user_model().objects.select_for_update().get(pk=user.pk)
        if not (locked.totp_enabled and locked.totp_secret):
            return False

        step = totp.matching_step(locked.totp_secret, code)
        if step is not None:
            if locked.totp_last_step is not None and step <= locked.totp_last_step:
                return False  # already used (a replay), even if it is still within its 30 seconds
            locked.totp_last_step = step
            locked.save(update_fields=["totp_last_step"])
            user.totp_last_step = step
            return True

        remaining = totp.consume_recovery_code(locked.totp_recovery_codes, code)
        if remaining is None:
            return False
        locked.totp_recovery_codes = remaining
        locked.save(update_fields=["totp_recovery_codes"])
        user.totp_recovery_codes = remaining
        return True

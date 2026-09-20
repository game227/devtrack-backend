from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings
from django.db import models


def _fernet():
    """FIELD_ENCRYPTION_KEY may hold several comma-separated Fernet keys.

    The first key encrypts new values; every key can decrypt, so a key can be
    rotated without losing stored data: put the new key first, keep the old one
    after it, run ``manage.py rotate_encryption_key``, then drop the old key.
    """
    keys = [key.strip() for key in settings.FIELD_ENCRYPTION_KEY.split(",") if key.strip()]
    return MultiFernet([Fernet(key.encode()) for key in keys])


class EncryptedCharField(models.CharField):
    """A CharField that is encrypted (Fernet — symmetric, authenticated) at
    rest and transparently decrypted on load. Application code always sees
    the plaintext value; only the database column ever holds ciphertext."""

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None:
            return value
        return _fernet().encrypt(value.encode()).decode()

    def from_db_value(self, value, expression, connection):
        if value is None:
            return value
        return _fernet().decrypt(value.encode()).decode()

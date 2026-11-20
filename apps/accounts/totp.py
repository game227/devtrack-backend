"""Time-based one-time passwords (RFC 6238, the scheme every authenticator app speaks).

Implemented with the standard library: HMAC-SHA1, 30-second steps, 6 digits.
"""

import base64
import hashlib
import hmac
import re
import secrets
import struct
import time
from urllib.parse import quote, urlencode

STEP_SECONDS = 30
DIGITS = 6
ISSUER = "DevTrack"


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code_at(secret, step):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def current_step(now=None):
    return int((time.time() if now is None else now) // STEP_SECONDS)


def matching_step(secret, code, now=None, window=1):
    """The time step `code` belongs to (allowing one step of clock drift either way), or None."""
    code = "".join(str(code or "").split())
    if not (code.isascii() and code.isdigit() and len(code) == DIGITS):
        return None
    step = current_step(now)
    for candidate in range(step - window, step + window + 1):
        if hmac.compare_digest(_code_at(secret, candidate), code):
            return candidate
    return None


def provisioning_uri(secret, account_name):
    label = quote(f"{ISSUER}:{account_name}")
    return f"otpauth://totp/{label}?{urlencode({'secret': secret, 'issuer': ISSUER, 'digits': DIGITS, 'period': STEP_SECONDS})}"


# Recovery codes carry 80 random bits (20 hex digits, shown as two groups of ten). Stored hashes are
# salted per code, so even a leaked database gives no shortcut: each code would have to be guessed on its
# own, over a 2^80 space.
RECOVERY_CODE_RE = re.compile(r"^[0-9a-f]{20}$")


def new_recovery_codes(count=10):
    return [f"{secrets.token_hex(5)}-{secrets.token_hex(5)}" for _ in range(count)]


def _normalize_recovery_code(code):
    return "".join(str(code).lower().split()).replace("-", "")


def hash_recovery_code(code, salt=None):
    salt = salt or secrets.token_hex(8)
    digest = hashlib.sha256(f"{salt}:{_normalize_recovery_code(code)}".encode()).hexdigest()
    return f"{salt}${digest}"


def consume_recovery_code(stored, code):
    """`stored` without the entry `code` matches, or None if it matches none of them."""
    if not RECOVERY_CODE_RE.match(_normalize_recovery_code(code)):
        return None  # not shaped like a recovery code (e.g. a wrong 6-digit code): nothing to compare
    for entry in stored:
        salt, _, _digest = entry.partition("$")
        if salt and hmac.compare_digest(hash_recovery_code(code, salt), entry):
            return [other for other in stored if other != entry]
    return None

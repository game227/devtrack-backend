"""Small helpers for turning request input into database lookups safely."""

from rest_framework.exceptions import ValidationError

MAX_ID = 2**63 - 1


def parse_id(raw, field):
    """A positive integer id taken from a query string or request body.

    Anything else (missing, "abc", a list, a float, a bool, an absurdly large number) is a 400 for
    that field. Without this, ``get_object_or_404(Model, pk="abc")`` raises ``ValueError`` and the
    caller sees a 500 — noise in the error tracker and a free way to probe the API.
    """
    if isinstance(raw, bool) or raw is None or raw == "":
        raise ValidationError({field: "This field is required."})
    if isinstance(raw, int):
        value = raw
    elif isinstance(raw, str) and raw.isascii() and raw.isdigit():
        value = int(raw)
    else:
        raise ValidationError({field: "A valid integer id is required."})
    if not 0 < value <= MAX_ID:
        raise ValidationError({field: "A valid integer id is required."})
    return value


def body_value(request, key):
    """``request.data[key]`` when the body is a JSON object / form; None for a list, string or nothing.

    ``request.data.get`` raises AttributeError (-> 500) when a client posts ``[1, 2]`` as the body.
    """
    data = request.data
    return data.get(key) if hasattr(data, "get") else None

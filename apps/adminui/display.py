"""Small display helpers shared by the ModelAdmins, so lists read like the web app (chips, keys)."""

from django.utils.html import format_html


def chip(css_class: str, label: str):
    """A rounded label with a coloured dot; the colour comes from the class (see admin.css)."""
    return format_html('<span class="dt-chip {}">{}</span>', css_class, label)


def key(number) -> str:
    return format_html('<span class="dt-key">#{}</span>', number)


def excerpt(text: str, length: int = 80) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= length else text[: length - 1] + "…"

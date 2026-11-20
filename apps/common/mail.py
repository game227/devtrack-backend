"""One look for every email DevTrack sends: a branded HTML part with a plain-text twin.

The HTML is built the way mail clients need it (tables, inline styles, no images or scripts), and every
value that comes from people (names, titles) is escaped by the caller with django.utils.html.escape
or format_html before it gets here.
"""

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils.html import escape

INK = "#141414"
BODY = "#3a3a38"
MUTED = "#76766f"
LINE = "#e3e3e0"
PAGE = "#e9e9e7"
ORANGE = "#f05a16"
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"


def send_email(subject, text, to, html=None, fail_silently=False):
    """Send one message; replies go to the support address rather than the sending domain."""
    reply_to = [settings.SUPPORT_EMAIL] if settings.SUPPORT_EMAIL else None
    message = EmailMultiAlternatives(subject=subject, body=text, to=[to], reply_to=reply_to)
    if html:
        message.attach_alternative(html, "text/html")
    message.send(fail_silently=fail_silently)


def paragraph(html, *, muted=False, small=False):
    size = "13px" if small else "15px"
    colour = MUTED if muted else BODY
    return f'<p style="margin:0 0 14px;font:{size}/1.6 {FONT};color:{colour}">{html}</p>'


def button(label, url):
    """A button that survives Outlook: a table cell with the link filling it."""
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:22px 0 18px">'
        f'<tr><td style="border-radius:10px;background:{INK}">'
        f'<a href="{escape(url)}" style="display:inline-block;padding:13px 22px;font:600 15px/1 {FONT};'
        f'color:#ffffff;text-decoration:none;border-radius:10px">{escape(label)}</a>'
        "</td></tr></table>"
    )


def link_fallback(note, url):
    """For mail clients that block buttons: the address itself, to copy."""
    return paragraph(
        f'{escape(note)}<br><a href="{escape(url)}" style="color:{INK};word-break:break-all">{escape(url)}</a>',
        muted=True,
        small=True,
    )


def layout(*, lang, preheader, heading, body_html, footer_html=""):
    """The whole message: the DevTrack line on top, a white card with the content, a quiet footer."""
    logo = (
        f'<span style="font:700 15px/1 {FONT};color:{INK};letter-spacing:-1px">&#9679;&#8212;&#9679;</span>'
        f'<span style="font:700 15px/1 {FONT};color:{ORANGE}">&#9679;</span>'
        f'<span style="font:600 18px/1 {FONT};color:{INK};letter-spacing:-0.02em;padding-left:8px">DevTrack</span>'
    )
    footer = footer_html or ""
    return (
        f'<!doctype html><html lang="{escape(lang)}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">'
        f"<title>{escape(heading)}</title></head>"
        f'<body style="margin:0;padding:0;background:{PAGE}">'
        # The inbox preview line, hidden in the message itself.
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0">{escape(preheader)}</div>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{PAGE}">'
        '<tr><td align="center" style="padding:32px 12px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px">'
        f'<tr><td style="padding:0 6px 18px">{logo}</td></tr>'
        f'<tr><td style="background:#ffffff;border:1px solid {LINE};border-radius:16px;padding:30px 28px 18px">'
        f'<h1 style="margin:0 0 16px;font:600 23px/1.25 {FONT};color:{INK};letter-spacing:-0.02em">{escape(heading)}</h1>'
        f"{body_html}</td></tr>"
        f'<tr><td style="padding:18px 6px 0;font:12px/1.6 {FONT};color:{MUTED}">{footer}</td></tr>'
        "</table></td></tr></table></body></html>"
    )

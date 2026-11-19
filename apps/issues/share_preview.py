"""Link previews for shared issues.

A share link points at /s/<token>. Chat apps (Telegram, Slack, ...) fetch it and read its Open Graph tags,
so the preview names the issue and shows a card with its place on the line; people are sent straight on to
the read-only page in the web app. Both answer only while the link is live, with nothing beyond what the
public page itself shows (number, title, project, status, due date).
"""

import io
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.urls import reverse
from django.utils.html import escape
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from .models import IssueShareLink
from .tools import PublicIssueThrottle

LANGS = ("uz", "en", "ru")
STATIONS = ("backlog", "todo", "in_progress", "in_review", "done")

TEXT = {
    "uz": {
        "status": {"backlog": "Zaxira", "todo": "Qilinadigan", "in_progress": "Jarayonda", "in_review": "Ko'rib chiqilmoqda", "done": "Bajarildi"},
        "due": "Muddat: {date}",
        "open": "Vazifani ochish",
        "gone": "Bu havolaning muddati tugagan yoki u bekor qilingan.",
    },
    "en": {
        "status": {"backlog": "Backlog", "todo": "Todo", "in_progress": "In progress", "in_review": "In review", "done": "Done"},
        "due": "Due {date}",
        "open": "Open the issue",
        "gone": "This link has expired or was revoked.",
    },
    "ru": {
        "status": {"backlog": "Бэклог", "todo": "К выполнению", "in_progress": "В работе", "in_review": "На проверке", "done": "Готово"},
        "due": "Срок: {date}",
        "open": "Открыть задачу",
        "gone": "Срок действия ссылки истёк, или её отозвали.",
    },
}

# The same palette as the site's own social card (public/og.png).
BG = (206, 206, 204)
GRID = (225, 225, 223)
INK = (17, 17, 17)
MUTED = (119, 119, 117)
SOFT = (171, 171, 170)
PILL = (228, 228, 227)
ORANGE = (240, 90, 22)
STATION_RGB = {
    "backlog": (106, 106, 104),
    "todo": (51, 84, 196),
    "in_progress": (191, 76, 11),
    "in_review": (122, 75, 207),
    "done": (25, 122, 67),
}

FONT_DIR = Path(__file__).resolve().parent / "share_fonts"


def _lang(request):
    lang = request.query_params.get("lang", "")
    return lang if lang in LANGS else settings.DIGEST_LANGUAGE if settings.DIGEST_LANGUAGE in LANGS else "en"


def _live_link(token):
    link = IssueShareLink.objects.select_related("issue__project").filter(token=token).first()
    if link is None or not link.is_live():
        return None
    return link


# --- Drawing ------------------------------------------------------------------------------------------
# Geist (SIL OFL, see share_fonts/OFL.txt) comes as the web subsets the frontend ships, so each character
# is drawn with the subset that has it: Cyrillic for Russian, Latin (and its extension) for the rest.


@lru_cache(maxsize=32)
def _font(subset, size, weight):
    from PIL import ImageFont

    font = ImageFont.truetype(str(FONT_DIR / f"geist-{subset}-wght-normal.woff2"), size)
    font.set_variation_by_axes([weight])
    return font


def _subset(char):
    code = ord(char)
    if 0x0400 <= code <= 0x045F or code in (0x0490, 0x0491, 0x04B0, 0x04B1, 0x2116):
        return "cyrillic"
    if 0x0460 <= code <= 0x052F:
        return "cyrillic-ext"
    if code <= 0xFF or 0x2000 <= code <= 0x206F or code in (0x0131, 0x0152, 0x0153, 0x02BB, 0x02BC, 0x20AC, 0x2122):
        return "latin"
    return "latin-ext"


def _runs(text):
    runs = []
    for char in text:
        subset = _subset(char)
        if runs and runs[-1][0] == subset:
            runs[-1][1] += char
        else:
            runs.append([subset, char])
    return runs


def _width(text, size, weight):
    return sum(_font(subset, size, weight).getlength(run) for subset, run in _runs(text))


def _draw(draw, xy, text, size, weight, fill):
    x, y = xy
    for subset, run in _runs(text):
        font = _font(subset, size, weight)
        draw.text((x, y), run, font=font, fill=fill)
        x += font.getlength(run)
    return x


def _wrap(text, size, weight, width, max_lines):
    words, lines = text.split(), []
    while words and len(lines) < max_lines:
        line = words.pop(0)
        while words and _width(f"{line} {words[0]}", size, weight) <= width:
            line = f"{line} {words.pop(0)}"
        lines.append(line)
    if words or (lines and _width(lines[-1], size, weight) > width):
        last = lines[-1]
        while last and _width(f"{last}…", size, weight) > width:
            last = last[:-1].rstrip()
        lines[-1] = f"{last}…"
    return lines


def render_card(issue, lang):
    """A 1200x630 PNG: the brand, the project, "#12 Title", and the line with the issue's station lit."""
    from PIL import Image, ImageDraw

    text = TEXT[lang]
    scale = 2  # drawn at twice the size and scaled down, for smooth circles and lines
    W, H = 1200 * scale, 630 * scale
    image = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(image)
    s = lambda value: int(round(value * scale))  # noqa: E731

    for x in range(71, 1200, 72):
        draw.line([(s(x), 0), (s(x), H)], fill=GRID, width=s(1))
    for y in range(71, 630, 72):
        draw.line([(0, s(y)), (W, s(y))], fill=GRID, width=s(1))
    for cx, cy, dx, dy in ((28, 28, 1, 1), (1172, 28, -1, 1), (28, 602, 1, -1), (1172, 602, -1, -1)):
        draw.line([(s(cx), s(cy)), (s(cx + 34 * dx), s(cy))], fill=INK, width=s(2))
        draw.line([(s(cx), s(cy)), (s(cx), s(cy + 34 * dy))], fill=INK, width=s(2))

    # The logo: two stations and the orange one, then the name.
    draw.line([(s(92), s(97)), (s(124), s(97))], fill=INK, width=s(4))
    for cx, r, colour in ((92, 6, INK), (114, 6, INK), (136, 9, ORANGE)):
        draw.ellipse([s(cx - r), s(97 - r), s(cx + r), s(97 + r)], fill=colour)
    _draw(draw, (s(160), s(78)), "DevTrack", s(32), 600, INK)

    # The project, as the pill the site's card uses for its tagline.
    project = issue.project.name.upper()
    pill_text = project if _width(project, s(17), 500) <= s(900) else _wrap(project, s(17), 500, s(900), 1)[0]
    pill_w = _width(pill_text, s(17), 500) / scale + 64
    draw.rounded_rectangle([s(85), s(162), s(85 + pill_w), s(198)], radius=s(18), fill=PILL, outline=(196, 196, 194), width=s(1))
    draw.ellipse([s(101), s(175), s(111), s(185)], fill=ORANGE)
    _draw(draw, (s(122), s(169)), pill_text, s(17), 500, INK)

    # "#12" and the title, up to three lines.
    size = 62 if len(issue.title) < 70 else 52
    lines = _wrap(f"#{issue.number}  {issue.title}", s(size), 600, s(1020), 3)
    y = 236
    for index, line in enumerate(lines):
        if index == 0 and line.startswith(f"#{issue.number}"):
            number = f"#{issue.number}"
            x = _draw(draw, (s(85), s(y)), number, s(size), 600, MUTED)
            _draw(draw, (x, s(y)), line[len(number):], s(size), 600, INK)
        else:
            _draw(draw, (s(85), s(y)), line, s(size), 600, INK)
        y += size + 12

    # The line along the bottom: travelled in ink up to the issue's station, which is lit orange.
    xs = [84 + i * (1116 - 84) / 4 for i in range(5)]
    current = STATIONS.index(issue.status) if issue.status in STATIONS else 0
    for i in range(4):
        colour = INK if i < current else SOFT
        draw.line([(s(xs[i]), s(541)), (s(xs[i + 1]), s(541))], fill=colour, width=s(4))
    for i, station in enumerate(STATIONS):
        cx = xs[i]
        if i == current:
            draw.ellipse([s(cx - 15), s(541 - 15), s(cx + 15), s(541 + 15)], fill=BG)
            draw.ellipse([s(cx - 12), s(541 - 12), s(cx + 12), s(541 + 12)], fill=ORANGE)
        else:
            draw.ellipse([s(cx - 8), s(541 - 8), s(cx + 8), s(541 + 8)], fill=STATION_RGB[station])
        label = text["status"][station].upper()
        weight, colour = (700, INK) if i == current else (500, MUTED)
        label_w = _width(label, s(15), weight) / scale
        lx = cx - label_w / 2 if 0 < i < 4 else (cx - 8 if i == 0 else cx + 8 - label_w)
        _draw(draw, (s(lx), s(566)), label, s(15), weight, colour)

    image = image.resize((1200, 630), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


# --- Views --------------------------------------------------------------------------------------------


class ShareCardView(APIView):
    """GET /s/<token>/card.png: the preview image."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [PublicIssueThrottle]

    def get(self, request, token):
        link = _live_link(token)
        if link is None:
            raise NotFound("This link has expired or was revoked.")
        response = HttpResponse(render_card(link.issue, _lang(request)), content_type="image/png")
        response["Cache-Control"] = "public, max-age=300"
        return response


class SharePreviewView(APIView):
    """GET /s/<token>: Open Graph tags for chat apps, and an immediate hop to the web app for people."""

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [PublicIssueThrottle]
    CSP = "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'"

    def get(self, request, token):
        lang = _lang(request)
        text = TEXT[lang]
        link = _live_link(token)
        if link is None:
            page = _page(lang, title="DevTrack", body=f"<p>{escape(text['gone'])}</p>")
            return self._respond(page, status=404)
        issue = link.issue
        target = f"{settings.FRONTEND_URL.rstrip('/')}/share/{token}"
        card = request.build_absolute_uri(reverse("share-card", args=[token])) + f"?lang={lang}"
        title = f"#{issue.number} {issue.title}"
        facts = [issue.project.name, text["status"].get(issue.status, issue.status)]
        if issue.due_date:
            facts.append(text["due"].format(date=issue.due_date.isoformat()))
        description = " · ".join(facts)
        head = "".join(
            f'<meta property="{name}" content="{escape(value)}">'
            for name, value in (
                ("og:type", "article"),
                ("og:site_name", "DevTrack"),
                ("og:title", title),
                ("og:description", description),
                ("og:url", target),
                ("og:image", card),
                ("og:image:width", "1200"),
                ("og:image:height", "630"),
            )
        )
        head += '<meta name="twitter:card" content="summary_large_image">'
        head += f'<meta http-equiv="refresh" content="0; url={escape(target)}">'
        head += f'<link rel="canonical" href="{escape(target)}">'
        body = f'<p><strong>{escape(title)}</strong></p><p>{escape(description)}</p><p><a href="{escape(target)}">{escape(text["open"])}</a></p>'
        return self._respond(_page(lang, title=title, body=body, head=head))

    def _respond(self, page, status=200):
        response = HttpResponse(page, status=status, content_type="text/html; charset=utf-8")
        response["Cache-Control"] = "no-store"
        response["Content-Security-Policy"] = self.CSP
        response["Referrer-Policy"] = "no-referrer"
        response["X-Robots-Tag"] = "noindex"
        return response


def _page(lang, title, body, head=""):
    return (
        f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex">'
        f"<title>{escape(title)} · DevTrack</title>{head}"
        "<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#cecece;"
        "color:#111;font:16px/1.5 system-ui,sans-serif}main{max-width:32rem;padding:2rem}a{color:#111}</style>"
        f"</head><body><main>{body}</main></body></html>"
    )

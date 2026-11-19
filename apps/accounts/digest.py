"""The weekly email to workspace owners and admins: how each project is doing, what is late, what got done.

Plain text with a branded HTML part, in English, Uzbek or Russian (the reader's last chosen UI language is
not stored, so the DIGEST_LANGUAGE default applies). Only workspaces with at least one project are sent.
"""

import datetime as dt

from django.conf import settings
from django.utils import timezone
from django.utils.html import escape

from apps.analytics.health import compute_project_health
from apps.common.mail import BODY, FONT, INK, LINE, MUTED, button, layout, paragraph, send_email
from apps.issues.models import Issue
from apps.workspaces.models import Membership, Workspace

TEXT = {
    "en": {
        "subject": "DevTrack weekly: {workspace}",
        "intro": "Here is how {workspace} did this week.",
        "done": "Done in the last 7 days: {count}",
        "overdue": "Past their due date: {count}",
        "projects": "Projects:",
        "project": "- {name}: health {score}/100, {open} open, {done}% done",
        "late": "Late issues:",
        "late_item": "- #{number} {title} ({project}), due {due}",
        "footer": "Open DevTrack: {link}\nYou get this as a workspace owner or admin. Turn it off in Settings.",
    },
    "uz": {
        "subject": "DevTrack haftalik: {workspace}",
        "intro": "{workspace} ish maydonida bu hafta nimalar bo'ldi.",
        "done": "Oxirgi 7 kunda bajarildi: {count}",
        "overdue": "Muddati o'tgan: {count}",
        "projects": "Loyihalar:",
        "project": "- {name}: salomatlik {score}/100, {open} ta ochiq, {done}% bajarilgan",
        "late": "Kechikkan vazifalar:",
        "late_item": "- #{number} {title} ({project}), muddat {due}",
        "footer": "DevTrack'ni ochish: {link}\nBu xat sizga ish maydoni egasi yoki administratori sifatida keladi. Sozlamalarda o'chirsa bo'ladi.",
    },
    "ru": {
        "subject": "DevTrack за неделю: {workspace}",
        "intro": "Как прошла неделя в {workspace}.",
        "done": "Готово за 7 дней: {count}",
        "overdue": "Просрочено: {count}",
        "projects": "Проекты:",
        "project": "- {name}: здоровье {score}/100, открыто {open}, готово {done}%",
        "late": "Просроченные задачи:",
        "late_item": "- #{number} {title} ({project}), срок {due}",
        "footer": "Открыть DevTrack: {link}\nВы получаете это письмо как владелец или администратор. Отключить можно в настройках.",
    },
}


HTML_TEXT = {
    "en": {
        "heading": "{workspace}: the week",
        "done": "Done in 7 days",
        "overdue": "Past due date",
        "project": "Project",
        "health": "Health",
        "open": "Open",
        "done_share": "Done",
        "late": "Late issues",
        "due": "due {due}",
        "button": "Open DevTrack",
        "footer": "You get this as a workspace owner or admin. Turn it off in Settings.",
    },
    "uz": {
        "heading": "{workspace}: hafta yakuni",
        "done": "7 kunda bajarildi",
        "overdue": "Muddati o'tgan",
        "project": "Loyiha",
        "health": "Salomatlik",
        "open": "Ochiq",
        "done_share": "Bajarilgan",
        "late": "Kechikkan vazifalar",
        "due": "muddat {due}",
        "button": "DevTrack'ni ochish",
        "footer": "Bu xat sizga ish maydoni egasi yoki administratori sifatida keladi. Sozlamalarda o'chirsa bo'ladi.",
    },
    "ru": {
        "heading": "{workspace}: итоги недели",
        "done": "Готово за 7 дней",
        "overdue": "Просрочено",
        "project": "Проект",
        "health": "Здоровье",
        "open": "Открыто",
        "done_share": "Готово",
        "late": "Просроченные задачи",
        "due": "срок {due}",
        "button": "Открыть DevTrack",
        "footer": "Вы получаете это письмо как владелец или администратор. Отключить можно в настройках.",
    },
}


def digest_data(workspace, now=None):
    """The week's numbers for one workspace, shared by the text and the HTML parts."""
    now = now or timezone.now()
    today = timezone.localdate(now)
    issues = Issue.objects.filter(project__workspace=workspace)
    open_issues = issues.exclude(status=Issue.Status.DONE)
    projects = []
    for project in workspace.projects.exclude(status__in=["completed", "archived"]).order_by("name"):
        total = project.issues.count()
        done = project.issues.filter(status=Issue.Status.DONE).count()
        projects.append(
            {
                "name": project.name,
                "score": compute_project_health(project, now=now)["score"],
                "open": total - done,
                "done": round(100 * done / total) if total else 0,
            }
        )
    return {
        "workspace": workspace.name,
        "done_week": issues.filter(status=Issue.Status.DONE, completed_at__gte=now - dt.timedelta(days=7)).count(),
        "overdue": open_issues.filter(due_date__lt=today).count(),
        "projects": projects,
        "late": [
            {"number": i.number, "title": i.title, "project": i.project.name, "due": i.due_date.isoformat()}
            for i in open_issues.filter(due_date__lt=today).select_related("project").order_by("due_date")[:10]
        ],
    }


def digest_text(data, lang="en"):
    text = TEXT.get(lang) or TEXT["en"]
    lines = [text["intro"].format(workspace=data["workspace"]), "", text["done"].format(count=data["done_week"])]
    lines.append(text["overdue"].format(count=data["overdue"]))
    if data["projects"]:
        lines += ["", text["projects"]]
        lines += [text["project"].format(**project) for project in data["projects"]]
    if data["late"]:
        lines += ["", text["late"]]
        lines += [text["late_item"].format(**item) for item in data["late"]]
    lines += ["", text["footer"].format(link=settings.FRONTEND_URL)]
    return text["subject"].format(workspace=data["workspace"]), "\n".join(lines)


MONTHS = {
    "uz": ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr"],
    "ru": ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"],
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
}


def _day(iso, lang):
    """"16-noyabr" / "16 ноября" / "November 16" for an ISO date."""
    day = dt.date.fromisoformat(iso)
    months = MONTHS.get(lang) or MONTHS["en"]
    if lang == "uz":
        return f"{day.day}-{months[day.month - 1]}"
    if lang == "ru":
        return f"{day.day} {months[day.month - 1]}"
    return f"{months[day.month - 1]} {day.day}"


def _score_colour(score):
    # The same thresholds and hues as the app's health ring.
    return "#1d7a45" if score >= 80 else "#c25a0e" if score >= 50 else "#b42318"


def digest_html(data, lang="en"):
    text = TEXT.get(lang) or TEXT["en"]
    words = HTML_TEXT.get(lang) or HTML_TEXT["en"]
    cell = f"padding:10px 8px;border-top:1px solid {LINE};font:14px/1.4 {FONT};color:{BODY}"
    head = f"padding:0 8px 8px;font:600 12px/1.2 {FONT};color:{MUTED};text-align:left"
    overdue_colour = "#b42318" if data["overdue"] else INK
    tiles = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:6px 0 22px"><tr>'
        + "".join(
            f'<td width="48%" style="padding:14px 16px;border:1px solid {LINE};border-radius:12px">'
            f'<div style="font:12px/1.3 {FONT};color:{MUTED}">{escape(label)}</div>'
            f'<div style="font:600 28px/1.2 {FONT};color:{colour};padding-top:4px">{value}</div></td>'
            + ('<td width="4%" style="font-size:0">&nbsp;</td>' if index == 0 else "")
            for index, (label, value, colour) in enumerate(
                [(words["done"], data["done_week"], INK), (words["overdue"], data["overdue"], overdue_colour)]
            )
        )
        + "</tr></table>"
    )
    body = paragraph(escape(text["intro"].format(workspace=data["workspace"]))) + tiles
    if data["projects"]:
        rows = "".join(
            f"<tr><td style=\"{cell};color:{INK};font-weight:600\">{escape(p['name'])}</td>"
            f"<td style=\"{cell}\"><span style=\"color:{_score_colour(p['score'])}\">&#9679;</span> {p['score']}</td>"
            f"<td style=\"{cell}\">{p['open']}</td><td style=\"{cell}\">{p['done']}%</td></tr>"
            for p in data["projects"]
        )
        body += (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 20px">'
            f'<tr><th style="{head}">{escape(words["project"])}</th><th style="{head}">{escape(words["health"])}</th>'
            f'<th style="{head}">{escape(words["open"])}</th><th style="{head}">{escape(words["done_share"])}</th></tr>'
            f"{rows}</table>"
        )
    if data["late"]:
        items = "".join(
            f'<li style="margin:0 0 6px;font:14px/1.5 {FONT};color:{BODY}">'
            f'<span style="color:{MUTED}">#{item["number"]}</span> <strong style="color:{INK}">{escape(item["title"])}</strong>'
            f' <span style="color:{MUTED}">· {escape(item["project"])} · {escape(words["due"].format(due=_day(item["due"], lang)))}</span></li>'
            for item in data["late"]
        )
        body += f'<h2 style="margin:0 0 10px;font:600 15px/1.3 {FONT};color:{INK}">{escape(words["late"])}</h2><ul style="margin:0 0 8px;padding-left:18px">{items}</ul>'
    body += button(words["button"], settings.FRONTEND_URL)
    subject = text["subject"].format(workspace=data["workspace"])
    heading = words["heading"].format(workspace=data["workspace"])
    return layout(lang=lang, preheader=text["intro"].format(workspace=data["workspace"]), heading=heading, body_html=body, footer_html=escape(words["footer"])), subject


def build_digest(workspace, lang="en", now=None):
    """(subject, plain text) for one workspace."""
    return digest_text(digest_data(workspace, now), lang)


def send_weekly_digests(lang=None, now=None):
    """One email per (workspace, owner/admin who wants it). Returns how many were sent."""
    lang = lang or settings.DIGEST_LANGUAGE
    sent = 0
    for workspace in Workspace.objects.filter(projects__isnull=False).distinct():
        recipients = (
            Membership.objects.filter(workspace=workspace, role__in=[Membership.Role.OWNER, Membership.Role.ADMIN])
            .filter(user__is_active=True, user__weekly_digest=True)
            .exclude(user__email="")
            .exclude(user__email__endswith=".invalid")
            .values_list("user__email", flat=True)
        )
        recipients = list(recipients)
        if not recipients:
            continue
        data = digest_data(workspace, now)
        subject, body = digest_text(data, lang)
        html, _ = digest_html(data, lang)
        for address in recipients:
            send_email(subject, body, address, html=html, fail_silently=True)
            sent += 1
    return sent

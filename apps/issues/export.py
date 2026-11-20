"""Issues as CSV, for spreadsheets.

Cells that a spreadsheet would read as a formula (=, +, -, @ at the start, or a leading tab or carriage
return) are prefixed with an apostrophe, so an issue titled "=HYPERLINK(...)" cannot run anything when
the file is opened. The file starts with a byte-order mark so Excel reads Uzbek and Russian text as UTF-8.
"""

import csv

from django.http import StreamingHttpResponse
from django.utils import timezone

MAX_ROWS = 10_000
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

HEADERS = {
    "en": ["Number", "Title", "Project", "Status", "Priority", "Type", "Assignee", "Reporter", "Labels", "Due date", "Created", "Updated", "Completed"],
    "uz": ["Raqam", "Sarlavha", "Loyiha", "Holat", "Ustuvorlik", "Turi", "Ijrochi", "Muallif", "Yorliqlar", "Muddat", "Yaratilgan", "Yangilangan", "Bajarilgan"],
    "ru": ["Номер", "Название", "Проект", "Статус", "Приоритет", "Тип", "Исполнитель", "Автор", "Метки", "Срок", "Создана", "Обновлена", "Завершена"],
}
LABELS = {
    "uz": {
        "backlog": "Zaxira", "todo": "Qilinadigan", "in_progress": "Jarayonda", "in_review": "Ko'rib chiqilmoqda", "done": "Bajarildi",
        "none": "Belgilanmagan", "low": "Past", "medium": "O'rta", "high": "Yuqori", "urgent": "Shoshilinch",
        "task": "Topshiriq", "bug": "Xato", "feature": "Yangi imkoniyat", "improvement": "Yaxshilash", "chore": "Texnik ish",
    },
    "ru": {
        "backlog": "Бэклог", "todo": "К выполнению", "in_progress": "В работе", "in_review": "На проверке", "done": "Готово",
        "none": "Без приоритета", "low": "Низкий", "medium": "Средний", "high": "Высокий", "urgent": "Срочный",
        "task": "Задача", "bug": "Ошибка", "feature": "Новая функция", "improvement": "Улучшение", "chore": "Техническая работа",
    },
}


def safe_cell(value):
    text = "" if value is None else str(value)
    return "\u0027" + text if text.startswith(FORMULA_PREFIXES) else text


class _Echo:
    def write(self, value):
        return value


def _label(lang, code, display):
    return LABELS.get(lang, {}).get(code, display)


def _when(value):
    return timezone.localtime(value).strftime("%Y-%m-%d %H:%M") if value else ""


def issues_csv_response(queryset, lang, filename):
    lang = lang if lang in HEADERS else "en"
    writer = csv.writer(_Echo())

    def rows():
        yield "\ufeff" + writer.writerow(HEADERS[lang])
        for issue in queryset.select_related("project", "assignee", "reporter").prefetch_related("labels")[:MAX_ROWS]:
            yield writer.writerow(
                [
                    safe_cell(f"#{issue.number}"),
                    safe_cell(issue.title),
                    safe_cell(issue.project.name),
                    _label(lang, issue.status, issue.get_status_display()),
                    _label(lang, issue.priority, issue.get_priority_display()),
                    _label(lang, issue.type, issue.get_type_display()),
                    safe_cell(issue.assignee.username if issue.assignee else ""),
                    safe_cell(issue.reporter.username),
                    safe_cell(", ".join(label.name for label in issue.labels.all())),
                    issue.due_date.isoformat() if issue.due_date else "",
                    _when(issue.created_at),
                    _when(issue.updated_at),
                    _when(issue.completed_at),
                ]
            )

    response = StreamingHttpResponse(rows(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response

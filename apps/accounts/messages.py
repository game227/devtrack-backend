"""Outgoing account messages, in the languages the UI supports: a plain-text and a branded HTML part."""

from django.utils.html import escape

from apps.common.mail import button, layout, link_fallback, paragraph

DEFAULT_LANGUAGE = "en"

# The HTML part's words (the plain text keeps its one sentence).
HTML_TEXT = {
    "en": {
        "reset_heading": "Reset your password",
        "reset_intro": "Someone asked to reset the password of your DevTrack account. Press the button to choose a new one.",
        "reset_button": "Choose a new password",
        "reset_ignore": "If this wasn't you, ignore this email: your password stays as it is.",
        "verify_heading": "Confirm your email",
        "verify_intro": "Confirm that this address belongs to your DevTrack account, so password resets and the weekly summary can reach you here.",
        "verify_button": "Confirm email",
        "fallback": "If the button does not work, copy this address into your browser:",
        "footer": "You get this email because of your DevTrack account.",
    },
    "uz": {
        "reset_heading": "Parolni tiklash",
        "reset_intro": "DevTrack akkauntingiz parolini tiklash so'raldi. Yangi parol o'rnatish uchun tugmani bosing.",
        "reset_button": "Yangi parol o'rnatish",
        "reset_ignore": "Agar buni siz so'ramagan bo'lsangiz, xatni e'tiborsiz qoldiring: parolingiz o'zgarmaydi.",
        "verify_heading": "Email manzilingizni tasdiqlang",
        "verify_intro": "Bu manzil DevTrack akkauntingizga tegishli ekanini tasdiqlang: parolni tiklash havolalari va haftalik xulosa shu yerga keladi.",
        "verify_button": "Tasdiqlash",
        "fallback": "Tugma ishlamasa, bu manzilni brauzerga nusxalang:",
        "footer": "Bu xat DevTrack akkauntingiz sababli yuborildi.",
    },
    "ru": {
        "reset_heading": "Сброс пароля",
        "reset_intro": "Для вашего аккаунта DevTrack запрошен сброс пароля. Нажмите кнопку, чтобы задать новый.",
        "reset_button": "Задать новый пароль",
        "reset_ignore": "Если это были не вы, просто проигнорируйте письмо: пароль не изменится.",
        "verify_heading": "Подтвердите адрес почты",
        "verify_intro": "Подтвердите, что этот адрес принадлежит вашему аккаунту DevTrack: сюда будут приходить ссылки для сброса пароля и еженедельная сводка.",
        "verify_button": "Подтвердить",
        "fallback": "Если кнопка не работает, скопируйте этот адрес в браузер:",
        "footer": "Вы получили это письмо из-за аккаунта DevTrack.",
    },
}


def _html(language, heading, intro, button_label, link, after=""):
    words = HTML_TEXT.get(language) or HTML_TEXT[DEFAULT_LANGUAGE]
    body = paragraph(escape(intro)) + button(button_label, link) + (paragraph(escape(after)) if after else "")
    body += link_fallback(words["fallback"], link)
    return layout(lang=language, preheader=intro, heading=heading, body_html=body, footer_html=escape(words["footer"]))

PASSWORD_RESET = {
    "en": {
        "subject": "Reset your DevTrack password",
        "email": "Use this link to reset your password: {link}",
        "telegram": "Reset your DevTrack password: {link}",
    },
    "uz": {
        "subject": "DevTrack parolini tiklash",
        "email": "Parolni tiklash uchun ushbu havoladan foydalaning: {link}",
        "telegram": "DevTrack parolini tiklash: {link}",
    },
    "ru": {
        "subject": "Сброс пароля DevTrack",
        "email": "Чтобы сбросить пароль, перейдите по ссылке: {link}",
        "telegram": "Сброс пароля DevTrack: {link}",
    },
}


def password_reset_message(language, link):
    language = language if language in PASSWORD_RESET else DEFAULT_LANGUAGE
    texts = PASSWORD_RESET[language]
    words = HTML_TEXT[language]
    return {
        "subject": texts["subject"],
        "email": f"{texts['email'].format(link=link)}\n\n{words['reset_ignore']}",
        "html": _html(language, words["reset_heading"], words["reset_intro"], words["reset_button"], link, words["reset_ignore"]),
        "telegram": texts["telegram"].format(link=link),
    }


EMAIL_VERIFICATION = {
    "en": {
        "subject": "Verify your DevTrack email",
        "email": "Confirm this is your email address: {link}",
    },
    "uz": {
        "subject": "DevTrack email manzilini tasdiqlang",
        "email": "Bu email manzilingiz ekanligini tasdiqlang: {link}",
    },
    "ru": {
        "subject": "Подтвердите адрес эл. почты в DevTrack",
        "email": "Подтвердите, что это ваш адрес эл. почты: {link}",
    },
}


def email_verification_message(language, link):
    language = language if language in EMAIL_VERIFICATION else DEFAULT_LANGUAGE
    texts = EMAIL_VERIFICATION[language]
    words = HTML_TEXT[language]
    return {
        "subject": texts["subject"],
        "email": texts["email"].format(link=link),
        "html": _html(language, words["verify_heading"], words["verify_intro"], words["verify_button"], link),
    }

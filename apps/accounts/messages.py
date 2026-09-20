"""Outgoing account messages, in the languages the UI supports."""

DEFAULT_LANGUAGE = "en"

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
}


def password_reset_message(language, link):
    texts = PASSWORD_RESET.get(language) or PASSWORD_RESET[DEFAULT_LANGUAGE]
    return {
        "subject": texts["subject"],
        "email": texts["email"].format(link=link),
        "telegram": texts["telegram"].format(link=link),
    }

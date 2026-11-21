"""Application-level Google sign-in allow-list (private single-Owner beta)."""

from app.core.config import Settings


def allowed_sign_in_emails(settings: Settings) -> frozenset[str]:
    entries = (item.strip().lower() for item in settings.google_sign_in_allowed_emails.split(","))
    return frozenset(entry for entry in entries if entry)


def is_sign_in_allowed(settings: Settings, email: object) -> bool:
    """Fail closed: an unset or empty list, or a non-string address, allows nobody."""
    if not isinstance(email, str):
        return False
    return email.strip().lower() in allowed_sign_in_emails(settings)

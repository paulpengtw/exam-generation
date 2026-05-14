"""Email whitelist helpers for magic-link auth."""

from __future__ import annotations


def is_email_allowed(email: str, whitelist: tuple[str, ...]) -> bool:
    """Return True if email is allowed to receive a magic link.

    Empty whitelist permits all emails (dev default).
    Entries starting with '*@' match the entire domain.
    """
    if not whitelist:
        return True
    email = email.lower()
    for entry in whitelist:
        if entry.startswith("*@"):
            if email.endswith("@" + entry[2:]):
                return True
        elif email == entry:
            return True
    return False

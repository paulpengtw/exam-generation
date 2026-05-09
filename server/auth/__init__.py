"""Auth: magic-link tokens, JWT, and email senders."""

from server.auth.dependencies import get_config, get_current_user
from server.auth.email import (
    ConsoleEmailSender,
    EmailSender,
    SESEmailSender,
    get_email_sender,
)
from server.auth.tokens import create_jwt, decode_jwt, generate_magic_token

__all__ = [
    "ConsoleEmailSender",
    "EmailSender",
    "SESEmailSender",
    "create_jwt",
    "decode_jwt",
    "generate_magic_token",
    "get_config",
    "get_current_user",
    "get_email_sender",
]

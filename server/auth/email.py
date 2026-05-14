"""Email senders for magic-link delivery."""

from __future__ import annotations

from typing import Protocol
from urllib.parse import urlencode

from server.config import ServerConfig

_TEMPLATES: dict[str, dict[str, str]] = {
    "zh-TW": {
        "subject": "您的登入連結",
        "intro": "點擊下方按鈕登入：",
        "button": "登入",
        "or": "或開啟此連結：",
        "text_prefix": "登入：",
    },
    "en-US": {
        "subject": "Your sign-in link",
        "intro": "Click the button below to sign in:",
        "button": "Sign in",
        "or": "Or open this link:",
        "text_prefix": "Sign in:",
    },
}
_DEFAULT_LANG = "en-US"


def _magic_link_url(frontend_url: str, raw_token: str, email: str) -> str:
    base = frontend_url.rstrip("/") if frontend_url else ""
    query = urlencode({"token": raw_token, "email": email})
    return f"{base}/verify?{query}"


def _html_body(link: str, lang: str = _DEFAULT_LANG) -> str:
    tpl = _TEMPLATES.get(lang, _TEMPLATES[_DEFAULT_LANG])
    return (
        "<html><body>"
        f"<p>{tpl['intro']}</p>"
        f'<p><a href="{link}" style="display:inline-block;padding:12px 24px;'
        'background:#2563eb;color:#fff;text-decoration:none;border-radius:6px;">'
        f"{tpl['button']}</a></p>"
        f"<p>{tpl['or']} <a href=\"{link}\">{link}</a></p>"
        "</body></html>"
    )


class EmailSender(Protocol):
    def send(self, to_email: str, raw_token: str, lang: str = _DEFAULT_LANG) -> None: ...


class ConsoleEmailSender:
    """Prints the magic link to stdout. Default for development."""

    def __init__(self, frontend_url: str = "") -> None:
        self.frontend_url = frontend_url

    def send(self, to_email: str, raw_token: str, lang: str = _DEFAULT_LANG) -> None:
        link = _magic_link_url(self.frontend_url, raw_token, to_email)
        print(f"[ConsoleEmailSender] Magic link for {to_email} (lang={lang}): {link}")


class SESEmailSender:
    """Sends magic links via AWS SES (boto3)."""

    def __init__(
        self,
        *,
        region: str,
        from_email: str,
        frontend_url: str,
        client: object | None = None,
    ) -> None:
        self.region = region
        self.from_email = from_email
        self.frontend_url = frontend_url
        if client is None:
            import boto3

            client = boto3.client("ses", region_name=region)
        self.client = client

    def send(self, to_email: str, raw_token: str, lang: str = _DEFAULT_LANG) -> None:
        tpl = _TEMPLATES.get(lang, _TEMPLATES[_DEFAULT_LANG])
        link = _magic_link_url(self.frontend_url, raw_token, to_email)
        self.client.send_email(
            Source=self.from_email,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": tpl["subject"], "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": _html_body(link, lang), "Charset": "UTF-8"},
                    "Text": {"Data": f"{tpl['text_prefix']} {link}", "Charset": "UTF-8"},
                },
            },
        )


def get_email_sender(config: ServerConfig) -> EmailSender:
    """Factory: returns SESEmailSender if configured, else ConsoleEmailSender."""
    if config.email_backend == "ses":
        return SESEmailSender(
            region=config.aws_region,
            from_email=config.ses_from_email,
            frontend_url=config.frontend_url,
        )
    return ConsoleEmailSender(frontend_url=config.frontend_url)

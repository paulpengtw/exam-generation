"""Email senders for magic-link delivery."""

from __future__ import annotations

from typing import Protocol

from server.config import ServerConfig


def _magic_link_url(frontend_url: str, raw_token: str) -> str:
    base = frontend_url.rstrip("/") if frontend_url else ""
    return f"{base}/auth/verify?token={raw_token}"


def _html_body(link: str) -> str:
    return (
        "<html><body>"
        "<p>Click the button below to sign in:</p>"
        f'<p><a href="{link}" style="display:inline-block;padding:12px 24px;'
        'background:#2563eb;color:#fff;text-decoration:none;border-radius:6px;">'
        "Sign in</a></p>"
        f'<p>Or open this link: <a href="{link}">{link}</a></p>'
        "</body></html>"
    )


class EmailSender(Protocol):
    def send(self, to_email: str, raw_token: str) -> None: ...


class ConsoleEmailSender:
    """Prints the magic link to stdout. Default for development."""

    def __init__(self, frontend_url: str = "") -> None:
        self.frontend_url = frontend_url

    def send(self, to_email: str, raw_token: str) -> None:
        link = _magic_link_url(self.frontend_url, raw_token)
        print(f"[ConsoleEmailSender] Magic link for {to_email}: {link}")


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

    def send(self, to_email: str, raw_token: str) -> None:
        link = _magic_link_url(self.frontend_url, raw_token)
        self.client.send_email(
            Source=self.from_email,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": "Your sign-in link", "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": _html_body(link), "Charset": "UTF-8"},
                    "Text": {"Data": f"Sign in: {link}", "Charset": "UTF-8"},
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

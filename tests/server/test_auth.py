from __future__ import annotations

import hashlib
import io
import uuid
from contextlib import redirect_stdout
from unittest.mock import MagicMock

import pytest
pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from fastapi import HTTPException

from server.auth import (
    ConsoleEmailSender,
    SESEmailSender,
    create_jwt,
    decode_jwt,
    generate_magic_token,
    get_email_sender,
)
from server.config import ServerConfig


def _config(**overrides) -> ServerConfig:
    base = dict(
        api_key="x",
        jwt_secret="test-secret",
        jwt_expire_days=7,
        frontend_url="https://example.com",
        email_backend="console",
        aws_region="us-east-1",
        ses_from_email="noreply@example.com",
    )
    base.update(overrides)
    return ServerConfig(**base)


def test_generate_magic_token_returns_tuple_with_matching_hash() -> None:
    raw, token_hash = generate_magic_token()
    assert isinstance(raw, str) and isinstance(token_hash, str)
    assert raw != token_hash
    assert token_hash == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    # token_urlsafe(32) yields ~43 chars
    assert len(raw) >= 32


def test_jwt_round_trip() -> None:
    config = _config()
    uid = uuid.uuid4()
    token = create_jwt(uid, "user@example.com", config=config)
    payload = decode_jwt(token, config=config)
    assert payload["sub"] == str(uid)
    assert payload["email"] == "user@example.com"
    assert "exp" in payload


def test_decode_jwt_invalid_raises_401() -> None:
    config = _config()
    with pytest.raises(HTTPException) as exc:
        decode_jwt("not-a-token", config=config)
    assert exc.value.status_code == 401


def test_decode_jwt_wrong_secret_raises_401() -> None:
    token = create_jwt(uuid.uuid4(), "u@example.com", config=_config())
    with pytest.raises(HTTPException) as exc:
        decode_jwt(token, config=_config(jwt_secret="other-secret"))
    assert exc.value.status_code == 401


def test_console_email_sender_prints_link() -> None:
    sender = ConsoleEmailSender(frontend_url="https://example.com")
    buf = io.StringIO()
    with redirect_stdout(buf):
        sender.send("user@example.com", "raw-token-abc")
    out = buf.getvalue()
    assert "user@example.com" in out
    assert "https://example.com/verify?token=raw-token-abc&email=user%40example.com" in out


def test_ses_email_sender_calls_boto3() -> None:
    mock_client = MagicMock()
    sender = SESEmailSender(
        region="us-east-1",
        from_email="noreply@example.com",
        frontend_url="https://example.com",
        client=mock_client,
    )
    sender.send("user@example.com", "raw-token-xyz")
    mock_client.send_email.assert_called_once()
    kwargs = mock_client.send_email.call_args.kwargs
    assert kwargs["Source"] == "noreply@example.com"
    assert kwargs["Destination"] == {"ToAddresses": ["user@example.com"]}
    html = kwargs["Message"]["Body"]["Html"]["Data"]
    assert "https://example.com/verify?token=raw-token-xyz&email=user%40example.com" in html


def test_ses_email_sender_zh_tw_subject() -> None:
    mock_client = MagicMock()
    sender = SESEmailSender(
        region="us-east-1",
        from_email="noreply@example.com",
        frontend_url="https://example.com",
        client=mock_client,
    )
    sender.send("user@example.com", "raw-token-zh", lang="zh-TW")
    kwargs = mock_client.send_email.call_args.kwargs
    assert kwargs["Message"]["Subject"]["Data"] == "您的登入連結"
    html = kwargs["Message"]["Body"]["Html"]["Data"]
    assert "登入" in html


def test_ses_email_sender_en_us_subject() -> None:
    mock_client = MagicMock()
    sender = SESEmailSender(
        region="us-east-1",
        from_email="noreply@example.com",
        frontend_url="https://example.com",
        client=mock_client,
    )
    sender.send("user@example.com", "raw-token-en", lang="en-US")
    kwargs = mock_client.send_email.call_args.kwargs
    assert kwargs["Message"]["Subject"]["Data"] == "Your sign-in link"
    html = kwargs["Message"]["Body"]["Html"]["Data"]
    assert "Sign in" in html


def test_ses_email_sender_unknown_lang_falls_back_to_en() -> None:
    mock_client = MagicMock()
    sender = SESEmailSender(
        region="us-east-1",
        from_email="noreply@example.com",
        frontend_url="https://example.com",
        client=mock_client,
    )
    sender.send("user@example.com", "raw-token-fr", lang="fr-FR")
    kwargs = mock_client.send_email.call_args.kwargs
    assert kwargs["Message"]["Subject"]["Data"] == "Your sign-in link"


def test_get_email_sender_factory() -> None:
    assert isinstance(get_email_sender(_config(email_backend="console")), ConsoleEmailSender)
    # SES path requires boto3; skip if unavailable
    pytest.importorskip("boto3")
    assert isinstance(get_email_sender(_config(email_backend="ses")), SESEmailSender)

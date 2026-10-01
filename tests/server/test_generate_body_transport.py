"""Complete 預抽 payloads cross the HTTP boundary without a long request URL."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from server.app import create_app
from server.auth.dependencies import get_config
from server.auth.tokens import create_jwt
from server.config import ServerConfig
from server.db import get_async_session
from server.models import Base, User
from server.rate_limit import limiter


@pytest.fixture
def transport_client(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'transport.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id = uuid.uuid4()

    async def setup():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as session:
            session.add(User(id=user_id, email="transport@example.com"))
            await session.commit()

    asyncio.run(setup())

    async def session_dependency():
        async with sessions() as session:
            yield session

    config = ServerConfig(
        api_key="test",
        openai_api_key="test",
        jwt_secret="transport-test",
        output_dir=tmp_path,
        model_plan="gpt-4.1",
        model_execute="gpt-4.1",
        creative_planning=False,
        llm_models_allowed=("gpt-4.1", "gemini-3.1-pro-preview"),
    )
    app = create_app()
    app.dependency_overrides[get_config] = lambda: config
    app.dependency_overrides[get_async_session] = session_dependency
    # Store the isolated session factory on app.state so _execute_run helpers in
    # this and dependent test files can retrieve it without a dead monkeypatch.
    app.state.test_async_session_local = sessions

    def deny_provider_call(*args, **kwargs):
        raise AssertionError("External LLM calls must be stubbed in transport tests")

    monkeypatch.setattr("openai.resources.chat.completions.Completions.create", deny_provider_call)
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer " + create_jwt(
        user_id, "transport@example.com", config=config
    )
    limiter.reset()
    try:
        yield client
    finally:
        client.close()
        limiter.reset()
        asyncio.run(engine.dispose())


def wire_payload(payload):
    """The existing public contract uses JSON strings for nested config arrays."""
    payload = json.loads(json.dumps(payload))
    for row in payload.get("per_question_params", []):
        if isinstance(row.get("subquestion_configs"), list):
            row["subquestion_configs"] = json.dumps(row["subquestion_configs"], ensure_ascii=False)
    for key in ("subquestion_configs", "per_question_params"):
        if isinstance(payload.get(key), list):
            payload[key] = json.dumps(payload[key], ensure_ascii=False)
    return payload


def semantic_params(value):
    """Decode wire arrays and omit null default additions; retain every supplied value."""
    if isinstance(value, dict):
        return {
            key: semantic_params(
                json.loads(item)
                if key in {"subquestion_configs", "per_question_params"} and isinstance(item, str)
                else item
            )
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, list):
        return [semantic_params(item) for item in value]
    return value


def test_large_resolved_batch_has_identical_post_and_get_prompt_previews(transport_client):
    instruction = "請根據地方自治的證據比較不同立場，保留完整的中文出題指示。" * 100
    resolved = transport_client.post(
        "/api/generate/resolve",
        json={
            "subject": "social_studies",
            "seed": 41,
            "count": 2,
            "sub_question_count": 3,
            "content_type": "純文字",
            "text_instruction": instruction,
        },
    )
    assert resolved.status_code == 200, resolved.text
    payload = wire_payload(resolved.json()["payload"])
    payload["drawn"] = resolved.json()["drawn"]
    assert len("/api/generate/preview?" + urlencode(payload, doseq=True)) > 9489

    posted = transport_client.post("/api/generate/preview", json=payload)
    assert posted.status_code == 200, posted.text
    legacy = transport_client.get("/api/generate/preview", params=payload)
    assert legacy.status_code == 200, legacy.text
    assert posted.json() == legacy.json()
    text_prompts = [p for p in posted.json()["prompts"] if "subquestion_index" not in p]
    assert len(text_prompts) == 2
    assert all(instruction in p["user_prompt"] for p in text_prompts)


def test_post_generation_rejects_an_unresolved_batch_before_saving_history(transport_client):
    response = transport_client.post(
        "/api/generate",
        json={
            "subject": "math",
            "seed": 41,
            "grade": 8,
            "context": ["個人"],
            "set_type": "單一題",
            "q_type": ["選擇題"],
            "style": ["text_only"],
            "math_thinking": ["形成"],
            "learning_content": ["A-7-7"],
            "learning_performance": ["s-IV-12"],
            "core_competency": ["數-J-A2"],
            "stream_version": 3,
        },
    )
    assert response.status_code == 422, response.text[:1000]
    assert response.json()["detail"] == [{"field": "題目內容類型", "code": "unresolved"}]
    history = transport_client.get("/api/history")
    assert history.status_code == 200
    assert history.json()["total"] == 0


def test_nested_body_validation_preserves_field_paths_without_stringifying_inputs(transport_client):
    response = transport_client.post(
        "/api/generate",
        json={
            "subject": "math",
            "count": 1,
            "per_question_params": json.dumps([{
                "math_thinking": [],
                "grade": "PRIVATE_INPUT_787",
            }]),
        },
    )
    assert response.status_code == 422
    errors = response.json()["detail"]
    assert {tuple(error["loc"]) for error in errors} == {
        ("body", "per_question_params", 0, "math_thinking"),
        ("body", "per_question_params", 0, "grade"),
    }
    assert any(
        error["msg"] == "Value error, math_thinking must contain 1 to 3 values"
        for error in errors
    )
    # These messages are displayed and reported by the frontend; input/ctx stay separate.
    assert all("PRIVATE_INPUT_787" not in error["msg"] for error in errors)
    assert all("input_value" not in error["msg"] for error in errors)
    assert "event: started" not in response.text
    assert transport_client.get("/api/history").json()["total"] == 0


@pytest.mark.parametrize(("endpoint", "limit"), [("generate", 10), ("generate/preview", 30)])
def test_switching_transport_cannot_double_the_request_allowance(transport_client, endpoint, limit):
    # stream_version=3 so the 426 gate passes; the check here is about rate-limiting
    _sv_params = {"stream_version": 3}
    for index in range(limit):
        if index % 2:
            response = transport_client.post(f"/api/{endpoint}", json=_sv_params)
        else:
            response = transport_client.get(f"/api/{endpoint}", params=_sv_params)
        assert response.status_code == 422
    response = transport_client.post(f"/api/{endpoint}", json=_sv_params)
    assert response.status_code == 429


@pytest.mark.parametrize("fixture_name", ["social", "natural"])
@pytest.mark.parametrize("method", ["get", "post"])
def test_complete_batch_survives_generation_history_and_unchanged_reload(
    transport_client,
    monkeypatch,
    fixture_name,
    method,
):
    from openai.resources.chat.completions import Completions

    def provider_response(_self, **kwargs):
        # Only the external provider SDK is stubbed; prompts, generation, streaming,
        # persistence, authentication and History all run through the real application.
        if "## 本小題規劃" in kwargs["messages"][-1]["content"]:
            answer = {
                "題目": "哪個選項有證據支持？ A.甲 B.乙",
                "答案": "A",
                "答案解析": "甲有證據支持。",
            }
        else:
            answer = {
                "核心問題": "如何比較證據？",
                "文本": "甲提出紀錄，乙提出假設。",
                "subquestions": [
                    {"序號": 1, "出題概念": "辨識證據"},
                    {"序號": 2, "出題概念": "比較證據"},
                    {"序號": 3, "出題概念": "整合證據"},
                ],
            }
        content = json.dumps(answer, ensure_ascii=False)
        return iter(
            [SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))])]
        )

    monkeypatch.setattr(Completions, "create", provider_response)
    payload = json.loads(
        (Path(__file__).parents[1] / f"fixtures/transport-{fixture_name}-batch.json").read_text()
    )
    payload.setdefault("stream_version", 3)  # #742: stream_version gate
    payload["text_instruction"] = "請保留完整批次和各小題的證據比較要求。" * 100
    assert len("/api/generate?" + urlencode(payload, doseq=True)) > 9489

    def send(path, body):
        if method == "post":
            return transport_client.post(path, json=body)
        return transport_client.get(path, params=body)

    preview = send("/api/generate/preview", payload)
    assert preview.status_code == 200, preview.text[:1000]
    response = send("/api/generate", payload)
    assert response.status_code == 202, response.text[:1000]
    run_id = response.json()["run_id"]
    assert run_id  # non-empty string

    # Execute the queued run in-process using the same isolated session factory.
    from unittest.mock import MagicMock as _MagicMock

    from server.generate.run import claim_next_run, execute_run

    _sessions = transport_client.app.state.test_async_session_local
    _config = transport_client.app.dependency_overrides[get_config]()
    _app_state = _MagicMock()
    _app_state.renderer_pool = None

    async def _do_execute() -> None:
        claimed = await claim_next_run(_sessions, host_id="test-host")
        assert claimed is not None, "run was not queued"
        await execute_run(
            claimed,
            app_state=_app_state,
            config=_config,
            session_factory=_sessions,
            host_id="test-host",
        )

    asyncio.run(_do_execute())

    history = transport_client.get("/api/history").json()
    assert history["total"] == 2
    for item in history["items"]:
        detail = transport_client.get(f"/api/history/{item['id']}").json()
        assert detail["status"] == "completed"
        assert len(detail["question_json"]["subquestions"]) == 3
        saved = detail["params_json"]
        for field, value in payload.items():
            if field == "stream_version":
                continue  # server-only transport field; not stored in params_json (#742)
            if field in {"per_question_params", "subquestion_configs"} and value is not None:
                expected_rows = json.loads(value)
                if field == "per_question_params":
                    # Existing request defaults are serialized into each batch row;
                    # these additions are not changes to submitted pins.
                    expected_rows = [
                        {"image_generation_mode": "html", "coverage_mode": "balanced", **row}
                        for row in expected_rows
                    ]
                assert json.loads(saved[field]) == expected_rows, field
            else:
                assert saved[field] == value, field

    reloaded = transport_client.post("/api/generate/resolve", json=saved)
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["drawn"] == []
    assert semantic_params(reloaded.json()["payload"]) == semantic_params(saved)
    gated_saved = {k: v for k, v in saved.items() if v is not None} | {"stream_version": 3}
    repeated = send("/api/generate", gated_saved)
    assert repeated.status_code == 202, repeated.text[:1000]
    asyncio.run(_do_execute())  # execute the second queued run
    assert transport_client.get("/api/history").json()["total"] == 4


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize("endpoint", ["generate", "generate/preview"])
@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"model_execute": "unapproved-model"}, "model_execute"),
        ({"model_execute": "gemini-3.1-pro-preview"}, "GEMINI_API_KEY"),
        ({"effort_execute": "xhigh"}, "effort_execute"),
        ({"per_question_params": "not-json"}, "per_question_params"),
        ({"count": 11}, "count"),
    ],
)
def test_body_and_legacy_requests_enforce_validation_before_generation(
    transport_client,
    method,
    endpoint,
    override,
    message,
):
    payload = json.loads(
        (Path(__file__).parents[1] / "fixtures/transport-social-batch.json").read_text()
    )
    payload.setdefault("stream_version", 3)  # #742: stream_version gate
    payload.update(override)
    response = (
        transport_client.post(f"/api/{endpoint}", json=payload)
        if method == "post"
        else transport_client.get(f"/api/{endpoint}", params=payload)
    )
    assert response.status_code == 422, response.text[:1000]
    assert message in response.text[:1000]
    assert transport_client.get("/api/history").json()["total"] == 0


@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize("endpoint", ["generate", "generate/preview"])
def test_both_transports_require_authentication(transport_client, method, endpoint):
    del transport_client.headers["Authorization"]
    response = (
        transport_client.post(f"/api/{endpoint}", json={})
        if method == "post"
        else transport_client.get(f"/api/{endpoint}")
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing Authorization header"


@pytest.mark.parametrize("endpoint", ["generate", "generate/preview"])
@pytest.mark.parametrize("problem", ["unresolved", "incompatible_parent"])
def test_post_reports_the_nested_field_that_prevents_generation(
    transport_client,
    endpoint,
    problem,
):
    payload = json.loads(
        (Path(__file__).parents[1] / "fixtures/transport-natural-batch.json").read_text()
    )
    payload.setdefault("stream_version", 3)  # #742: stream_version gate
    rows = json.loads(payload["per_question_params"])
    if problem == "unresolved":
        configs = json.loads(rows[0]["subquestion_configs"])
        configs[0].pop("question_type")
        rows[0]["subquestion_configs"] = json.dumps(configs, ensure_ascii=False)
        expected_field = "per_question_params[0].subquestion_configs[0].question_type"
    else:
        rows[0].update(context=["Global"], sub_context="Maintenance of health")
        expected_field = "per_question_params[0].sub_context"
    payload["per_question_params"] = json.dumps(rows, ensure_ascii=False)
    response = transport_client.post(f"/api/{endpoint}", json=payload)
    assert response.status_code == 422, response.text[:1000]
    assert [(error["field"], error["code"]) for error in response.json()["detail"]] == [
        (expected_field, problem)
    ]
    assert transport_client.get("/api/history").json()["total"] == 0


def test_post_preview_keeps_request_and_prompt_content_out_of_sentry(transport_client, monkeypatch):
    import sentry_sdk
    from sentry_sdk.transport import Transport

    from server import observability

    envelopes = []

    class CaptureTransport(Transport):
        def capture_envelope(self, envelope):
            envelopes.append(envelope)

    monkeypatch.setenv("SENTRY_DSN", "https://public@example.com/1")
    # Restore the initialization state after exercising the real production setup.
    monkeypatch.setattr(observability, "_initialized", observability._initialized)
    observability.init_sentry()
    sdk_client = sentry_sdk.get_client()
    original_transport = sdk_client.transport
    sdk_client.transport = CaptureTransport()
    try:
        payload = json.loads(
            (Path(__file__).parents[1] / "fixtures/transport-social-batch.json").read_text()
        )
        payload["text_instruction"] = "PRIVATE_BODY_762_請勿收集出題內容"
        response = transport_client.post("/api/generate/preview", json=payload)
        assert response.status_code == 200
        assert payload["text_instruction"] in response.text
        sentry_sdk.flush()
        transactions = [
            json.loads(item.get_bytes())
            for envelope in envelopes
            for item in envelope.items
            if item.type == "transaction"
        ]
        assert any(event.get("transaction") == "/api/generate/preview" for event in transactions)
        telemetry = b"".join(item.get_bytes() for envelope in envelopes for item in envelope.items)
        assert b"PRIVATE_BODY_762" not in telemetry
        assert all(not event.get("request", {}).get("data") for event in transactions)
    finally:
        sdk_client.transport = original_transport
        sdk_client.close()
        sentry_sdk.get_global_scope().set_client(None)


@pytest.mark.parametrize(
    ("admission", "message"),
    [
        (
            {"model_execute": "unapproved-model"},
            "model_execute: model 'unapproved-model' not in allowlist",
        ),
        ({"model_execute": "gemini-3.1-pro-preview"}, "GEMINI_API_KEY"),
        (
            {"effort_execute": "unknown-effort"},
            "effort_execute: effort 'unknown-effort' not supported",
        ),
    ],
)
def test_legacy_get_keeps_admission_errors_ahead_of_subject_validation(
    transport_client,
    admission,
    message,
):
    response = transport_client.get(
        "/api/generate",
        params={
            "subject": "math",
            "subquestion_configs": "[]",
            "stream_version": 3,  # #742: stream_version gate
            **admission,
        },
    )
    assert response.status_code == 422
    assert message in response.text

"""Pipeline-level tests for the live Agent 自主驗證修正歷程 verdict spine."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from src.common.generation_core import generate_with_corrections_core
from src.common.subject_spec import SubjectGenerationSpec
from src.config import Config
from src.schemas import ChartVerificationResult, VerificationResult


class _StubClient:
    def get_observer(self):
        return None

    def generate_json(self, *_args, **_kwargs):
        return {"subquestions": [{"序號": 1}]}


def _stub_spec(verification: VerificationResult) -> SubjectGenerationSpec:
    return SubjectGenerationSpec(
        few_shot_subdir="math",
        build_text_system_fn=lambda _params: ("system", {}),
        build_text_user_fn=lambda *_args: ("user", []),
        build_subquestion_system_fn=lambda _stage_ctx: "sub-system",
        build_subquestion_user_fn=lambda *_args: ("sub-user", []),
        parse_text_shell_fn=lambda _raw, question_id, _params, _model: SimpleNamespace(
            id=question_id,
            subquestions=[],
            chart_spec=None,
            圖片=None,
            verification=None,
        ),
        parse_subquestion_fn=lambda _raw, _question_id, _params, index: SimpleNamespace(
            序號=index,
        ),
        make_fallback_sq_plans_fn=lambda _params, _count: [],
        ensure_visual_spec_fn=None,
        render_subquestion_images_fn=None,
        image_question_text_fn=lambda _question: "",
        verify_fn=lambda *_args, **_kwargs: verification,
        correct_fn=lambda *_args, **_kwargs: _args[1],
    )


def test_verify_pass_captures_typed_verdict_entry_with_resolved_model_and_timestamp(
    tmp_path,
) -> None:
    verdict = VerificationResult(
        passed=True,
        details="答案與解析一致。",
        my_answer="A",
        provided_answer="A",
        answer_match=True,
        chart_verification=ChartVerificationResult(
            chart_data_match=True,
            chart_labels_correct=True,
            chart_details="圖表數據與標籤一致。",
        ),
    )
    trail = []

    generate_with_corrections_core(
        config=Config(
            output_dir=tmp_path,
            model_execute="execute-model",
            model_verify="verify-model",
        ),
        client=_StubClient(),
        params=SimpleNamespace(sub_question_count=1, subquestion_configs=[]),
        question_id="q-429",
        spec=_stub_spec(verdict),
        on_trail_entry=trail.append,
    )

    assert len(trail) == 1
    payload = trail[0].model_dump(mode="json")
    assert {key: value for key, value in payload.items() if key != "timestamp"} == {
        "code": "verification_trail",
        "kind": "verification",
        "question_id": "q-429",
        "passed": True,
        "details": "答案與解析一致。",
        "my_answer": "A",
        "provided_answer": "A",
        "answer_match": True,
        "chart_verification": {
            "chart_data_match": True,
            "chart_labels_correct": True,
            "chart_details": "圖表數據與標籤一致。",
        },
        "model": "verify-model",
    }
    datetime.fromisoformat(payload["timestamp"])


def test_all_subject_generation_wrappers_forward_the_trail_callback(monkeypatch) -> None:
    from src import cli as math_cli
    from src.natural_sciences import cli as ns_cli
    from src.social_studies import cli as ss_cli

    def callback(_entry) -> None:
        pass
    captured: list[object] = []

    def fake_core(**kwargs):
        captured.append(kwargs["on_trail_entry"])
        return "stubbed"

    params = SimpleNamespace(sub_question_count=3, subquestion_configs=[])
    monkeypatch.setattr(math_cli, "generate_with_corrections_core", fake_core)
    monkeypatch.setattr(ns_cli, "generate_with_corrections_core", fake_core)
    monkeypatch.setattr(ss_cli, "generate_with_corrections_core", fake_core)

    math_cli.generate_with_corrections(
        Config(),
        _StubClient(),
        [],
        {},
        "",
        {},
        params,
        "math-question",
        on_trail_entry=callback,
    )
    ns_cli.generate_with_corrections(
        Config(), _StubClient(), params, "ns-question", on_trail_entry=callback
    )
    ss_cli.generate_with_corrections(
        Config(), _StubClient(), params, "ss-question", on_trail_entry=callback
    )

    assert captured == [callback, callback, callback]

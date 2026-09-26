"""Pipeline-level tests for the live Agent 自主驗證修正歷程 verdict spine."""

from __future__ import annotations

import dataclasses
from datetime import datetime
from types import SimpleNamespace

from src.common.generation_core import generate_with_corrections_core
from src.common.subject_spec import SubjectGenerationSpec
from src.config import Config
from src.natural_sciences.schemas import VerificationResult as NaturalSciencesVerificationResult
from src.schemas import ChartVerificationResult, VerificationResult
from src.social_studies.schemas import VerificationResult as SocialStudiesVerificationResult


class _StubClient:
    def get_observer(self):
        return None

    def generate_json(self, *_args, **_kwargs):
        return {"subquestions": [{"序號": 1}]}


class _SnapshotQuestion(SimpleNamespace):
    """Small mutable question double with a JSON-like snapshot payload."""

    def __init__(self, question_id: str) -> None:
        super().__init__(
            id=question_id,
            answer="before",
            subquestions=[],
            chart_spec=None,
            圖片="question.png",
            verification=None,
        )

    def model_dump(self, *, mode: str = "python", exclude: set[str] | None = None):
        del mode
        payload = {
            "id": self.id,
            "題目": [self.answer],
            "圖片": self.圖片,
            "image_base64": "embedded-question-bytes",
            "subquestions": [
                {"圖片": "subquestion.png", "image_base64": "embedded-subquestion-bytes"}
            ],
            "verification": {"passed": False},
        }
        if exclude:
            for field in exclude:
                payload.pop(field, None)
        return payload


def test_verification_result_schemas_do_not_own_run_revision_bindings() -> None:
    payload = {
        "passed": True,
        "answer_match": True,
        "details": "同一版本。",
        "content_revision": 7,
    }

    for result_cls in (
        VerificationResult,
        SocialStudiesVerificationResult,
        NaturalSciencesVerificationResult,
    ):
        result = result_cls.model_validate(payload)
        assert "content_revision" not in result.model_dump()


def _stub_spec(verification: VerificationResult) -> SubjectGenerationSpec:
    return SubjectGenerationSpec(
        few_shot_subdir="math",
        build_text_system_fn=lambda _params: ("system", {}),
        build_text_user_fn=lambda *_args: ("user", [], []),
        build_subquestion_system_fn=lambda _stage_ctx: "sub-system",
        build_subquestion_user_fn=lambda *_args: ("sub-user", [], []),
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


def _snapshot_spec(verdicts: list[VerificationResult]) -> SubjectGenerationSpec:
    remaining_verdicts = iter(verdicts)

    def parse_text_shell(_raw, question_id, _params, _model):
        return _SnapshotQuestion(question_id)

    def correct(_client, question, _verification, **_kwargs):
        question.answer = "after"
        return question

    return SubjectGenerationSpec(
        few_shot_subdir="math",
        build_text_system_fn=lambda _params: ("system", {}),
        build_text_user_fn=lambda *_args: ("user", [], []),
        build_subquestion_system_fn=lambda _stage_ctx: "sub-system",
        build_subquestion_user_fn=lambda *_args: ("sub-user", [], []),
        parse_text_shell_fn=parse_text_shell,
        parse_subquestion_fn=lambda _raw, _question_id, _params, index: SimpleNamespace(
            序號=index,
        ),
        make_fallback_sq_plans_fn=lambda _params, _count: [],
        ensure_visual_spec_fn=None,
        render_subquestion_images_fn=None,
        image_question_text_fn=lambda _question: "",
        verify_fn=lambda *_args, **_kwargs: next(remaining_verdicts),
        correct_fn=correct,
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

    assert len(trail) == 2
    assert trail[0].kind == "initial"
    payload = trail[1].model_dump(mode="json")
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


def test_verification_trail_verdict_targets_the_content_revision(tmp_path) -> None:
    verdict = VerificationResult(
        passed=True,
        details="同一版本。",
        my_answer="A",
        provided_answer="A",
        answer_match=True,
    )
    seen_revisions: list[int | None] = []

    def verify(*_args, content_revision=None, **_kwargs):
        seen_revisions.append(content_revision)
        return verdict

    spec = dataclasses.replace(_stub_spec(verdict), verify_fn=verify)
    trail = []

    generate_with_corrections_core(
        config=Config(
            output_dir=tmp_path,
            model_execute="execute-model",
            model_verify="verify-model",
        ),
        client=_StubClient(),
        params=SimpleNamespace(sub_question_count=1, subquestion_configs=[]),
        question_id="q-revision-binding",
        spec=spec,
        on_question_update=lambda _question, _phase: 7,
        on_trail_entry=trail.append,
    )

    assert seen_revisions == [7]
    assert trail[0].content_revision == 7
    assert trail[1].content_revision == 7


def test_failed_verification_emits_initial_correction_and_reverification_in_order(
    tmp_path,
) -> None:
    failed = VerificationResult(
        passed=False,
        details="答案需要修正。",
        my_answer="B",
        provided_answer="A",
        answer_match=False,
    )
    passed = failed.model_copy(
        update={
            "passed": True,
            "details": "修正後一致。",
            "my_answer": "A",
            "answer_match": True,
        }
    )
    trail = []

    generate_with_corrections_core(
        config=Config(
            output_dir=tmp_path,
            model_execute="execute-model",
            model_verify="verify-model",
            model_correct="correct-model",
        ),
        client=_StubClient(),
        params=SimpleNamespace(sub_question_count=1, subquestion_configs=[]),
        question_id="q-431-order",
        spec=_snapshot_spec([failed, passed]),
        on_trail_entry=trail.append,
        max_retries=1,
    )

    assert [entry.kind for entry in trail] == [
        "initial",
        "verification",
        "correction",
        "verification",
    ]
    correction = trail[2]
    assert correction.retry_index == 1
    assert correction.model == "correct-model"
    datetime.fromisoformat(correction.model_dump(mode="json")["timestamp"])


def test_trail_snapshots_capture_each_question_state_without_embedded_payloads(tmp_path) -> None:
    failed = VerificationResult(
        passed=False,
        details="需要修正。",
        my_answer="B",
        provided_answer="A",
        answer_match=False,
    )
    passed = failed.model_copy(update={"passed": True, "answer_match": True})
    trail = []

    generate_with_corrections_core(
        config=Config(output_dir=tmp_path, model_execute="execute-model"),
        client=_StubClient(),
        params=SimpleNamespace(sub_question_count=1, subquestion_configs=[]),
        question_id="q-431-snapshot",
        spec=_snapshot_spec([failed, passed]),
        on_trail_entry=trail.append,
        max_retries=1,
    )

    initial_snapshot = trail[0].snapshot
    correction_snapshot = trail[2].snapshot
    assert initial_snapshot["題目"] == ["before"]
    assert correction_snapshot["題目"] == ["after"]
    assert initial_snapshot["圖片"] == "question.png"
    assert correction_snapshot["圖片"] == "question.png"
    for snapshot in (initial_snapshot, correction_snapshot):
        assert "verification" not in snapshot
        assert "image_base64" not in snapshot
        assert "image_base64" not in snapshot["subquestions"][0]


def test_exhausted_retries_end_with_the_failed_reverification_entry(tmp_path) -> None:
    failed = VerificationResult(
        passed=False,
        details="仍需修正。",
        my_answer="B",
        provided_answer="A",
        answer_match=False,
    )
    trail = []

    generate_with_corrections_core(
        config=Config(output_dir=tmp_path, model_execute="execute-model"),
        client=_StubClient(),
        params=SimpleNamespace(sub_question_count=1, subquestion_configs=[]),
        question_id="q-431-exhausted",
        spec=_snapshot_spec([failed, failed]),
        on_trail_entry=trail.append,
        max_retries=1,
    )

    assert [entry.kind for entry in trail] == [
        "initial",
        "verification",
        "correction",
        "verification",
    ]
    assert trail[-1].kind == "verification"
    assert trail[-1].passed is False


def test_legacy_math_generation_emits_the_same_snapshot_chain(monkeypatch, tmp_path) -> None:
    from src import cli as math_cli
    from src.sampler import sample_params
    from src.schemas import QuestionSetType

    failed = VerificationResult(
        passed=False,
        details="需要修正。",
        my_answer="B",
        provided_answer="A",
        answer_match=False,
    )
    passed = failed.model_copy(update={"passed": True, "answer_match": True})
    remaining_verdicts = iter([failed, passed])

    class _LegacyClient:
        def get_observer(self):
            return None

        def generate_json(self, *_args, **_kwargs):
            return {
                "情境": ["個人"],
                "題型種類": "單一題",
                "題型": "選擇題",
                "數學思考": ["運用"],
                "學習內容": [{"編碼": "N-7-1", "說明": "測試"}],
                "題目": ["題目前"],
                "正確解題分析": ["解析"],
                "出題概念": "概念",
            }

    def fake_verify(*_args, **_kwargs):
        return next(remaining_verdicts)

    def fake_correct(_client, question, _verification, **_kwargs):
        question.題目 = ["題目修正後"]
        return question

    monkeypatch.setattr(math_cli, "verify_question", fake_verify)
    monkeypatch.setattr(math_cli, "correct_question", fake_correct)

    trail = []
    math_cli.generate_with_corrections(
        config=Config(
            output_dir=tmp_path,
            model_execute="execute-model",
            model_verify="verify-model",
            model_correct="correct-model",
        ),
        client=_LegacyClient(),
        curriculum=[],
        performance={},
        intro_text="",
        grade_content={},
        params=sample_params(set_type=QuestionSetType("單一題"), seed=23),
        question_id="q-431-legacy",
        max_retries=1,
        on_trail_entry=trail.append,
    )

    assert [entry.kind for entry in trail] == [
        "initial",
        "verification",
        "correction",
        "verification",
    ]
    assert trail[0].snapshot["題目"] == ["題目前"]
    assert trail[2].retry_index == 1
    assert trail[2].model == "correct-model"
    assert trail[2].snapshot["題目"] == ["題目修正後"]


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


def test_reverification_entry_carries_post_correction_revision(tmp_path) -> None:
    """#746 core: the reverification trail entry must bind the post-correction revision.

    Uses ``_snapshot_spec`` (which mutates ``question.answer`` from ``'before'`` to
    ``'after'`` on correction) and a simple ``on_question_update`` that returns
    revision 1 for the initial content and revision 2 after correction.

    This is the non-parametrized core assertion that was previously spread across
    the vacuous parametrized ``test_746_reverify_revision_binding.py``.
    """
    failed = VerificationResult(
        passed=False,
        details="答案需要修正。",
        my_answer="B",
        provided_answer="A",
        answer_match=False,
    )
    passed = failed.model_copy(
        update={
            "passed": True,
            "details": "修正後正確。",
            "my_answer": "A",
            "answer_match": True,
        }
    )
    trail = []

    def on_question_update(question: object, _phase: str) -> int:
        return 1 if getattr(question, "answer", None) == "before" else 2

    generate_with_corrections_core(
        config=Config(
            output_dir=tmp_path,
            model_execute="execute-model",
            model_verify="verify-model",
            model_correct="correct-model",
        ),
        client=_StubClient(),
        params=SimpleNamespace(sub_question_count=1, subquestion_configs=[]),
        question_id="q-746-core",
        spec=_snapshot_spec([failed, passed]),
        on_question_update=on_question_update,
        on_trail_entry=trail.append,
        max_retries=1,
    )

    kinds = [e.kind for e in trail]
    assert kinds == ["initial", "verification", "correction", "verification"], kinds

    R1 = trail[0].content_revision
    assert isinstance(R1, int) and R1 >= 1, f"initial entry content_revision={R1!r}"

    # First verification (pre-correction) must be at R1
    assert trail[1].content_revision == R1, (
        f"first verification carries {trail[1].content_revision!r}, expected R1={R1}"
    )
    assert trail[1].passed is False

    # Correction entry must carry the post-correction revision R2 > R1
    R2 = trail[2].content_revision
    assert isinstance(R2, int) and R2 > R1, (
        f"correction entry content_revision={R2!r} should exceed R1={R1}"
    )

    # Reverification entry must carry R2, not the stale R1
    assert trail[3].content_revision == R2, (
        f"reverification entry carries {trail[3].content_revision!r}, expected R2={R2}"
    )
    assert trail[3].passed is True


def test_post_draft_non_visual_mutation_binds_revision_to_verifier(tmp_path) -> None:
    """#746 (core): ensure_visual_spec_fn stamping non-visual fields (SS ICCS axes pattern)
    must emit a draft commit so the verifier receives the post-hook content_revision."""
    verdict = VerificationResult(
        passed=True, details="ok", my_answer="A", provided_answer="A", answer_match=True,
    )
    seen_revisions: list[int | None] = []
    update_calls: list[tuple[str, int]] = []

    class _Q(SimpleNamespace):
        def model_dump(self, *, mode: str = "python", exclude_none: bool = False, **_kw):
            raw = {"id": self.id, "認知歷程": self.認知歷程, "subquestions": []}
            if exclude_none:
                return {k: v for k, v in raw.items() if v is not None}
            return raw

    def tracking_update(question, phase) -> int:
        rev = len(update_calls) + 1
        update_calls.append((phase, rev))
        return rev

    def hook_stamps_axes(question, _params, _client, **_kw) -> None:
        question.認知歷程 = ["知識"]  # non-visual field (mirrors SS _derive_iccs_axes)

    def verify_and_capture(*_a, content_revision=None, **_kw):
        seen_revisions.append(content_revision)
        return verdict

    spec = dataclasses.replace(
        _stub_spec(verdict),
        parse_text_shell_fn=lambda _raw, qid, _params, _model: _Q(
            id=qid, subquestions=[], chart_spec=None, 圖片=None, 認知歷程=None,
        ),
        ensure_visual_spec_fn=hook_stamps_axes,
        verify_fn=verify_and_capture,
    )
    trail: list = []

    generate_with_corrections_core(
        config=Config(output_dir=tmp_path, model_execute="x"),
        client=_StubClient(),
        params=SimpleNamespace(sub_question_count=1, subquestion_configs=[]),
        question_id="q-746-nv",
        spec=spec,
        on_question_update=tracking_update,
        on_trail_entry=trail.append,
    )

    assert len(seen_revisions) == 1
    revision_seen = seen_revisions[0]
    assert isinstance(revision_seen, int) and revision_seen >= 1

    # With fix: hook emits a "draft" update after non-visual mutation → 3 drafts total
    # (text shell + sub-1 assembly + ICCS axes); without fix: only 2 drafts.
    draft_updates = [(phase, rev) for phase, rev in update_calls if phase == "draft"]
    assert len(draft_updates) == 3, (
        f"expected 3 draft updates (text shell + sub-1 + non-visual hook), "
        f"got {len(draft_updates)}: {update_calls!r}"
    )
    # Verifier must see the last draft revision (post-hook)
    last_draft_rev = draft_updates[-1][1]
    assert revision_seen == last_draft_rev, (
        f"verifier saw revision {revision_seen!r} but "
        f"post-hook draft revision is {last_draft_rev!r}"
    )
    assert trail[0].content_revision == revision_seen  # initial trail entry
    assert trail[1].content_revision == revision_seen  # verification trail entry


def test_post_draft_only_excluded_key_mutation_emits_no_extra_update(tmp_path) -> None:
    """#746 regression: a hook that mutates ONLY ledger-excluded keys (review/progress)
    must NOT emit an extra question_update and must leave the verifier bound to
    the last draft revision from actual content changes.

    RED before the CONTENT_SIGNATURE_EXCLUDED_KEYS constant fix (the old set lacked
    review/progress so _full_content_marker saw the change and emitted a spurious
    draft commit); GREEN after.
    """
    verdict = VerificationResult(
        passed=True, details="ok", my_answer="A", provided_answer="A", answer_match=True,
    )
    seen_revisions: list[int | None] = []
    update_calls: list[tuple[str, int]] = []

    class _Q(SimpleNamespace):
        def model_dump(self, *, mode: str = "python", exclude_none: bool = False, **_kw):
            raw = {
                "id": self.id,
                "content": "question text",
                "review": getattr(self, "review", None),
                "progress": getattr(self, "progress", None),
                "subquestions": [],
            }
            if exclude_none:
                return {k: v for k, v in raw.items() if v is not None}
            return raw

    def tracking_update(question, phase) -> int:
        rev = len(update_calls) + 1
        update_calls.append((phase, rev))
        return rev

    def hook_stamps_excluded_keys_only(question, _params, _client, **_kw) -> None:
        # Mutates ONLY ledger-excluded keys — should NOT be visible to _full_content_marker
        question.review = {"status": "pending"}
        question.progress = {"step": "review"}

    def verify_and_capture(*_a, content_revision=None, **_kw):
        seen_revisions.append(content_revision)
        return verdict

    spec = dataclasses.replace(
        _stub_spec(verdict),
        parse_text_shell_fn=lambda _raw, qid, _params, _model: _Q(
            id=qid, subquestions=[], chart_spec=None, 圖片=None,
        ),
        ensure_visual_spec_fn=hook_stamps_excluded_keys_only,
        verify_fn=verify_and_capture,
    )
    trail: list = []

    generate_with_corrections_core(
        config=Config(output_dir=tmp_path, model_execute="x"),
        client=_StubClient(),
        params=SimpleNamespace(sub_question_count=1, subquestion_configs=[]),
        question_id="q-746-excluded",
        spec=spec,
        on_question_update=tracking_update,
        on_trail_entry=trail.append,
    )

    # text shell draft + sub-1 draft = 2 total; hook touches only excluded keys
    # so _full_content_marker must NOT change → no extra draft commit
    draft_updates = [(phase, rev) for phase, rev in update_calls if phase == "draft"]
    assert len(draft_updates) == 2, (
        f"expected 2 draft updates (text-shell + sub-1 assembly), "
        f"hook must not add more for excluded keys; "
        f"got {len(draft_updates)}: {update_calls!r}"
    )

    # Verifier must see the last draft revision — no phantom revision from the hook
    last_draft_rev = draft_updates[-1][1]
    assert seen_revisions == [last_draft_rev], (
        f"verifier saw revisions {seen_revisions!r} but "
        f"expected [{last_draft_rev!r}] (last draft)"
    )


def test_post_draft_sub_chart_spec_mutation_binds_revision_to_verifier(tmp_path) -> None:
    """#746 (core): ensure_visual_spec_fn repairing a sub-question's chart_spec (NS pattern)
    must emit a corrected commit so content_revision is bound to the visual repair."""
    verdict = VerificationResult(
        passed=True, details="ok", my_answer="A", provided_answer="A", answer_match=True,
    )
    seen_revisions: list[int | None] = []
    update_calls: list[tuple[str, int]] = []

    class _Sub(SimpleNamespace):
        pass

    class _Q(SimpleNamespace):
        pass  # No model_dump → _full_content_marker falls back to _visual_content_marker

    def tracking_update(question, phase) -> int:
        rev = len(update_calls) + 1
        update_calls.append((phase, rev))
        return rev

    def hook_repairs_sub_chart_spec(question, _params, _client, **_kw) -> None:
        # Mirrors NS _ns_ensure_visual_spec repairing a missing sub chart_spec
        for sub in question.subquestions:
            if getattr(sub, "chart_spec", None) is None:
                sub.chart_spec = {"render_mode": "html", "description": "repaired"}

    def verify_and_capture(*_a, content_revision=None, **_kw):
        seen_revisions.append(content_revision)
        return verdict

    def parse_shell(_raw, qid, _params, _model):
        q = _Q(id=qid, chart_spec=None, 圖片=None)
        q.subquestions = []
        return q

    def parse_sub(_raw, _qid, _params, index):
        return _Sub(序號=index, chart_spec=None, 圖片=None, image_generation_mode=None)

    spec = dataclasses.replace(
        _stub_spec(verdict),
        parse_text_shell_fn=parse_shell,
        parse_subquestion_fn=parse_sub,
        ensure_visual_spec_fn=hook_repairs_sub_chart_spec,
        verify_fn=verify_and_capture,
    )
    trail: list = []

    generate_with_corrections_core(
        config=Config(output_dir=tmp_path, model_execute="x"),
        client=_StubClient(),
        params=SimpleNamespace(sub_question_count=1, subquestion_configs=[]),
        question_id="q-746-sub",
        spec=spec,
        on_question_update=tracking_update,
        on_trail_entry=trail.append,
    )

    assert len(seen_revisions) == 1
    revision_seen = seen_revisions[0]
    assert isinstance(revision_seen, int) and revision_seen >= 1

    # With fix: sub.chart_spec change is a visual change → "corrected" update emitted;
    # without fix: top-level-only comparison misses sub-level visual changes → no corrected.
    phases = [phase for phase, _ in update_calls]
    assert "corrected" in phases, (
        f"ensure_visual_spec_fn repaired sub.chart_spec but no 'corrected' update was emitted "
        f"(phases={phases!r})"
    )
    # Verifier must see the revision from the corrected update (post-repair)
    corrected_index = phases.index("corrected")
    expected_revision = corrected_index + 1  # tracking_update returns len(update_calls)
    assert revision_seen == expected_revision, (
        f"verifier saw revision {revision_seen!r} but post-repair (corrected) revision is "
        f"{expected_revision!r}"
    )
    assert trail[0].content_revision == revision_seen  # initial trail entry
    assert trail[1].content_revision == revision_seen  # verification trail entry

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.common.generation_core import _scoped_callback
from src.common.generation_events import (
    QuestionContext,
    new_call_scope,
    new_operation_scope,
)


def test_operation_and_call_scopes_are_run_unique_and_immutable() -> None:
    question = QuestionContext(run_id="RUN", question_id="q-1", index=0)

    operation = new_operation_scope(
        question,
        kind="subquestion",
        subquestion_index=0,
    )
    retry_operation = new_operation_scope(
        question,
        kind="subquestion",
        subquestion_index=0,
        supersedes_operation_id=operation.operation_id,
    )
    first_call = new_call_scope(operation)
    retry_call = new_call_scope(retry_operation, retry_of_call_id=first_call.call_id)

    assert operation.run_id == retry_operation.run_id == first_call.run_id == "RUN"
    assert operation.operation_id != retry_operation.operation_id
    assert operation.operation_id.startswith("RUN:")
    assert first_call.call_id != retry_call.call_id
    assert first_call.call_id.startswith("RUN:")
    assert retry_call.retry_of_call_id == first_call.call_id
    assert operation.subquestion_index == retry_operation.subquestion_index == 0
    assert retry_operation.supersedes_operation_id == operation.operation_id
    with pytest.raises(dataclasses.FrozenInstanceError):
        operation.operation_id = "mutated"  # type: ignore[misc]


def test_nested_scoped_callback_forwards_one_scope() -> None:
    question = QuestionContext(run_id="RUN", question_id="q-1", index=0)
    scope = new_operation_scope(question, kind="image")
    received: list[object] = []

    def callback(_entry: object, *, scope=None) -> None:
        received.append(scope)

    wrapped = _scoped_callback(_scoped_callback(callback, scope), scope)

    wrapped("entry")

    assert received == [scope]


def test_operation_scope_coverage_table_all_subjects_and_visual_providers(
    tmp_path: Path,
) -> None:
    """Every subject verifier/corrector and image provider receives its owner."""
    from src.corrector import correct_question as correct_math
    from src.natural_sciences.corrector import correct_question as correct_ns
    from src.natural_sciences.schemas import ExamQuestion as NaturalQuestion
    from src.natural_sciences.verifier import verify_question as verify_ns
    from src.renderer import render_image
    from src.schemas import ExamQuestion as MathQuestion
    from src.social_studies.corrector import correct_question as correct_social
    from src.social_studies.schemas import ExamQuestion as SocialQuestion
    from src.social_studies.verifier import verify_question as verify_social
    from src.verifier import verify_question as verify_math

    class ScopedProvider:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []
            self.config = SimpleNamespace(
                web_search_provider="none",
                web_search_max_uses=1,
                model_verify="",
                model_execute="",
            )

        def get_observer(self):
            return None

        def generate_with_image(
            self, _system, _user, image_path=None, purpose="generate", *, scope=None
        ):
            del image_path
            self.calls.append((purpose, scope))
            return json.dumps({
                "my_answer": "A",
                "provided_answer": "A",
                "answer_match": True,
                "passed": True,
                "details": "ok",
            })

        def generate_json(self, _system, _user, purpose="generate", *, scope=None, **_kwargs):
            self.calls.append((purpose, scope))
            return {}

        def generate(self, _system, _user, purpose="generate", *, scope=None, **_kwargs):
            self.calls.append((purpose, scope))
            return "<!DOCTYPE html><html><body>image</body></html>"

        def generate_image(self, _prompt, output_path, *, scope=None):
            self.calls.append(("gpt_image", scope))
            Path(output_path).write_bytes(b"png")
            return str(output_path)

    provider = ScopedProvider()
    owner = QuestionContext(run_id="RUN", question_id="q-1", index=0)

    math_question = MathQuestion(
        id="math-scope",
        情境=["個人"],
        題型種類="單一題",
        題型="選擇題",
        數學思考=["形成"],
        學習內容=[],
        題目=["一加一等於多少？"],
        正確解題分析=["二。"],
    )
    social_question = SocialQuestion(
        id="social-scope",
        情境=["公共"],
        題型種類="題組題",
        題型="選擇題",
        題目=["文本"],
        正確解題分析=["A"],
    )
    natural_question = NaturalQuestion(
        id="natural-scope",
        情境=["Local and national"],
        情境子類別="Environmental impact",
        題型種類="題組題",
        題型="Simple multiple-choice",
        題目=["文本"],
        正確解題分析=["A"],
    )

    question_cases = [
        ("math", math_question, verify_math, correct_math),
        ("social_studies", social_question, verify_social, correct_social),
        ("natural_sciences", natural_question, verify_ns, correct_ns),
    ]
    coverage: dict[str, object] = {}
    for subject, question, verify, correct in question_cases:
        verify_scope = new_operation_scope(owner, kind=f"{subject}:verify")
        correct_scope = new_operation_scope(owner, kind=f"{subject}:correct")
        verification = verify(provider, question, scope=verify_scope, content_revision=7)
        coverage[f"{subject}:verify"] = verify_scope
        correct(provider, question, verification, scope=correct_scope)
        coverage[f"{subject}:correct"] = correct_scope

    renderer_scopes: list[object] = []

    class ScopedRenderer:
        def render(self, _html, output_path, width=800, *, scope=None):
            del width
            renderer_scopes.append(scope)
            Path(output_path).write_bytes(b"png")
            return str(output_path)

    renderer = ScopedRenderer()
    html_scope = new_operation_scope(owner, kind="image")
    render_image(
        {"render_mode": "html", "html": "<p>fixed</p>"},
        tmp_path / "fixed.png",
        html_renderer=renderer,
        scope=html_scope,
    )
    generated_html_scope = new_operation_scope(owner, kind="html_image")
    render_image(
        {"render_mode": "html", "description": "generated"},
        tmp_path / "generated.png",
        html_renderer=renderer,
        llm_client=provider,
        scope=generated_html_scope,
    )
    gpt_scope = new_operation_scope(owner, kind="image")
    render_image(
        {"render_mode": "gpt_image", "description": "generated"},
        tmp_path / "gpt.png",
        image_generation_mode="gpt_image",
        llm_client=provider,
        scope=gpt_scope,
    )

    assert set(coverage) == {
        "math:verify",
        "math:correct",
        "social_studies:verify",
        "social_studies:correct",
        "natural_sciences:verify",
        "natural_sciences:correct",
    }
    for purpose, scope in provider.calls:
        if purpose in {"verify", "correct", "html_image", "gpt_image"}:
            assert scope is not None
    assert renderer_scopes == [html_scope, generated_html_scope]
    assert (tmp_path / "fixed.png").exists()
    assert (tmp_path / "generated.png").exists()
    assert (tmp_path / "gpt.png").exists()

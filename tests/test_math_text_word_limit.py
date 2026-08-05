from __future__ import annotations

from pathlib import Path

from src.config import Config


def test_math_sampler_carries_text_word_limit_as_a_request_level_suggestion() -> None:
    """The value is a 建議值 for generator-authored 文本, not a truncation setting."""
    from src.sampler import sample_params

    params = sample_params(
        grade=8,
        seed=23,
        content_type="純文字",
        sub_question_count=3,
        text_word_limit=321,
    )

    assert params.text_word_limit == 321


def test_math_cli_threads_one_canonical_limit_without_per_subquestion_configs() -> None:
    """Math keeps one request-level 建議值; it must not materialise 各小題配置."""
    from src.cli import _with_text_word_limit
    from src.sampler import sample_params

    params = sample_params(grade=8, seed=23, content_type="純文字", sub_question_count=3)

    resolved = _with_text_word_limit(params, 321)

    assert resolved.text_word_limit == 321
    assert "subquestion_configs" not in type(resolved).model_fields


def test_math_prompt_builder_forwards_limit_on_the_canonical_params(tmp_path, monkeypatch) -> None:
    """Prompt plumbing carries the 建議值; it does not ask the 子題產生器 to repeat it."""
    import src.cli as math_cli
    from src.sampler import sample_params

    params = sample_params(grade=8, seed=23, content_type="純文字", sub_question_count=3)
    captured: dict[str, int | None] = {}

    def fake_text_prompt(*args, **kwargs):
        captured["limit"] = args[0].text_word_limit
        return "text prompt", []

    monkeypatch.setattr(math_cli, "build_text_user_prompt", fake_text_prompt)

    math_cli.build_generation_prompts(
        Config(data_dir=Path("data"), output_dir=tmp_path),
        params,
        text_word_limit=321,
    )

    assert captured == {"limit": 321}


def test_math_text_generator_prompt_carries_the_exact_word_limit() -> None:
    """The 文本生成器 receives a 建議值, not a mechanical truncation command."""
    import random

    from src.context_builder import build_text_user_prompt
    from src.sampler import sample_params

    params = sample_params(
        grade=8,
        seed=23,
        content_type="純文字",
        sub_question_count=3,
        text_word_limit=321,
    )

    prompt, _ = build_text_user_prompt(
        params,
        Path("data/few_shot"),
        rng=random.Random(19),
    )

    assert "- **文本字數上限**：321 字" in prompt


def test_math_text_generator_prompt_omits_word_limit_when_unset() -> None:
    """An omitted 建議值 must not add a 文本字數上限 instruction."""
    import random

    from src.context_builder import build_text_user_prompt
    from src.sampler import sample_params

    params = sample_params(grade=8, seed=23, content_type="純文字", sub_question_count=3)

    prompt, _ = build_text_user_prompt(
        params,
        Path("data/few_shot"),
        rng=random.Random(19),
    )

    assert "文本字數上限" not in prompt


def test_math_flat_prompt_is_byte_for_byte_unchanged_by_text_word_limit() -> None:
    """A 題組-only 建議值 must never reach the flat math prompt."""
    import hashlib
    import random

    from src.context_builder import build_user_prompt
    from src.sampler import sample_params

    baseline_params = sample_params(grade=8, seed=7, content_type="純文字")
    limited_params = baseline_params.model_copy(update={"text_word_limit": 321})

    baseline, baseline_images = build_user_prompt(
        baseline_params,
        Path("data/few_shot"),
        rng=random.Random(19),
    )
    limited, limited_images = build_user_prompt(
        limited_params,
        Path("data/few_shot"),
        rng=random.Random(19),
    )

    assert limited == baseline
    assert limited_images == baseline_images == []
    assert hashlib.sha256(limited.encode()).hexdigest() == (
        "850a195851abb329d71da5d96a34ebe1cb90f393857c44c4ed54e75f92e3b7fb"
    )

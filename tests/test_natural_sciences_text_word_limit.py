from __future__ import annotations


def test_natural_sciences_cli_keeps_text_word_limit_request_level_without_padding_configs() -> None:
    from src.natural_sciences.cli import _with_text_word_limit
    from src.natural_sciences.sampler import sample_params

    params = sample_params(seed=23, sub_question_count=3).model_copy(
        update={"subquestion_configs": []}
    )

    resolved = _with_text_word_limit(params, 321)

    assert resolved.text_word_limit == 321
    assert resolved.subquestion_configs == []
    assert all(cfg.text_word_limit is None for cfg in resolved.subquestion_configs)

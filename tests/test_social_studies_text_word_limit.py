from __future__ import annotations


def test_social_cli_keeps_text_word_limit_request_level_without_padding_configs() -> None:
    from src.social_studies.cli import _with_text_word_limit
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=23, sub_question_count=3).model_copy(
        update={"subquestion_configs": []}
    )

    resolved = _with_text_word_limit(params, 321)

    assert resolved.text_word_limit == 321
    assert resolved.subquestion_configs == []
    # text_word_limit is now a request-level-only field; SubQuestionConfig has no such attribute
    assert not any(hasattr(cfg, "text_word_limit") for cfg in resolved.subquestion_configs)

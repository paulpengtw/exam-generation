from __future__ import annotations

import random
import shutil
from collections import Counter
from pathlib import Path

import pytest


def test_domain_mapping_loads_codes_and_inverse_domain_index() -> None:
    from src.social_studies.domain_mapping import load_domain_mapping

    mapping = load_domain_mapping()

    assert len(mapping.code_to_domains) == 76
    assert mapping.code_to_domains["公Aa-Ⅳ-1"] == {"Civic Roles and Identities"}
    assert mapping.code_to_domains["公Ab-Ⅳ-1"] == {
        "Civic Institutions and Systems",
        "Civic Principles",
    }

    for code, domains in mapping.code_to_domains.items():
        for domain in domains:
            assert code in mapping.domain_to_codes[domain]
    for domain, codes in mapping.domain_to_codes.items():
        for code in codes:
            assert domain in mapping.code_to_domains[code]

    assert Counter({domain: len(codes) for domain, codes in mapping.domain_to_codes.items()}) == {
        "Civic Institutions and Systems": 51,
        "Civic Principles": 27,
        "Civic Participation": 12,
        "Civic Roles and Identities": 10,
    }


def test_domain_mapping_uses_social_studies_curriculum_dir_override(
    monkeypatch, tmp_path: Path
) -> None:
    source = Path("data/social_studies/curriculum/內容領域_mapping.csv")
    override_dir = tmp_path / "curriculum"
    override_dir.mkdir()
    shutil.copyfile(source, override_dir / source.name)
    monkeypatch.setenv("SOCIAL_STUDIES_CURRICULUM_DIR", str(override_dir))

    from src.social_studies.domain_mapping import load_domain_mapping

    mapping = load_domain_mapping()

    assert mapping.code_to_domains["公Aa-Ⅳ-1"] == {"Civic Roles and Identities"}


def test_civic_and_cross_subject_public_learning_content_uses_drawn_domain() -> None:
    from src.social_studies.domain_mapping import load_domain_mapping
    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import QuestionSubject

    mapping = load_domain_mapping()
    for subject_value in ("公民與社會", "跨科"):
        subject = QuestionSubject(subject_value)
        for seed in range(200):
            params = sample_params(seed=seed, subject=[subject])
            mapped_codes = mapping.domain_to_codes[params.內容領域.value]

            assert all(
                not code.startswith("公") or code in mapped_codes
                for code in params.學習內容_pool
            )


def test_civic_learning_performance_pool_is_drawable_under_every_content_domain() -> None:
    """公1c-Ⅳ-1 is the only stage-4 公 學習表現 code and maps to no ICCS domain

    (#833): under every 內容領域 it must still be drawable from the 公民與社會
    學習表現 pool since 學習表現 is never restricted by 內容領域.
    """
    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import ContentDomain, QuestionSubject

    target_code = "公1c-Ⅳ-1"
    subject = QuestionSubject("公民與社會")
    for domain in ContentDomain:
        observed = {
            code
            for seed in range(200)
            for code in sample_params(
                seed=seed,
                subject=[subject],
                content_domain=domain.value,
            ).學習表現_pool
        }

        assert target_code in observed


def test_domain_filter_applies_to_public_learning_content_but_not_performance(
    monkeypatch,
) -> None:
    from src.social_studies import sampler
    from src.social_studies.schemas import QuestionSubject

    domains = [domain.value for domain in sampler.ContentDomain]
    code_to_domains = {
        "公Aa-Ⅳ-1": {domains[0], domains[2]},
        "公Ab-Ⅳ-1": {domains[1], domains[3]},
    }
    monkeypatch.setattr(
        sampler,
        "_LC_DATA",
        {
            "學習內容": [
                {
                    "學習階段": "第四學習階段",
                    "科目": "公",
                    "value": code,
                    "admitted_by": {"內容領域": sorted(code_domains)},
                }
                for code, code_domains in code_to_domains.items()
            ]
        },
    )
    monkeypatch.setattr(
        sampler,
        "_LP_DATA",
        {
            "學習表現": [
                {"學習階段": "第四學習階段", "科目": "公", "value": code}
                for code in code_to_domains
            ]
        },
    )

    subject = QuestionSubject("公民與社會")
    observed_lp_codes: set[str] = set()
    for seed in range(80):
        params = sampler.sample_params(seed=seed, subject=[subject])
        mapped_codes = {
            code
            for code, code_domains in code_to_domains.items()
            if params.內容領域.value in code_domains
        }

        assert set(params.學習內容_pool) <= mapped_codes
        observed_lp_codes.update(params.學習表現_pool)

    # 學習表現 is never restricted by 內容領域 (#833): both fixture codes remain
    # drawable across the seed loop regardless of which domain a seed selected.
    assert observed_lp_codes == set(code_to_domains)


def test_domain_filter_resamples_when_initial_domain_has_no_public_pool(monkeypatch) -> None:
    from src.social_studies import sampler
    from src.social_studies.schemas import QuestionSubject

    domains = [domain.value for domain in sampler.ContentDomain]
    target_domain = domains[0]
    code = "公Aa-Ⅳ-1"
    monkeypatch.setattr(
        sampler,
        "_LP_DATA",
        {
            "學習表現": [
                {"學習階段": "第四學習階段", "科目": "社", "value": "社1a-Ⅳ-1"}
            ]
        },
    )

    unrestricted_lc = {
        "學習內容": [
            {
                "學習階段": "第四學習階段",
                "科目": "公",
                "value": code,
                "admitted_by": {"內容領域": list(domains)},
            }
        ]
    }
    restricted_lc = {
        "學習內容": [
            {
                "學習階段": "第四學習階段",
                "科目": "公",
                "value": code,
                "admitted_by": {"內容領域": [target_domain]},
            }
        ]
    }
    subject = QuestionSubject("公民與社會")

    for seed in range(100):
        monkeypatch.setattr(sampler, "_LC_DATA", unrestricted_lc)
        initial = sampler.sample_params(seed=seed, subject=[subject])
        if initial.內容領域.value == target_domain:
            continue

        monkeypatch.setattr(sampler, "_LC_DATA", restricted_lc)
        resampled = sampler.sample_params(seed=seed, subject=[subject])

        assert resampled.內容領域.value == target_domain
        assert resampled.學習內容_pool == [code]
        break
    else:
        raise AssertionError("the seeded batch did not draw a non-target initial domain")


def test_blank_domain_draws_once_from_domains_with_a_nonempty_civic_pool(monkeypatch) -> None:
    from src.social_studies import sampler
    from src.social_studies.schemas import QuestionSubject

    target_domain = "Civic Principles"
    code = "公Synthetic-Ⅳ-1"
    monkeypatch.setattr(
        sampler,
        "_LC_DATA",
        {
            "學習內容": [
                {
                    "學習階段": "第四學習階段",
                    "科目": "公",
                    "value": code,
                    "admitted_by": {
                        "科目": ["公民與社會", "跨科"],
                        "內容領域": [target_domain],
                    },
                }
            ]
        },
    )
    monkeypatch.setattr(
        sampler,
        "_LP_DATA",
        {"學習表現": [{"學習階段": "第四學習階段", "科目": "社", "value": "社1a-Ⅳ-1"}]},
    )

    class CountingRandom(random.Random):
        choice_calls = 0

        def choice(self, sequence):
            self.choice_calls += 1
            return super().choice(sequence)

    domain_rng = CountingRandom(7)
    original_draw_rng = sampler.draw_rng

    def tracked_draw_rng(seed, field_path, counter=0):
        if field_path == "內容領域":
            return domain_rng
        return original_draw_rng(seed, field_path, counter)

    monkeypatch.setattr(sampler, "draw_rng", tracked_draw_rng)

    params = sampler.sample_params(
        seed=7,
        subject=[QuestionSubject("公民與社會")],
    )

    assert params.內容領域.value == target_domain
    assert params.學習內容_pool == [code]
    assert domain_rng.choice_calls == 1


def test_pinned_domain_intersects_the_civic_learning_content_pool(monkeypatch) -> None:
    from src.social_studies import sampler
    from src.social_studies.schemas import QuestionSubject

    target_domain = "Civic Principles"
    other_domain = "Civic Participation"
    target_code = "公Synthetic-Ⅳ-1"
    other_code = "公Synthetic-Ⅳ-2"
    monkeypatch.setattr(
        sampler,
        "_LC_DATA",
        {
            "學習內容": [
                {
                    "學習階段": "第四學習階段",
                    "科目": "公",
                    "value": target_code,
                    "admitted_by": {
                        "科目": ["公民與社會", "跨科"],
                        "內容領域": [target_domain],
                    },
                },
                {
                    "學習階段": "第四學習階段",
                    "科目": "公",
                    "value": other_code,
                    "admitted_by": {
                        "科目": ["公民與社會", "跨科"],
                        "內容領域": [other_domain],
                    },
                },
            ]
        },
    )
    monkeypatch.setattr(
        sampler,
        "_LP_DATA",
        {"學習表現": [{"學習階段": "第四學習階段", "科目": "社", "value": "社1a-Ⅳ-1"}]},
    )

    params = sampler.sample_params(
        seed=11,
        subject=[QuestionSubject("公民與社會")],
        content_domain=target_domain,
    )

    assert params.內容領域.value == target_domain
    assert params.學習內容_pool == [target_code]


def test_cross_subject_domain_filter_keeps_unscoped_history_and_geography_codes(
    monkeypatch,
) -> None:
    from src.social_studies import sampler
    from src.social_studies.schemas import QuestionSubject

    target_domain = "Civic Principles"
    history_code = "歷Synthetic-Ⅳ-1"
    geography_code = "地Synthetic-Ⅳ-1"
    civic_code = "公Synthetic-Ⅳ-1"
    monkeypatch.setattr(
        sampler,
        "_LC_DATA",
        {
            "學習內容": [
                {
                    "學習階段": "第四學習階段",
                    "科目": "歷",
                    "value": history_code,
                    "admitted_by": {"科目": ["歷史", "跨科"]},
                },
                {
                    "學習階段": "第四學習階段",
                    "科目": "地",
                    "value": geography_code,
                    "admitted_by": {"科目": ["地理", "跨科"]},
                },
                {
                    "學習階段": "第四學習階段",
                    "科目": "公",
                    "value": civic_code,
                    "admitted_by": {
                        "科目": ["公民與社會", "跨科"],
                        "內容領域": [target_domain],
                    },
                },
            ]
        },
    )
    monkeypatch.setattr(
        sampler,
        "_LP_DATA",
        {
            "學習表現": [
                {
                    "學習階段": "第四學習階段",
                    "科目": "社",
                    "value": "社1a-Ⅳ-1",
                }
            ]
        },
    )

    params = sampler.sample_params(
        seed=13,
        subject=[QuestionSubject("跨科")],
        content_domain=target_domain,
        learning_content=[history_code, geography_code],
        learning_performance=["社1a-Ⅳ-1"],
    )

    assert params.學習內容_pool == [history_code, geography_code]


_KNOWING_DEFINING = "Knowing–Defining and Describing"
_KNOWING_ILLUSTRATING = "Knowing–Illustrating with examples"
_REASONING_INTERPRET = "Reasoning and Applying–Interpret information"
_REASONING_RELATE = "Reasoning and Applying–Relate or Integrate"
_KNOWING = {_KNOWING_DEFINING, _KNOWING_ILLUSTRATING}
_REASONING = {_REASONING_INTERPRET, _REASONING_RELATE}


def _cognitive_processes(params) -> list[str]:
    return [cfg.認知歷程 for cfg in params.subquestion_configs]


def test_cognitive_assignment_is_seeded_and_limits_knowing_defining_to_one() -> None:
    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import QuestionSubject

    subject = QuestionSubject("跨科")

    for seed in range(300):
        first = sample_params(
            seed=seed,
            subject=[subject],
            learning_content=["社1a-Ⅳ-1"],
            learning_performance=["社1a-Ⅳ-1"],
            sub_question_count=7,
        )
        second = sample_params(
            seed=seed,
            subject=[subject],
            learning_content=["社1a-Ⅳ-1"],
            learning_performance=["社1a-Ⅳ-1"],
            sub_question_count=7,
        )

        processes = _cognitive_processes(first)
        assert processes == _cognitive_processes(second)
        assert processes == first.認知歷程_pool
        assert processes.count(_KNOWING_DEFINING) <= 1


def test_every_cross_subject_group_contains_relate_or_integrate() -> None:
    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import QuestionSubject

    subject = QuestionSubject("跨科")

    for seed in range(300):
        params = sample_params(
            seed=seed,
            subject=[subject],
            learning_content=["社1a-Ⅳ-1"],
            learning_performance=["社1a-Ⅳ-1"],
            sub_question_count=3,
        )

        assert _REASONING_RELATE in _cognitive_processes(params)


def test_cognitive_assignment_weights_knowing_toward_one_third() -> None:
    from src.social_studies.sampler import sample_params

    processes = [
        process
        for seed in range(400)
        for process in _cognitive_processes(
            sample_params(
                seed=seed,
                learning_content=["社1a-Ⅳ-1"],
                learning_performance=["社1a-Ⅳ-1"],
                sub_question_count=3,
            )
        )
    ]
    knowing_share = sum(process in _KNOWING for process in processes) / len(processes)

    assert 0.20 <= knowing_share <= 0.47
    assert set(processes) == _KNOWING | _REASONING


def test_pinned_content_domain_restricts_public_draws_to_that_domain() -> None:
    from src.social_studies.domain_mapping import load_domain_mapping
    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import ContentDomain, QuestionSubject

    target = ContentDomain("Civic Principles")
    params = sample_params(
        seed=17,
        subject=[QuestionSubject("公民與社會")],
        content_domain=target.value,
    )
    allowed_codes = load_domain_mapping().domain_to_codes[target.value]

    assert params.內容領域 == target
    # 學習內容 remains restricted to the pinned domain's admitted codes; 學習表現
    # is never restricted by 內容領域 (#833), so it is intentionally excluded here.
    assert all(
        not code.startswith("公") or code in allowed_codes
        for code in params.學習內容_pool
    )


def test_pinned_content_domain_is_not_resampled_when_its_public_pool_is_empty(
    monkeypatch,
) -> None:
    from src.social_studies import sampler
    from src.social_studies.schemas import ContentDomain, QuestionSubject

    target = ContentDomain("Civic Principles")
    code = "公Aa-Ⅳ-1"
    monkeypatch.setattr(
        sampler,
        "_LC_DATA",
        {
            "學習內容": [
                {
                    "學習階段": "第四學習階段",
                    "科目": "公",
                    "value": code,
                    "admitted_by": {
                        "內容領域": [
                            ContentDomain("Civic Institutions and Systems").value
                        ]
                    },
                }
            ]
        },
    )
    monkeypatch.setattr(
        sampler,
        "_LP_DATA",
        {"學習表現": [{"學習階段": "第四學習階段", "科目": "公", "value": code}]},
    )

    with pytest.raises(sampler.IncompatibleContentDomainError):
        sampler.sample_params(
            seed=2,
            subject=[QuestionSubject("公民與社會")],
            content_domain=target.value,
        )


def test_blank_content_domain_preserves_seeded_random_domain_draw() -> None:
    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import QuestionSubject

    observed = {
        sample_params(
            seed=seed,
            subject=[QuestionSubject("公民與社會")],
        ).內容領域.value
        for seed in range(200)
    }

    assert observed == {
        "Civic Institutions and Systems",
        "Civic Principles",
        "Civic Participation",
        "Civic Roles and Identities",
    }


def test_pinned_cognitive_process_is_honored_per_slot() -> None:
    from src.social_studies.sampler import sample_params

    params = sample_params(
        seed=5,
        sub_question_count=4,
        subquestion_configs=[
            {"cognitive_process": _KNOWING_DEFINING},
            {},
            {"cognitive_process": _REASONING_RELATE},
            {},
        ],
    )

    assert [cfg.認知歷程 for cfg in params.subquestion_configs][0] == _KNOWING_DEFINING
    assert [cfg.認知歷程 for cfg in params.subquestion_configs][2] == _REASONING_RELATE
    assert all(process in _KNOWING | _REASONING for process in _cognitive_processes(params))


def test_invalid_cognitive_process_pin_is_treated_as_unpinned() -> None:
    from src.social_studies.sampler import sample_params

    params = sample_params(
        seed=5,
        sub_question_count=3,
        subquestion_configs=[{"cognitive_process": "not-an-iccs-process"}, {}, {}],
    )

    assert params.subquestion_configs[0].認知歷程 in _KNOWING | _REASONING
    assert params.subquestion_configs[0].認知歷程 != "not-an-iccs-process"


def test_non_string_cognitive_process_pin_is_treated_as_unpinned() -> None:
    from src.social_studies.sampler import sample_params

    params = sample_params(
        seed=5,
        sub_question_count=3,
        subquestion_configs=[{"cognitive_process": []}, {}, {}],
    )

    assert params.subquestion_configs[0].認知歷程 in _KNOWING | _REASONING


def test_pinned_knowing_defining_prevents_unpinned_duplicate() -> None:
    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import QuestionSubject

    params = sample_params(
        seed=23,
        subject=[QuestionSubject("歷史")],
        sub_question_count=7,
        subquestion_configs=[{"cognitive_process": _KNOWING_DEFINING}, {}, {}, {}, {}, {}, {}],
    )

    processes = _cognitive_processes(params)
    assert processes[0] == _KNOWING_DEFINING
    assert processes.count(_KNOWING_DEFINING) == 1


def test_violating_cognitive_pins_still_sample_successfully() -> None:
    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import QuestionSubject

    params = sample_params(
        seed=23,
        subject=[QuestionSubject("跨科")],
        sub_question_count=3,
        subquestion_configs=[
            {"cognitive_process": _KNOWING_DEFINING},
            {"cognitive_process": _KNOWING_DEFINING},
            {"cognitive_process": _KNOWING_ILLUSTRATING},
        ],
    )

    assert _cognitive_processes(params) == [
        _KNOWING_DEFINING,
        _KNOWING_DEFINING,
        _KNOWING_ILLUSTRATING,
    ]


def test_pin_rule_violation_helper_names_violated_rules() -> None:
    from src.social_studies.pin_rules import (
        CROSS_SUBJECT_RELATE_RULE,
        KNOWING_DEFINING_LIMIT_RULE,
        find_pin_rule_violations,
    )

    violations = find_pin_rule_violations(
        [_KNOWING_DEFINING, _KNOWING_DEFINING, _KNOWING_ILLUSTRATING],
        "跨科",
    )

    assert violations == [KNOWING_DEFINING_LIMIT_RULE, CROSS_SUBJECT_RELATE_RULE]


def test_pin_rule_violation_helper_returns_empty_for_compliant_pins() -> None:
    from src.social_studies.pin_rules import find_pin_rule_violations

    assert find_pin_rule_violations([], "跨科") == []
    assert find_pin_rule_violations(
        [_KNOWING_DEFINING, _REASONING_RELATE, None],
        "跨科",
    ) == []


# ── #834: a pinned 學習內容/學習表現 narrows a blank/multi-valued 科目, and a ──
# ── pinned 學習內容 domain tag narrows a blank 內容領域 ─────────────────────


def test_blank_subject_is_narrowed_to_admitting_candidates_by_pinned_content() -> None:
    from src.social_studies.sampler import sample_params

    for seed in range(200):
        params = sample_params(seed=seed, learning_content=["公Bn-Ⅳ-3"])

        assert params.科目.value in {"公民與社會", "跨科"}


def test_multi_valued_subject_is_narrowed_to_the_single_admitting_candidate() -> None:
    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import QuestionSubject

    params = sample_params(
        seed=3,
        subject=[QuestionSubject("公民與社會"), QuestionSubject("地理")],
        learning_content=["公Bj-Ⅳ-1"],
    )

    assert params.科目.value == "公民與社會"


def test_blank_subject_is_narrowed_by_two_pinned_content_codes_to_cross_subject() -> None:
    from src.social_studies.sampler import sample_params

    params = sample_params(
        seed=11,
        learning_content=["公Bn-Ⅳ-3", "歷Fb-Ⅳ-1"],
    )

    assert params.科目.value == "跨科"


def test_blank_subject_is_narrowed_by_pinned_cross_subject_performance_code() -> None:
    from src.social_studies.sampler import sample_params

    for seed in range(50):
        params = sample_params(seed=seed, learning_performance=["公1c-Ⅳ-1"])

        assert params.科目.value in {"公民與社會", "跨科"}


def test_blank_domain_is_narrowed_to_the_pinned_content_codes_tagged_domain() -> None:
    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import QuestionSubject

    for seed in range(200):
        params = sample_params(
            seed=seed,
            subject=[QuestionSubject("公民與社會")],
            learning_content=["公Bn-Ⅳ-3"],
        )

        assert params.內容領域.value == "Civic Institutions and Systems"


def test_blank_domain_is_unrestricted_by_untagged_pinned_history_and_geography_codes() -> None:
    from src.social_studies.sampler import sample_params
    from src.social_studies.schemas import ContentDomain, QuestionSubject

    observed_domains = {
        sample_params(
            seed=seed,
            subject=[QuestionSubject("跨科")],
            learning_content=["歷Fb-Ⅳ-1", "地Bb-Ⅳ-1"],
        ).內容領域
        for seed in range(200)
    }

    assert observed_domains == set(ContentDomain)


def test_a_code_absent_from_the_content_admission_map_narrows_subject_to_nothing_admitted(
    monkeypatch,
) -> None:
    """An unknown/mistyped pinned code admits no candidate (#834 ruling); with

    no rejection yet, an empty narrowed range falls back to the unfiltered
    candidate set rather than raising.
    """
    from src.social_studies import sampler

    monkeypatch.setattr(
        sampler,
        "_LC_DATA",
        {"學習內容": [{"學習階段": "第四學習階段", "科目": "公", "value": "公Real-Ⅳ-1"}]},
    )
    monkeypatch.setattr(sampler, "_LP_DATA", {"學習表現": []})

    params = sampler.sample_params(seed=5, learning_content=["公Unknown-Ⅳ-9"])

    assert params.科目 is not None

"""generate_one threads the grade-derived stage into both stages (issue #91)."""

from __future__ import annotations

from pathlib import Path

import src.natural_sciences.cli as ns_cli
from src.config import Config
from src.natural_sciences.sampler import sample_params


class _FakeTextClient:
    """Non-LLMClient fake → cli uses the embedded-subquestions path."""

    def get_observer(self):
        return None

    def generate_json(self, *_args, **_kwargs):
        return {
            "核心問題": "測試核心問題",
            "文本": "測試文本",
            "取材來源": ["測試"],
            "subquestions": [
                {
                    "序號": 1,
                    "題型": "Simple multiple-choice",
                    "出題概念": "測試",
                    "題目": "題目？",
                    "答案": "A",
                    "答案解析": "解析",
                },
            ],
        }


def test_dry_run_prompts_use_grade_derived_stage():
    config = Config(data_dir=Path("data"))
    params = sample_params(grade=10, seed=7)
    out = ns_cli.generate_one(config, None, params, "ns_test_001", dry_run=True)
    assert isinstance(out, str)
    assert "專門為第五學習階段（10年級、11年級、12年級）" in out
    assert "10年級（第五學習階段）" in out


def test_generate_one_passes_grade_stage_to_sub_system(tmp_path, monkeypatch):
    captured: dict = {}
    real = ns_cli.build_subquestion_system_prompt

    def spy(**kwargs):
        captured.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(ns_cli, "build_subquestion_system_prompt", spy)
    config = Config(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    params = sample_params(grade=11, seed=2)
    question = ns_cli.generate_one(
        config=config,
        client=_FakeTextClient(),
        params=params,
        question_id="ns_test_002",
        skip_verify=True,
    )
    assert not isinstance(question, str)
    assert captured["learning_stage"] == "第五學習階段"
    assert '"學習階段": "第五學習階段"' in captured["content_text"]
    assert '"學習階段": "第四學習階段"' not in captured["content_text"]

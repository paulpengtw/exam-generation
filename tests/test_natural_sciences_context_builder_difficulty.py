"""NS text + subquestion prompts must NOT contain `## 難度要求` (#282).

Formerly asserted presence; issue #282 removes 難度 from the NS path.
The authoritative assertions now live in test_ns_difficulty_leaves_pipeline.py;
this file is kept as a thin alias so search-by-filename still finds it.
"""

from __future__ import annotations

import random
from pathlib import Path


def test_ns_text_prompt_has_no_difficulty_section(tmp_path: Path) -> None:
    from src.natural_sciences.context_builder import build_text_user_prompt
    from src.natural_sciences.sampler import sample_params

    params = sample_params(seed=1)
    prompt, _ = build_text_user_prompt(params, tmp_path, rng=random.Random(1))
    assert "## 難度要求" not in prompt


def test_ns_subquestion_prompt_has_no_difficulty_section(tmp_path: Path) -> None:
    from src.natural_sciences.context_builder import build_subquestion_user_prompt
    from src.natural_sciences.sampler import sample_params

    params = sample_params(seed=1)
    sq_plan = {"序號": 1, "題型": "Simple-multiple-choice", "出題概念": "test"}
    prompt, _ = build_subquestion_user_prompt(
        核心問題="核心",
        文本="文本",
        取材來源=["來源"],
        sq_plan=sq_plan,
        params=params,
        few_shot_dir=tmp_path,
        rng=random.Random(1),
    )
    assert "## 難度要求" not in prompt

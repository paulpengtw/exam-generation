from __future__ import annotations

import hashlib
import random
from pathlib import Path


def test_math_group_prompts_describe_the_requested_group_contract() -> None:
    from src.context_builder import (
        build_subquestion_system_prompt,
        build_subquestion_user_prompt,
        build_text_system_prompt,
        build_text_user_prompt,
    )
    from src.sampler import sample_params

    params = sample_params(grade=8, seed=7, content_type="純文字", sub_question_count=4)
    few_shot_dir = Path("data/few_shot")

    text_system = build_text_system_prompt()
    text_user, _, _draws = build_text_user_prompt(
        params,
        few_shot_dir,
        rng=random.Random(19),
    )
    sub_system = build_subquestion_system_prompt("第四學習階段")
    sub_user, _, _draws = build_subquestion_user_prompt(
        核心問題="如何比較兩種方案？",
        文本="方案甲每件 10 元，方案乙每件 12 元。",
        取材來源=["試算資料"],
        sq_plan={"序號": 1, "題型": "選擇題", "出題概念": "比較單價"},
        params=params,
        few_shot_dir=few_shot_dir,
    )

    assert "小題數量" in text_user
    assert "4" in text_user
    for field in ("核心問題", "文本", "取材來源", "subquestions"):
        assert field in text_system
        assert field in text_user
    for field in ("題目", "答案", "答案解析", "誘答分析"):
        assert field in sub_system
        assert field in sub_user
    assert "評分規準" not in sub_system
    assert "維持單題輸出結構（不是題組）" not in text_system
    assert "維持單題輸出結構（不是題組）" not in text_user


def test_math_flat_prompt_contract_is_stable_for_a_fixed_keyed_seed() -> None:
    from src.context_builder import build_user_prompt
    from src.sampler import sample_params

    params = sample_params(grade=8, seed=7, content_type="純文字")
    prompt, images, _draws = build_user_prompt(
        params,
        Path("data/few_shot"),
        rng=random.Random(19),
    )

    assert images == []
    assert (
        "7. 維持單題輸出結構（不是題組）：不要產生 `subquestions`、`核心問題`、`文本`、"
        "`評分規準` 等題組欄位。"
    ) in prompt
    assert hashlib.sha256(prompt.encode()).hexdigest() == (
        "4fa880d9baf41d69d15c97469fe578248c14a16e7c28c06979fb66ceceb48c88"
    )

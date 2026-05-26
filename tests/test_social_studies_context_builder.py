from __future__ import annotations

import random

from src.social_studies.context_builder import build_user_prompt
from src.social_studies.sampler import sample_params


def test_topic_replaces_context_in_social_studies_prompt(tmp_path) -> None:
    params = sample_params(seed=1)

    prompt, images = build_user_prompt(
        params,
        tmp_path,
        rng=random.Random(1),
        user_topic="氣候變遷與都市規劃",
    )

    assert images == []
    assert "- **情境**：氣候變遷與都市規劃（PISA閱讀情境）" in prompt
    assert "## 指定情境（請直接取代原本的 PISA 情境）" in prompt
    assert "主題 / 議題：氣候變遷與都市規劃" in prompt

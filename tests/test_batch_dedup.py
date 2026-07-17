"""Unit tests for the batch-level prior-scope helper (issue #111)."""

from __future__ import annotations

import logging

from src.common.batch_dedup import (
    _PRIOR_SCOPES_CAP,
    PriorScope,
    extract_math_prior_scope,
    extract_ns_prior_scope,
    extract_ss_prior_scope,
    format_prior_scopes_block,
)


def test_format_returns_empty_string_when_no_scopes() -> None:
    assert format_prior_scopes_block([]) == ""


def test_format_renders_summary_and_codes() -> None:
    scopes = [
        PriorScope(summary="人口老化如何影響社區資源？", codes=["歷Ka-Ⅳ-1", "地Ab-Ⅳ-2"]),
        PriorScope(summary="能源轉型的取捨", codes=["自Nc-Ⅳ-3"]),
    ]
    block = format_prior_scopes_block(scopes)
    assert "## 已生成題目（請避免相似範圍）" in block
    assert "1. 核心問題：人口老化如何影響社區資源？；學習內容：歷Ka-Ⅳ-1, 地Ab-Ⅳ-2" in block
    assert "2. 核心問題：能源轉型的取捨；學習內容：自Nc-Ⅳ-3" in block


def test_format_renders_empty_codes_as_placeholder() -> None:
    block = format_prior_scopes_block([PriorScope(summary="測試主題", codes=[])])
    assert "1. 核心問題：測試主題；學習內容：（無）" in block


def test_format_caps_at_ten_most_recent_entries() -> None:
    scopes = [
        PriorScope(summary=f"主題{i}", codes=[f"X-{i}"]) for i in range(1, 13)
    ]
    assert _PRIOR_SCOPES_CAP == 10
    block = format_prior_scopes_block(scopes)
    # Oldest two dropped; the surviving ten start with 主題3 and end with 主題12.
    assert "主題1；" not in block
    assert "主題2；" not in block
    assert "1. 核心問題：主題3；" in block
    assert "10. 核心問題：主題12；" in block


def test_extract_math_uses_出題概念_and_學習內容_codes() -> None:
    from src.schemas import ExamQuestion, LearningContentItem

    question = ExamQuestion.model_construct(
        id="q_test",
        情境=[],
        題型種類="單一題",
        題型="選擇題",
        數學思考=[],
        學習內容=[
            LearningContentItem(編碼="N-7-1", 說明="整數運算"),
            LearningContentItem(編碼="N-7-2", 說明="有理數"),
            LearningContentItem(編碼="N-7-1", 說明="整數運算"),  # duplicate
        ],
        題目=[],
        正確解題分析=[],
        出題概念="評量學生能否比較有理數大小",
    )
    scope = extract_math_prior_scope(question)
    assert scope is not None
    assert scope.summary == "評量學生能否比較有理數大小"
    assert scope.codes == ["N-7-1", "N-7-2"]  # order preserved, deduped


def test_extract_math_returns_none_when_both_summary_and_codes_missing(caplog) -> None:
    from src.schemas import ExamQuestion

    question = ExamQuestion.model_construct(
        id="q_empty",
        情境=[],
        題型種類="單一題",
        題型="選擇題",
        數學思考=[],
        學習內容=[],
        題目=[],
        正確解題分析=[],
        出題概念="",
    )
    with caplog.at_level(logging.DEBUG, logger="src.common.batch_dedup"):
        scope = extract_math_prior_scope(question)
    assert scope is None
    assert any("skipping prior scope" in rec.message for rec in caplog.records)


def test_extract_ss_uses_核心問題_and_aggregated_subquestion_codes() -> None:
    from src.social_studies.schemas import (
        ExamQuestion,
        LearningContentRef,
        SubQuestion,
    )

    question = ExamQuestion.model_construct(
        id="ss_test",
        核心問題="工業革命如何改變勞動條件？",
        文本="…",
        取材來源=[],
        subquestions=[
            SubQuestion.model_construct(
                id="ss_test-01",
                序號=1,
                年級=8,
                科目=["歷史"],
                核心素養=[],
                學習內容=[LearningContentRef(編碼="歷Ka-Ⅳ-1", 說明="工業革命")],
                學習表現=[],
                題型="選擇題",
                題目="…",
            ),
            SubQuestion.model_construct(
                id="ss_test-02",
                序號=2,
                年級=8,
                科目=["公民與社會"],
                核心素養=[],
                學習內容=[
                    LearningContentRef(編碼="公Ab-Ⅳ-2", 說明="勞動權益"),
                    LearningContentRef(編碼="歷Ka-Ⅳ-1", 說明="工業革命"),
                ],
                學習表現=[],
                題型="選擇題",
                題目="…",
            ),
        ],
        情境=[],
        題型種類="題組題",
        題型="選擇題",
        閱讀歷程=[],
        文本形式="連續文本",
    )
    scope = extract_ss_prior_scope(question)
    assert scope is not None
    assert scope.summary == "工業革命如何改變勞動條件？"
    assert scope.codes == ["歷Ka-Ⅳ-1", "公Ab-Ⅳ-2"]


def test_extract_ns_uses_核心問題_and_aggregated_subquestion_codes() -> None:
    from src.natural_sciences.schemas import (
        ExamQuestion,
        LearningContentRef,
        SubQuestion,
    )

    question = ExamQuestion.model_construct(
        id="ns_test",
        核心問題="海洋酸化對生態的影響",
        文本="…",
        取材來源=[],
        subquestions=[
            SubQuestion.model_construct(
                id="ns_test-01",
                序號=1,
                年級=8,
                科目=["自然科學"],
                科學能力=["能力一"],
                核心素養=[],
                學習內容=[LearningContentRef(編碼="INc-Ⅳ-1", 說明="…")],
                學習表現=[],
                題型="Simple-multiple-choice",
                題目="…",
            ),
        ],
        情境=[],
        情境子類別="Environment",
        題型種類="題組題",
        題型="Simple-multiple-choice",
        科學能力=["能力一"],
    )
    scope = extract_ns_prior_scope(question)
    assert scope is not None
    assert scope.summary == "海洋酸化對生態的影響"
    assert scope.codes == ["INc-Ⅳ-1"]


def test_math_build_user_prompt_no_scopes_is_byte_identical(tmp_path) -> None:
    import random

    from src.context_builder import build_user_prompt
    from src.sampler import sample_params

    grade_content = {g: [] for g in [7, 8, 9]}
    params = sample_params(grade_content=grade_content, seed=1)

    baseline, _ = build_user_prompt(params, tmp_path, rng=random.Random(2))
    with_none, _ = build_user_prompt(
        params, tmp_path, rng=random.Random(2), prior_scopes=None,
    )
    with_empty, _ = build_user_prompt(
        params, tmp_path, rng=random.Random(2), prior_scopes=[],
    )
    assert baseline == with_none == with_empty
    assert "已生成題目" not in baseline


def test_math_build_user_prompt_renders_prior_scopes_block(tmp_path) -> None:
    import random

    from src.common.batch_dedup import PriorScope
    from src.context_builder import build_user_prompt
    from src.sampler import sample_params

    grade_content = {g: [] for g in [7, 8, 9]}
    params = sample_params(grade_content=grade_content, seed=1)
    scopes = [PriorScope(summary="比較有理數大小", codes=["N-7-1", "N-7-2"])]

    prompt, _ = build_user_prompt(
        params, tmp_path, rng=random.Random(2), prior_scopes=scopes,
    )
    assert "## 已生成題目（請避免相似範圍）" in prompt
    assert "1. 核心問題：比較有理數大小；學習內容：N-7-1, N-7-2" in prompt


def test_math_batch_loop_forwards_prior_scopes_to_next_question(tmp_path) -> None:
    """After question 1 completes, question 2's user prompt sees question 1's scope."""
    from pathlib import Path

    from src.cli import generate_with_corrections
    from src.common.batch_dedup import PriorScope, extract_math_prior_scope
    from src.config import Config
    from src.sampler import sample_params

    class _RecordingClient:
        def __init__(self) -> None:
            self.user_prompts: list[str] = []

        def get_observer(self):
            return None

        def generate_json(self, _system, user, *_args, **_kwargs):
            self.user_prompts.append(user)
            idx = len(self.user_prompts)
            return {
                "情境": ["個人"],
                "題型種類": "單一題",
                "題型": "選擇題",
                "數學思考": ["運用"],
                "學習內容": [{"編碼": f"N-7-{idx}", "說明": "測試"}],
                "題目": [f"題 {idx}"],
                "正確解題分析": [f"解 {idx}"],
                "出題概念": f"評量概念 {idx}",
            }

    config = Config(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    grade_content = {g: [] for g in [7, 8, 9]}
    client = _RecordingClient()

    prior_scopes: list[PriorScope] = []
    for i in range(2):
        params = sample_params(grade_content=grade_content, seed=100 + i)
        result = generate_with_corrections(
            config=config,
            client=client,
            curriculum=[],
            performance={},
            intro_text="",
            grade_content=grade_content,
            params=params,
            question_id=f"q_test_{i+1:03d}",
            max_retries=0,
            skip_verify=True,
            prior_scopes=list(prior_scopes),
        )
        scope = extract_math_prior_scope(result)
        assert scope is not None
        prior_scopes.append(scope)

    # First prompt has no dedup block; second must show question 1's summary + code.
    assert "已生成題目" not in client.user_prompts[0]
    assert "1. 核心問題：評量概念 1；學習內容：N-7-1" in client.user_prompts[1]


def test_ss_build_text_user_prompt_no_scopes_is_byte_identical(tmp_path) -> None:
    from src.social_studies.context_builder import build_text_user_prompt
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=5)

    baseline, _ = build_text_user_prompt(params, tmp_path)
    with_none, _ = build_text_user_prompt(params, tmp_path, prior_scopes=None)
    with_empty, _ = build_text_user_prompt(params, tmp_path, prior_scopes=[])
    assert baseline == with_none == with_empty
    assert "已生成題目" not in baseline


def test_ss_build_text_user_prompt_renders_prior_scopes_block(tmp_path) -> None:
    from src.common.batch_dedup import PriorScope
    from src.social_studies.context_builder import build_text_user_prompt
    from src.social_studies.sampler import sample_params

    params = sample_params(seed=5)
    scopes = [
        PriorScope(summary="工業革命如何改變勞動條件？", codes=["歷Ka-Ⅳ-1", "公Ab-Ⅳ-2"]),
    ]

    prompt, _ = build_text_user_prompt(params, tmp_path, prior_scopes=scopes)
    assert "## 已生成題目（請避免相似範圍）" in prompt
    assert "1. 核心問題：工業革命如何改變勞動條件？；學習內容：歷Ka-Ⅳ-1, 公Ab-Ⅳ-2" in prompt


def test_ss_batch_loop_forwards_prior_scopes_to_next_question(tmp_path) -> None:
    from pathlib import Path

    from src.common.batch_dedup import PriorScope, extract_ss_prior_scope
    from src.config import Config
    from src.social_studies.cli import generate_with_corrections
    from src.social_studies.sampler import sample_params

    class _RecordingSSClient:
        def __init__(self) -> None:
            self.user_prompts: list[str] = []

        def get_observer(self):
            return None

        def generate_json(self, _system, user, *_args, **_kwargs):
            self.user_prompts.append(user)
            idx = len(self.user_prompts)
            return {
                "核心問題": f"社會核心問題 {idx}",
                "文本": "測試文本",
                "取材來源": [],
                "subquestions": [
                    {
                        "序號": 1,
                        "年級": 8,
                        "科目": ["歷史"],
                        "核心素養": ["社-J-A2"],
                        "學習內容": [{"編碼": f"歷Ka-Ⅳ-{idx}", "說明": "測試"}],
                        "學習表現": [{"編碼": "社1b-Ⅳ-1", "說明": "測試"}],
                        "出題概念": "測試",
                        "題型": "選擇題",
                        "題目": "測試題目",
                        "答案": "A",
                        "答案解析": "測試",
                        "評分規準": [],
                    }
                ],
                "題目": ["文本", "測試"],
                "正確解題分析": ["A"],
            }

    config = Config(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    client = _RecordingSSClient()

    prior_scopes: list[PriorScope] = []
    for i in range(2):
        params = sample_params(seed=200 + i)
        result = generate_with_corrections(
            config=config,
            client=client,
            params=params,
            question_id=f"ss_test_{i+1:03d}",
            max_retries=0,
            skip_verify=True,
            prior_scopes=list(prior_scopes),
        )
        scope = extract_ss_prior_scope(result)
        assert scope is not None
        prior_scopes.append(scope)

    # `_RecordingSSClient` is used for both the 文本生成器 call and the sub_generator
    # calls. The first captured prompt (index 0) is the 文本生成器 prompt for question 1;
    # locate the 文本生成器 prompt for question 2 — the first prompt captured AFTER
    # question 1 finished — and confirm it carries the dedup block.
    text_prompts = [p for p in client.user_prompts if "## 已生成題目" in p]
    assert text_prompts, "expected at least one prompt to carry the dedup block"
    assert "1. 核心問題：社會核心問題 1；學習內容：歷Ka-Ⅳ-1" in text_prompts[0]


def test_ns_build_text_user_prompt_no_scopes_is_byte_identical(tmp_path) -> None:
    from src.natural_sciences.context_builder import build_text_user_prompt
    from src.natural_sciences.sampler import sample_params

    params = sample_params(seed=7)

    baseline, _ = build_text_user_prompt(params, tmp_path)
    with_none, _ = build_text_user_prompt(params, tmp_path, prior_scopes=None)
    with_empty, _ = build_text_user_prompt(params, tmp_path, prior_scopes=[])
    assert baseline == with_none == with_empty
    assert "已生成題目" not in baseline


def test_ns_build_text_user_prompt_renders_prior_scopes_block(tmp_path) -> None:
    from src.common.batch_dedup import PriorScope
    from src.natural_sciences.context_builder import build_text_user_prompt
    from src.natural_sciences.sampler import sample_params

    params = sample_params(seed=7)
    scopes = [PriorScope(summary="海洋酸化對生態的影響", codes=["INc-Ⅳ-1"])]

    prompt, _ = build_text_user_prompt(params, tmp_path, prior_scopes=scopes)
    assert "## 已生成題目（請避免相似範圍）" in prompt
    assert "1. 核心問題：海洋酸化對生態的影響；學習內容：INc-Ⅳ-1" in prompt


def test_ns_batch_loop_forwards_prior_scopes_to_next_question(tmp_path) -> None:
    from pathlib import Path

    from src.common.batch_dedup import PriorScope, extract_ns_prior_scope
    from src.config import Config
    from src.natural_sciences.cli import generate_with_corrections
    from src.natural_sciences.sampler import sample_params

    class _RecordingNSClient:
        def __init__(self) -> None:
            self.user_prompts: list[str] = []

        def get_observer(self):
            return None

        def generate_json(self, _system, user, *_args, **_kwargs):
            self.user_prompts.append(user)
            idx = len(self.user_prompts)
            return {
                "核心問題": f"科學核心問題 {idx}",
                "文本": "科學測試文本",
                "取材來源": [],
                "subquestions": [
                    {
                        "序號": 1,
                        "年級": 8,
                        "科目": ["自然科學"],
                        "科學能力": ["能力一"],
                        "核心素養": [],
                        "學習內容": [{"編碼": f"INc-Ⅳ-{idx}", "說明": "測試"}],
                        "學習表現": [{"編碼": "tr-Ⅳ-1", "說明": "測試"}],
                        "出題概念": "測試",
                        "題型": "Simple multiple-choice",
                        "題目": "測試題目",
                        "答案": "A",
                        "答案解析": "測試",
                        "評分規準": [],
                    }
                ],
                "題目": ["文本", "測試"],
                "正確解題分析": ["A"],
            }

    config = Config(api_key="x", output_dir=tmp_path, data_dir=Path("data"))
    client = _RecordingNSClient()

    prior_scopes: list[PriorScope] = []
    for i in range(2):
        params = sample_params(seed=300 + i)
        result = generate_with_corrections(
            config=config,
            client=client,
            params=params,
            question_id=f"ns_test_{i+1:03d}",
            max_retries=0,
            skip_verify=True,
            prior_scopes=list(prior_scopes),
        )
        scope = extract_ns_prior_scope(result)
        assert scope is not None
        prior_scopes.append(scope)

    text_prompts = [p for p in client.user_prompts if "## 已生成題目" in p]
    assert text_prompts, "expected at least one prompt to carry the dedup block"
    assert "1. 核心問題：科學核心問題 1；學習內容：INc-Ⅳ-1" in text_prompts[0]


def test_server_generate_stream_accumulates_prior_scopes_across_math_workers(tmp_path) -> None:
    """Two sequentially-completing math workers: the second must receive scope 1.

    `generate_question_stream` dispatches all workers concurrently via
    `loop.run_in_executor(None, ...)`, so with the default executor pool
    (several idle threads) both workers can reach their pre-call snapshot
    within microseconds of each other, before either has appended its
    scope. That is expected best-effort behavior per the design (early
    workers may see an empty snapshot). To deterministically exercise the
    "later worker observes an earlier worker's completed scope" path, this
    test pins the loop's default executor to a single worker thread, which
    forces strictly sequential execution of `worker_one` for the two
    dispatched questions.
    """
    import asyncio
    import concurrent.futures
    import threading
    import types
    from pathlib import Path

    from server.config import ServerConfig
    from server.generate import service
    from server.generate.models import GenerateParams
    from src.common.batch_dedup import PriorScope

    captured: dict[int, list[PriorScope] | None] = {}
    order_lock = threading.Lock()
    counter = {"n": 0}

    def fake_math_gwc(**kwargs):
        idx = kwargs.get("question_id", "")
        prior = kwargs.get("prior_scopes")
        with order_lock:
            counter["n"] += 1
            captured[counter["n"]] = list(prior) if prior is not None else None
        from src.schemas import ExamQuestion, LearningContentItem
        return ExamQuestion.model_construct(
            id=idx,
            情境=[],
            題型種類="單一題",
            題型="選擇題",
            數學思考=[],
            學習內容=[LearningContentItem(編碼=f"N-7-{counter['n']}", 說明="測試")],
            題目=[],
            正確解題分析=[],
            出題概念=f"概念 {counter['n']}",
            metadata=None,
        )

    original = service.math_generate_with_corrections
    service.math_generate_with_corrections = fake_math_gwc  # type: ignore[assignment]

    app_state = types.SimpleNamespace(
        renderer_pool=None,
        curriculum=[],
        performance={},
        intro_text="",
        grade_content={7: [], 8: [], 9: []},
    )
    config = ServerConfig(
        output_dir=tmp_path,
        data_dir=Path("data"),
        api_key="x",
        base_url="http://x",
        model_plan="p",
        model_execute="e",
        log_truncate=200,
        max_retries=0,
        subgen_max_concurrency=1,
    )
    params = GenerateParams(subject="math", count=2, skip_verify=True, seed=42)

    async def _drive() -> list[dict]:
        loop = asyncio.get_running_loop()
        loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=1))
        events: list[dict] = []
        async for evt in service.generate_question_stream(params, config, app_state):
            events.append(evt)
        return events

    try:
        asyncio.run(_drive())
    finally:
        service.math_generate_with_corrections = original  # type: ignore[assignment]

    # 2 workers ran sequentially; the second must see the first's scope.
    assert len(captured) == 2
    assert captured[1] == []
    assert captured[2] and captured[2][0].codes == ["N-7-1"]

"""Regression tests for paper-format scoring and retired SS question types."""

from __future__ import annotations

import csv
import json
import uuid
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from fastapi.testclient import TestClient

from server.app import create_app
from server.auth.dependencies import get_config, get_current_user
from server.config import ServerConfig
from server.db import get_async_session
from server.models import User
from server.rate_limit import limiter
from src.social_studies.context_builder import (
    build_subquestion_system_prompt,
    build_system_prompt,
    build_user_prompt,
)
from src.social_studies.sampler import sample_params
from src.social_studies.schemas import (
    ExamQuestion,
    QuestionType,
    RubricEntry,
    SubQuestion,
)
from src.social_studies.verifier import verify_question

REPO_ROOT = Path(__file__).resolve().parents[1]
RETIRED_TYPE = "封閉式建構反應題"


class _CurrentBuildAuthority:
    async def read(self) -> dict[str, object]:
        return {
            "schema": "exam-generation.release-policy/1",
            "environment": "production",
            "release_revision": 1,
            "released_build_id": "test-build-x",
            "admission": "open",
            "supported_recovery_formats": [],
        }


def _social_generate_request(**params: str) -> object:
    app = create_app(
        release_authority_source=_CurrentBuildAuthority(),  # type: ignore[arg-type]
    )
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="paper-rescore@example.com"
    )
    app.dependency_overrides[get_async_session] = lambda: None
    app.dependency_overrides[get_config] = lambda: ServerConfig(
        api_key="x", gemini_api_key="x"
    )
    limiter.reset()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            gate_params = {"subject": "social_studies", "stream_version": 3, **params}
            return client.get(
                "/api/generate",
                params=gate_params,
                headers={"X-Frontend-Build-ID": "test-build-x"},
            )
    finally:
        limiter.reset()


def test_social_question_type_enum_and_csv_retire_closed_format() -> None:
    csv_path = REPO_ROOT / "data/social_studies/curriculum/schema_parameters.csv"
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    type_rows = {row["value"]: row["instruction"] for row in rows if row["類別"] == "題型"}
    assert list(QuestionType) == ["選擇題", "開放式建構反應題", "拖放題", "滑桿題"]
    assert RETIRED_TYPE not in type_rows
    assert type_rows["選擇題"] == (
        "四選一單選題，計分 0/1：答對得 1 分、答錯 0 分。"
        "選項設計應包含具誘答力的錯誤選項，並於誘答分析欄以認知偏誤角度說明各誘答項為何吸引人。"
        "ICCS 2022 約 85% 試題為此形式，應為題組的主要題型。"
    )
    assert type_rows["開放式建構反應題"] == (
        "學生需自行組織文字作答並說明思考過程。計分採每題專屬評分指引（scoring guide），"
        "固定 2 / 1 / 0 三級。評分規準表必須隨題產出：[2] 附 1 個學生作答實例、"
        "[1] 附 2 個（第一個為最小對照）、[0] 附 1 個。"
    )
    assert type_rows["拖放題"] == (
        "互動題型，僅限數位卷面（target surface = 數位）。學生將棋子（draggables）拖放至目標區（"
        "targets）完成配對、分類或排序。必須輸出 interaction 規格：draggables、targets、"
        "correct_mapping、exact_match、shuffle_draggables。預設 partial credit：每格放對得 1 分；"
        "各放置位置相互扣連時可設 "
        "exact_match=true 改為全對計分。"
        "誘答分析以「棋子→錯誤目標」配對為鍵，說明常見錯置的概念混淆。"
    )
    assert type_rows["滑桿題"] == (
        "互動題型，僅限數位卷面。學生拖曳滑桿在數值範圍中標定答案，適用於自資料判讀或推估數值的題目。"
        "必須輸出 interaction 規格：min、max、step、unit、correct_value、tolerance。"
        "計分 0/1：作答值落在 correct_value ± tolerance 內得 1 分。"
        "誘答分析以命名的錯誤區間為鍵（如 below_range：誤讀舊年份資料）。"
    )


def test_social_cli_q_type_choices_follow_surviving_enum() -> None:
    from src.social_studies.cli import parse_args

    parsed = parse_args(["generate", "--q-type", "選擇題", "開放式建構反應題"])
    assert parsed.q_type == ["選擇題", "開放式建構反應題"]

    with pytest.raises(SystemExit):
        parse_args(["generate", "--q-type", RETIRED_TYPE])


def test_retired_subquestion_config_pin_is_a_422_with_retirement_message() -> None:
    response = _social_generate_request(
        subquestion_configs=json.dumps([{"question_type": RETIRED_TYPE}, {}], ensure_ascii=False),
    )

    assert response.status_code == 422
    assert RETIRED_TYPE in response.text
    assert "退役" in response.text


def test_retired_per_question_q_type_is_a_422_after_recursive_validation() -> None:
    response = _social_generate_request(
        count="1",
        per_question_params=json.dumps([{"q_type": [RETIRED_TYPE]}], ensure_ascii=False),
    )

    assert response.status_code == 422
    assert RETIRED_TYPE in response.text


def test_other_unknown_subquestion_config_types_remain_tolerated() -> None:
    from server.generate.models import GenerateParams

    params = GenerateParams(
        subject="social_studies",
        count=1,
        subquestion_configs=json.dumps([{"question_type": "future-paper-format"}]),
    )

    assert params.subquestion_configs is not None


def test_legacy_closed_question_type_deserializes_as_read_only_text() -> None:
    payload = {
        "id": "legacy-closed-1",
        "核心問題": "核心問題",
        "文本": "共用文本",
        "情境": ["公共"],
        "題型種類": "題組題",
        "題型": RETIRED_TYPE,
        "閱讀歷程": ["擷取訊息"],
        "文本形式": "連續文本—說明文",
        "subquestions": [
            {
                "id": "legacy-closed-1-01",
                "序號": 1,
                "年級": 8,
                "科目": ["歷史"],
                "題型": RETIRED_TYPE,
                "題目": "舊版小題",
                "答案": "答案",
                "答案解析": "解析",
            }
        ],
        "題目": ["共用文本", "舊版小題"],
        "正確解題分析": ["答案"],
    }

    question = ExamQuestion.model_validate(payload)

    assert question.題型 == RETIRED_TYPE
    assert question.subquestions[0].題型 == RETIRED_TYPE
    assert question.subquestions[0].題目 == "舊版小題"


@pytest.mark.parametrize("code", ["0", "1", "2", "0X", "3"])
def test_rubric_entry_accepts_legacy_and_native_integer_scale_codes(code: str) -> None:
    entry = RubricEntry(
        code=code,
        規準說明="依本題專屬評分指引判定",
        學生作答實例=["正確示例", "錯誤示例"],
    )

    assert entry.code == code
    assert entry.學生作答實例 == ["正確示例", "錯誤示例"]


def test_new_social_studies_prompts_use_native_scoring_language() -> None:
    # Build both the 文本生成器 system prompt and the 子題產生器 system prompt.
    system_prompt = build_system_prompt()
    subq_prompt = build_subquestion_system_prompt("第四學習階段")
    prompt = system_prompt + "\n" + subq_prompt

    # task 3.4: 含「計分 0/1」與「每題專屬評分指引」
    assert "計分 0/1" in prompt
    assert "每題專屬評分指引" in prompt

    # task 3.4: 不含「0..N」、「2/1/0/0X」與「每一分數級距附 1-2 個學生作答實例」
    assert "0..N" not in prompt
    assert "2/1/0/0X" not in prompt
    assert "每一分數級距附 1-2 個學生作答實例" not in prompt

    # task 3.4: 文本生成器 system prompt 不含「學生作答實例」
    assert "學生作答實例" not in system_prompt

    # task 3.4: 選擇題子句 byte-identical (stays unchanged)
    _MC_CLAUSE = "**選擇題**：四選一單選題，計分 0/1：答對得 1 分、答錯 0 分。"
    assert _MC_CLAUSE in system_prompt

    # Other existing invariants
    assert "全對才給分" not in prompt
    assert RETIRED_TYPE not in prompt


def test_few_shot_prompt_defers_scoring_scale_to_current_instructions(tmp_path: Path) -> None:
    params = sample_params(seed=1, q_type=[QuestionType("選擇題")])

    prompt, _images, _draws = build_user_prompt(
        params,
        tmp_path,
        disable_reference_fewshot=False,
    )

    assert "評分尺度以本提示的評分指引為準" in prompt
    assert "不以範例中的舊版代號為準" in prompt


def _question_with_rubric(*, cognitive_process: str | None, code: str) -> ExamQuestion:
    return ExamQuestion(
        id="rubric-era-test",
        情境=["公共"],
        題型種類="題組題",
        題型="開放式建構反應題",
        核心問題="如何解釋文本中的現象？",
        文本="文本素材",
        subquestions=[
            SubQuestion(
                id="rubric-era-test-01",
                序號=1,
                年級=8,
                科目=["歷史"],
                題型="開放式建構反應題",
                認知歷程=cognitive_process,
                題目="請說明你的理由。",
                答案="合理說明",
                答案解析="依文本判定",
                評分規準=[RubricEntry(code=code, 規準說明="說明", 學生作答實例=["示例"])],
            )
        ],
        題目=["文本素材", "請說明你的理由。"],
        正確解題分析=["合理說明"],
    )


class _PassingVerifierClient:
    def generate_with_image(self, *_args, **_kwargs) -> str:
        return json.dumps(
            {
                "my_answer": "合理說明",
                "provided_answer": "合理說明",
                "answer_match": True,
                "passed": True,
                "details": "LLM 審核通過",
            },
            ensure_ascii=False,
        )


def test_new_era_0x_rubric_code_fails_deterministic_verification() -> None:
    question = _question_with_rubric(
        cognitive_process="Knowing–Defining and Describing",
        code="0X",
    )

    result = verify_question(_PassingVerifierClient(), question)

    assert result.passed is False
    assert "0X" in result.details
    assert "第1題" in result.details
    # task 3.6: details contains 「2 / 1 / 0」 and not 「0..N」
    assert "2 / 1 / 0" in result.details
    assert "0..N" not in result.details


def test_legacy_0x_rubric_code_is_left_untouched_by_new_era_check() -> None:
    question = _question_with_rubric(cognitive_process=None, code="0X")

    result = verify_question(_PassingVerifierClient(), question)

    assert result.passed is True
    assert result.details == "LLM 審核通過"


# ---------------------------------------------------------------------------
# Task 4.2: _ss_rubric_shape_check_hook tests
# ---------------------------------------------------------------------------

def _open_response_question_with_shape(
    *,
    cognitive_process: str | None,
    rubric_entries: list,
) -> ExamQuestion:
    """Build an SS open-response question with the given rubric entries."""
    return ExamQuestion(
        id="shape-check-test",
        情境=["公共"],
        題型種類="題組題",
        題型="開放式建構反應題",
        核心問題="測試用核心問題",
        文本="測試文本",
        subquestions=[
            SubQuestion(
                id="shape-check-test-01",
                序號=1,
                年級=8,
                科目=["歷史"],
                題型="開放式建構反應題",
                認知歷程=cognitive_process,
                題目="請說明你的理由。",
                答案="合理說明",
                答案解析="依文本判定",
                評分規準=rubric_entries,
            )
        ],
        題目=["測試文本", "請說明你的理由。"],
        正確解題分析=["合理說明"],
    )


def _conforming_rubric_entries() -> list:
    """Return a fully conforming 2/1/0 rubric with correct example counts."""
    from src.common.open_response_rubric import EXTRA_ITEMS_FIXED_SENTENCE
    return [
        RubricEntry(
            code="2",
            規準說明=f"完整說明。{EXTRA_ITEMS_FIXED_SENTENCE}",
            學生作答實例=["完整作答示例"],
        ),
        RubricEntry(
            code="1",
            規準說明="部分說明。",
            學生作答實例=["最小對照示例", "另一種缺口示例"],
        ),
        RubricEntry(
            code="0",
            規準說明="未進入推理。",
            學生作答實例=["錯誤作答示例"],
        ),
    ]


def test_ss_rubric_shape_check_fails_nonconforming_open_response_with_cognitive_process() -> None:
    """Task 4.2: a non-conforming rubric on a new-era SS open-response 小題 fails verification."""
    # Rubric with wrong level set: uses 0X instead of 0
    question = _open_response_question_with_shape(
        cognitive_process="Knowing–Defining and Describing",
        rubric_entries=[
            RubricEntry(code="2", 規準說明="完整說明。", 學生作答實例=["完整作答"]),
            RubricEntry(code="1", 規準說明="部分說明。", 學生作答實例=["示例"]),
        ],
    )

    result = verify_question(_PassingVerifierClient(), question)

    assert result.passed is False
    assert "[評分規準形狀檢核]" in result.details
    assert "第1題" in result.details


def test_ss_rubric_shape_check_preserves_existing_details_on_llm_fail() -> None:
    """Task 4.2: when LLM already failed, shape-check appends to existing details."""
    class _FailingVerifierClient:
        def generate_with_image(self, *_args, **_kwargs) -> str:
            return json.dumps(
                {
                    "my_answer": "不確定",
                    "provided_answer": "合理說明",
                    "answer_match": False,
                    "passed": False,
                    "details": "LLM 審核不通過：答案不符",
                },
                ensure_ascii=False,
            )

    question = _open_response_question_with_shape(
        cognitive_process="Knowing–Defining and Describing",
        rubric_entries=[
            RubricEntry(code="2", 規準說明="完整說明。", 學生作答實例=["完整作答"]),
        ],
    )

    result = verify_question(_FailingVerifierClient(), question)

    assert result.passed is False
    # Both the LLM details and the shape-check details should be present.
    assert "LLM 審核不通過" in result.details
    assert "[評分規準形狀檢核]" in result.details


def test_ss_rubric_shape_check_skips_subquestion_without_cognitive_process() -> None:
    """Task 4.2: a 小題 without 認知歷程 carrying 0X still passes with details unchanged."""
    question = _question_with_rubric(cognitive_process=None, code="0X")

    result = verify_question(_PassingVerifierClient(), question)

    # The shape check skips (no 認知歷程); the 0X scale check also skips.
    assert result.passed is True
    assert result.details == "LLM 審核通過"


def test_ss_rubric_shape_check_passes_conforming_open_response() -> None:
    """Task 4.2: a conforming rubric on a new-era SS open-response 小題 passes."""
    question = _open_response_question_with_shape(
        cognitive_process="Knowing–Defining and Describing",
        rubric_entries=_conforming_rubric_entries(),
    )

    result = verify_question(_PassingVerifierClient(), question)

    assert result.passed is True
    assert "[評分規準形狀檢核]" not in result.details

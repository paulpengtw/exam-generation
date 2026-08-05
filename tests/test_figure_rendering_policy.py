"""Classification + dispatch tests for the figure-rendering routing policy.

Source of truth: docs/figure-rendering-policy.md.
"""

from __future__ import annotations

import pytest

from src.context_builder import CONTENT_TYPE_INSTRUCTIONS as MATH_CT
from src.natural_sciences.context_builder import (
    CONTENT_TYPE_INSTRUCTIONS as NS_CT,
)
from src.social_studies.context_builder import (
    CONTENT_TYPE_INSTRUCTIONS as SS_CT,
)

_SUBJECT_TABLES = [
    pytest.param("math", MATH_CT, id="math"),
    pytest.param("social_studies", SS_CT, id="social_studies"),
    pytest.param("natural_sciences", NS_CT, id="natural_sciences"),
]


@pytest.mark.parametrize("subject, table", _SUBJECT_TABLES)
def test_plain_text_bans_chart_spec(subject: str, table: dict) -> None:
    assert "純文字" in table
    text = table["純文字"]
    assert "chart_spec" in text
    # The policy forbids any chart_spec output for 純文字.
    assert ("不得輸出" in text) or ("不輸出" in text)


@pytest.mark.parametrize("subject, table", _SUBJECT_TABLES)
def test_illustrative_content_routes_to_gpt_image_or_html(
    subject: str, table: dict
) -> None:
    """含圖片 must route realistic diagrams to gpt_image and structured/semantic to html."""
    assert "含圖片" in table
    text = table["含圖片"]
    assert 'render_mode: "gpt_image"' in text, (
        f"{subject}: 含圖片 instruction must direct realistic diagrams to "
        f'render_mode: "gpt_image"'
    )
    assert 'render_mode: "html"' in text, (
        f"{subject}: 含圖片 instruction must direct structured/semantic content to "
        f'render_mode: "html"'
    )


@pytest.mark.parametrize("subject, table", _SUBJECT_TABLES)
def test_quantitative_content_routes_to_chart_and_html_for_tables(
    subject: str, table: dict
) -> None:
    assert "graphs/charts/tables" in table
    text = table["graphs/charts/tables"]
    assert 'render_mode: "chart"' in text, (
        f"{subject}: graphs/charts/tables instruction must mention render_mode: \"chart\""
    )
    assert 'render_mode: "html"' in text, (
        f"{subject}: graphs/charts/tables instruction must also mention "
        'render_mode: "html" for tables'
    )


# --- Dispatch tests ---------------------------------------------------------


class _RecordingHtmlRenderer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def render(self, html: str, output_path):  # noqa: D401
        self.calls.append((html, str(output_path)))
        return str(output_path)


class _RecordingLlmClient:
    def __init__(self) -> None:
        self.html_calls: list[dict] = []
        self.image_calls: list[dict] = []

    def generate(self, system: str, user: str, purpose: str = "") -> str:
        self.html_calls.append({"system": system, "user": user, "purpose": purpose})
        return "<!DOCTYPE html><html><body>fake</body></html>"

    def generate_image(self, prompt: str, output_path):
        self.image_calls.append({"prompt": prompt, "output_path": str(output_path)})
        return str(output_path)


def test_dispatch_chart_render_mode_uses_matplotlib(tmp_path, monkeypatch) -> None:
    from src import renderer

    called: dict = {}

    def fake_render_chart(spec, output_path):
        called["spec"] = spec
        called["output_path"] = str(output_path)
        return str(output_path)

    monkeypatch.setattr(renderer, "render_chart", fake_render_chart)
    html_renderer = _RecordingHtmlRenderer()
    llm_client = _RecordingLlmClient()

    out = tmp_path / "hist.png"
    result = renderer.render_image(
        {"render_mode": "chart", "chart_type": "histogram", "data": {"bins": [], "counts": []}},
        out,
        html_renderer=html_renderer,
        llm_client=llm_client,
        image_generation_mode="html",
    )

    assert result == str(out)
    assert called["spec"]["chart_type"] == "histogram"
    assert html_renderer.calls == []
    assert llm_client.html_calls == []
    assert llm_client.image_calls == []


def test_dispatch_html_render_mode_uses_playwright(tmp_path) -> None:
    from src import renderer

    html_renderer = _RecordingHtmlRenderer()
    llm_client = _RecordingLlmClient()

    out = tmp_path / "table.png"
    result = renderer.render_image(
        {"render_mode": "html", "description": "課表", "data": {"columns": ["a"], "rows": [["1"]]}},
        out,
        html_renderer=html_renderer,
        llm_client=llm_client,
        image_generation_mode="html",
    )

    assert result == str(out)
    assert len(llm_client.html_calls) == 1
    assert len(html_renderer.calls) == 1
    assert llm_client.image_calls == []


def test_dispatch_gpt_image_mode_bypasses_render_mode(tmp_path) -> None:
    from src import renderer

    html_renderer = _RecordingHtmlRenderer()
    llm_client = _RecordingLlmClient()

    out = tmp_path / "gpt.png"
    result = renderer.render_image(
        {"render_mode": "chart", "chart_type": "histogram", "data": {}},
        out,
        html_renderer=html_renderer,
        llm_client=llm_client,
        image_generation_mode="gpt_image",
    )

    assert result == str(out)
    assert html_renderer.calls == []
    assert llm_client.html_calls == []
    assert len(llm_client.image_calls) == 1


def test_dispatch_gpt_image_render_mode_calls_llm_generate_image(tmp_path) -> None:
    from src import renderer

    html_renderer = _RecordingHtmlRenderer()
    llm_client = _RecordingLlmClient()

    out = tmp_path / "diagram.png"
    result = renderer.render_image(
        {
            "render_mode": "gpt_image",
            "description": "簡易蒸餾裝置示意圖",
            "data": {"components": []},
        },
        out,
        html_renderer=html_renderer,
        llm_client=llm_client,
        # caller does NOT override; spec-level render_mode drives the choice
        image_generation_mode="html",
    )

    assert result == str(out)
    assert html_renderer.calls == [], "html Playwright path must NOT be called"
    assert llm_client.html_calls == [], "LLM HTML-generation path must NOT be called"
    assert len(llm_client.image_calls) == 1, "generate_image must be called exactly once"


def test_dispatch_gpt_image_render_mode_returns_none_when_llm_client_missing(tmp_path) -> None:
    from src import renderer

    html_renderer = _RecordingHtmlRenderer()

    out = tmp_path / "diagram.png"
    result = renderer.render_image(
        {
            "render_mode": "gpt_image",
            "description": "示意圖",
            "data": {},
        },
        out,
        html_renderer=html_renderer,
        llm_client=None,
        image_generation_mode="html",
    )

    assert result is None
    assert html_renderer.calls == []


def test_dispatch_gpt_image_render_mode_returns_none_on_generate_image_exception(tmp_path) -> None:
    from src import renderer

    class _RaisingLlmClient(_RecordingLlmClient):
        def generate_image(self, prompt, output_path):  # type: ignore[override]
            raise RuntimeError("simulated image API failure")

    html_renderer = _RecordingHtmlRenderer()
    llm_client = _RaisingLlmClient()

    out = tmp_path / "diagram.png"
    result = renderer.render_image(
        {
            "render_mode": "gpt_image",
            "description": "示意圖",
            "data": {},
        },
        out,
        html_renderer=html_renderer,
        llm_client=llm_client,
        image_generation_mode="html",
    )

    assert result is None
    assert html_renderer.calls == []


def test_dispatch_unknown_render_mode_returns_none(tmp_path) -> None:
    from src import renderer

    html_renderer = _RecordingHtmlRenderer()
    llm_client = _RecordingLlmClient()

    out = tmp_path / "unknown.png"
    result = renderer.render_image(
        {"render_mode": "nonsense", "data": {}},
        out,
        html_renderer=html_renderer,
        llm_client=llm_client,
        image_generation_mode="html",
    )

    assert result is None
    assert html_renderer.calls == []
    assert llm_client.html_calls == []
    assert llm_client.image_calls == []


# --- Classification validation tests ---------------------------------------


def test_validator_plain_text_requires_no_chart_spec() -> None:
    """純文字 forbids every chart_spec and allows an absent one."""
    from src.common.figure_policy import validate_figure_routing

    assert validate_figure_routing("純文字", None) == []
    violations = validate_figure_routing("純文字", {"render_mode": "chart"})
    assert len(violations) == 1
    assert "純文字" in violations[0]


@pytest.mark.parametrize("render_mode", ["gpt_image", "html"])
def test_validator_illustrative_content_accepts_allowed_modes(render_mode: str) -> None:
    """含圖片 accepts gpt_image and html chart specs."""
    from src.common.figure_policy import validate_figure_routing

    assert validate_figure_routing("含圖片", {"render_mode": render_mode}) == []


def test_validator_illustrative_content_rejects_chart_and_missing_spec() -> None:
    """含圖片 rejects chart and a missing chart_spec."""
    from src.common.figure_policy import validate_figure_routing

    assert validate_figure_routing("含圖片", {"render_mode": "chart"})
    assert validate_figure_routing("含圖片", None)


@pytest.mark.parametrize("render_mode", ["chart", "html"])
def test_validator_quantitative_content_accepts_allowed_modes(render_mode: str) -> None:
    """graphs/charts/tables accepts chart and html chart specs."""
    from src.common.figure_policy import validate_figure_routing

    assert validate_figure_routing("graphs/charts/tables", {"render_mode": render_mode}) == []


def test_validator_quantitative_content_rejects_gpt_image_and_missing_spec() -> None:
    """graphs/charts/tables rejects gpt_image and a missing chart_spec."""
    from src.common.figure_policy import validate_figure_routing

    assert validate_figure_routing("graphs/charts/tables", {"render_mode": "gpt_image"})
    assert validate_figure_routing("graphs/charts/tables", None)


@pytest.mark.parametrize("content_type", ["customized", None, "unrecognized"])
@pytest.mark.parametrize(
    "chart_spec",
    [None, {"render_mode": "chart"}, {"render_mode": "gpt_image"}],
)
def test_validator_unconstrained_content_types_always_pass(
    content_type: str | None, chart_spec: dict | None
) -> None:
    """customized, None, and unknown content types have no routing constraint."""
    from src.common.figure_policy import validate_figure_routing

    assert validate_figure_routing(content_type, chart_spec) == []


def test_validator_accepts_conforming_math_exam_question() -> None:
    """A math ExamQuestion with an ImageSpec follows its declared type."""
    from src.common.figure_policy import validate_question_figure_routing
    from src.schemas import ExamQuestion, ImageSpec, LearningContentItem

    question = ExamQuestion(
        情境=["個人"],
        題型種類="單一題",
        題型="選擇題",
        數學思考=["形成"],
        學習內容=[LearningContentItem(編碼="N-7-1", 說明="整數")],
        題目=["下列何者正確？"],
        正確解題分析=["依題意判斷。"],
        題目內容類型="含圖片",
        chart_spec=ImageSpec(render_mode="gpt_image", description="示意圖"),
    )

    assert validate_question_figure_routing(question) == []


def test_validator_rejects_nonconforming_math_exam_question() -> None:
    """A math ExamQuestion reports a mismatched ImageSpec mode."""
    from src.common.figure_policy import validate_question_figure_routing
    from src.schemas import ExamQuestion, ImageSpec, LearningContentItem

    question = ExamQuestion(
        情境=["個人"],
        題型種類="單一題",
        題型="選擇題",
        數學思考=["形成"],
        學習內容=[LearningContentItem(編碼="N-7-1", 說明="整數")],
        題目=["下列何者正確？"],
        正確解題分析=["依題意判斷。"],
        題目內容類型="含圖片",
        chart_spec=ImageSpec(render_mode="chart", description="示意圖"),
    )

    assert validate_question_figure_routing(question)


def test_validator_accepts_conforming_social_studies_question_and_subquestion() -> None:
    """A social-studies question and subquestion can route their ImageSpecs."""
    from src.common.figure_policy import validate_question_figure_routing
    from src.social_studies.schemas import ExamQuestion, ImageSpec, SubQuestion

    subquestion = SubQuestion(
        序號=2,
        題型="選擇題",
        題目="請依圖片作答。",
        題目內容類型="含圖片",
        chart_spec=ImageSpec(render_mode="html", description="表單"),
    )
    question = ExamQuestion(
        情境=["公共"],
        題型種類="題組題",
        題型="選擇題",
        閱讀歷程=["擷取訊息"],
        文本形式="連續文本—敘事文",
        題目內容類型="含圖片",
        chart_spec=ImageSpec(render_mode="gpt_image", description="地圖"),
        subquestions=[subquestion],
    )

    assert validate_question_figure_routing(question) == []


def test_validator_names_nonconforming_social_studies_subquestion() -> None:
    """A social-studies subquestion violation names its 序號."""
    from src.common.figure_policy import validate_question_figure_routing
    from src.social_studies.schemas import ExamQuestion, ImageSpec, SubQuestion

    subquestion = SubQuestion(
        序號=2,
        題型="選擇題",
        題目="請依圖片作答。",
        題目內容類型="含圖片",
        chart_spec=ImageSpec(render_mode="chart", description="錯誤模式"),
    )
    question = ExamQuestion(
        情境=["公共"],
        題型種類="題組題",
        題型="選擇題",
        閱讀歷程=["擷取訊息"],
        文本形式="連續文本—敘事文",
        題目內容類型="含圖片",
        chart_spec=ImageSpec(render_mode="gpt_image", description="地圖"),
        subquestions=[subquestion],
    )

    violations = validate_question_figure_routing(question)
    assert violations
    assert any("小題 2" in violation for violation in violations)


def test_natural_sciences_subquestion_has_no_figure_fields() -> None:
    """Natural-sciences subquestions carry no per-subquestion figure fields."""
    from src.natural_sciences.schemas import SubQuestion

    assert "題目內容類型" not in SubQuestion.model_fields
    assert "chart_spec" not in SubQuestion.model_fields


def test_validator_accepts_conforming_natural_sciences_question_and_subquestion() -> None:
    """NS 小題 carry no per-小題 figure, so they contribute no violations."""
    from src.common.figure_policy import validate_question_figure_routing
    from src.natural_sciences.schemas import ExamQuestion, ImageSpec, SubQuestion

    subquestion = SubQuestion(
        序號=2,
        題型="Simple multiple-choice",
        題目="請依圖片作答。",
    )
    question = ExamQuestion(
        情境=["Personal"],
        題型種類="題組題",
        題型="Simple multiple-choice",
        題目內容類型="含圖片",
        chart_spec=ImageSpec(render_mode="gpt_image", description="實驗裝置"),
        subquestions=[subquestion],
    )

    assert validate_question_figure_routing(question) == []


def test_validator_names_nonconforming_natural_sciences_subquestion() -> None:
    """An NS top-level violation is not attributed to any 小題."""
    from src.common.figure_policy import validate_question_figure_routing
    from src.natural_sciences.schemas import ExamQuestion, ImageSpec, SubQuestion

    subquestion = SubQuestion(
        序號=2,
        題型="Simple multiple-choice",
        題目="請依圖片作答。",
    )
    question = ExamQuestion(
        情境=["Personal"],
        題型種類="題組題",
        題型="Simple multiple-choice",
        題目內容類型="graphs/charts/tables",
        chart_spec=ImageSpec(render_mode="gpt_image", description="實驗裝置"),
        subquestions=[subquestion],
    )

    violations = validate_question_figure_routing(question)
    assert violations
    assert all("小題" not in violation for violation in violations)


def test_validator_treats_dict_and_pydantic_chart_specs_identically() -> None:
    """Dict and Pydantic chart specs produce the same routing result."""
    from src.common.figure_policy import validate_figure_routing
    from src.schemas import ImageSpec

    pydantic_spec = ImageSpec(render_mode="html", description="表格")
    dict_spec = {"render_mode": "html", "description": "表格"}
    assert validate_figure_routing("含圖片", pydantic_spec) == validate_figure_routing(
        "含圖片", dict_spec
    )

    bad_pydantic_spec = ImageSpec(render_mode="chart", description="表格")
    bad_dict_spec = {"render_mode": "chart", "description": "表格"}
    assert validate_figure_routing("含圖片", bad_pydantic_spec) == validate_figure_routing(
        "含圖片", bad_dict_spec
    )


def test_validator_handles_missing_question_fields_without_raising() -> None:
    """A question-like object without routing fields is unconstrained."""
    from src.common.figure_policy import validate_question_figure_routing

    class EmptyQuestion:
        pass

    assert validate_question_figure_routing(EmptyQuestion()) == []


def test_instruction_render_modes_are_allowed_by_validator() -> None:
    """Every instruction render_mode fragment is accepted by its policy entry."""
    import re

    from src.common.figure_policy import allowed_render_modes

    for table in (MATH_CT, SS_CT, NS_CT):
        for content_type, instruction in table.items():
            allowed = allowed_render_modes(content_type)
            if allowed is None:
                continue
            modes = re.findall(r'render_mode:\s*"([^"]+)"', instruction)
            assert all(mode in allowed for mode in modes), (
                f"{content_type}: instruction modes {modes} exceed allowed {allowed}"
            )

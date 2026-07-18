# Fact-check Web-search Pass for 時事 Social-studies Questions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in fact-checking pass that uses the Anthropic native `web_search` server tool to validate 時事 (current-events) social-studies questions after the teacher verification pass, so a fabricated election result or UN resolution can no longer pass verification just because the passage was written by the same pipeline (GitHub issue #104).

**Architecture:** A new `LLMClient.generate_with_tools()` runs an Anthropic `messages.create` loop with `tools=[{"type":"web_search_20250305","name":"web_search","max_uses":N}]`. A new subject-scoped module `src/social_studies/fact_check.py` exposes `is_current_events(question)` (pure heuristic on 公民 學習內容 codes + 核心問題/文本 regex) and `fact_check_question(client, question) -> FactCheckResult` (single web-search-enabled call returning `{verified, citations, issues}` JSON). `src/social_studies/verifier.py::verify_question` calls the fact-checker only when the provider is enabled AND `is_current_events(question)` is true, and — when `fact_check.verified is False` — forces `passed=False` and appends the issues to `details` so the existing correction loop picks them up.

**Tech Stack:** Python 3.11+, Pydantic v2, `anthropic` SDK (`client.messages.create` with `tools=...`), pytest via `uv run pytest`.

**Spec:** `docs/superpowers/specs/2026-07-15-fact-check-web-search-design.md`

## Global Constraints

- Social studies only. Math and natural sciences are out of scope for this plan.
- Provider is Anthropic native `web_search_20250305` server tool. The issue's Tavily fallback is dropped.
- Config env vars: `WEB_SEARCH_PROVIDER` (values `"anthropic"` | `"none"`; default `"none"` — opt-in) and `WEB_SEARCH_MAX_USES` (integer; default `5`).
- Fact-check is **additive**: the teacher `verify_question` call runs unchanged first; fact-check runs after it only when the provider is enabled AND `is_current_events(question)` returns True.
- `is_current_events` is a pure function (no LLM call, no I/O) so it can be unit-tested with a static heuristic table.
- The 時事 heuristic is an OR of three signals: (a) any subquestion's 學習內容 編碼 starts with `"公"` (公民與社會 codes are the primary current-events surface in 108課綱 社會領域); (b) `核心問題` or `文本` matches the regex `近年|最近|今年|去年|本屆|現任|當前`; (c) a caller-supplied explicit flag.
- Fail-open: any tool-loop failure — provider `"none"`, tool not supported by the endpoint, exhausted `max_iterations`, malformed fact-check JSON — logs a warning and sets `fact_check=None`; the question passes / fails purely on the teacher verification result. A broken web search must never block generation.
- `fact_check.verified is False` (only when the fact-check pass actually ran and returned a definitive negative) forces `VerificationResult.passed=False` and appends `issues` to `details`. `fact_check=None` (skip / failure / not-time-sensitive) does NOT alter `passed` or `details`.
- `FactCheckResult` shape: `{verified: bool, citations: list[str], issues: list[str]}`. Citations are flattened to plain URL strings for the schema; the internal `Citation` object retains `url` + `title`.
- `generate_with_tools` signature: `generate_with_tools(system, user, tools, purpose, max_iterations=3) -> tuple[str, list[Citation]]`. It handles `stop_reason` values `"end_turn"`, `"pause_turn"` (continuation), and `"tool_use"` (server-side tools — no client-side execution required).
- The corrector is NOT modified; fact-check issues flow into it through the existing `verification.details` string, using the same minimal-targeted-fix contract as the teacher pass.

---

### Task 1: Add `WEB_SEARCH_PROVIDER` / `WEB_SEARCH_MAX_USES` to `Config`

**Files:**
- Modify: `src/config.py` (`Config` dataclass + `from_env`)
- Create: `tests/test_config_web_search.py`

**Interfaces:**
- Consumes: env vars `WEB_SEARCH_PROVIDER`, `WEB_SEARCH_MAX_USES`.
- Produces: `Config.web_search_provider: str` (default `"none"`), `Config.web_search_max_uses: int` (default `5`). Later tasks (`LLMClient.generate_with_tools`, `fact_check_question`, and the fact-check branch inside `verify_question`) read these fields.

- [ ] **Step 1: Write the failing test**

Create `tests/test_config_web_search.py`:

```python
"""Config surface for the web-search fact-check pass (issue #104)."""

from __future__ import annotations

import pytest

from src.config import Config


def test_defaults_disable_web_search() -> None:
    cfg = Config()
    assert cfg.web_search_provider == "none"
    assert cfg.web_search_max_uses == 5


def test_from_env_reads_web_search_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("WEB_SEARCH_PROVIDER", "anthropic")
    monkeypatch.setenv("WEB_SEARCH_MAX_USES", "7")
    cfg = Config.from_env()
    assert cfg.web_search_provider == "anthropic"
    assert cfg.web_search_max_uses == 7


def test_from_env_defaults_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.delenv("WEB_SEARCH_PROVIDER", raising=False)
    monkeypatch.delenv("WEB_SEARCH_MAX_USES", raising=False)
    cfg = Config.from_env()
    assert cfg.web_search_provider == "none"
    assert cfg.web_search_max_uses == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config_web_search.py -q`
Expected: FAIL with `AttributeError: 'Config' object has no attribute 'web_search_provider'`.

- [ ] **Step 3: Extend `Config` in `src/config.py`**

In `src/config.py`, add two fields to the `Config` dataclass (right after `log_truncate` on line 27):

```python
    web_search_provider: str = "none"  # "anthropic" | "none" (default: opt-in disabled)
    web_search_max_uses: int = 5
```

In `Config.from_env` (lines 37-52), append the following two arguments to the `cls(...)` kwargs (right before the closing paren):

```python
            web_search_provider=os.environ.get("WEB_SEARCH_PROVIDER", "none"),
            web_search_max_uses=int(os.environ.get("WEB_SEARCH_MAX_USES", "5")),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config_web_search.py -q`
Expected: PASS — 3 tests green.

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/test_config_web_search.py
git commit -m "feat(config): add WEB_SEARCH_PROVIDER / WEB_SEARCH_MAX_USES (#104)"
```

---

### Task 2: `FactCheckResult` schema and `VerificationResult.fact_check` field

**Files:**
- Modify: `src/social_studies/schemas.py` (add model, extend `VerificationResult`)
- Create: `tests/test_social_studies_fact_check_schemas.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `FactCheckResult(verified: bool, citations: list[str], issues: list[str])` — importable from `src.social_studies.schemas`.
  - `VerificationResult.fact_check: FactCheckResult | None = None` — new optional field, defaults to `None` so existing constructors and JSON payloads stay backward-compatible.

- [ ] **Step 1: Write the failing test**

Create `tests/test_social_studies_fact_check_schemas.py`:

```python
"""Schema surface for the fact-check pass (issue #104)."""

from __future__ import annotations

from src.social_studies.schemas import FactCheckResult, VerificationResult


def test_fact_check_result_defaults() -> None:
    result = FactCheckResult(verified=True)
    assert result.verified is True
    assert result.citations == []
    assert result.issues == []


def test_fact_check_result_carries_citations_and_issues() -> None:
    result = FactCheckResult(
        verified=False,
        citations=["https://example.org/a", "https://example.org/b"],
        issues=["文本聲稱2024年的選舉結果與公開紀錄不符。"],
    )
    assert result.verified is False
    assert result.citations == ["https://example.org/a", "https://example.org/b"]
    assert result.issues == ["文本聲稱2024年的選舉結果與公開紀錄不符。"]


def test_verification_result_fact_check_defaults_to_none() -> None:
    result = VerificationResult(
        passed=True,
        answer_match=True,
        details="通過。",
    )
    assert result.fact_check is None


def test_verification_result_carries_fact_check_payload() -> None:
    fc = FactCheckResult(
        verified=False,
        citations=["https://example.org/report"],
        issues=["文本引用的資料不存在。"],
    )
    result = VerificationResult(
        passed=False,
        answer_match=False,
        details="事實查證未通過：文本引用的資料不存在。",
        fact_check=fc,
    )
    assert result.fact_check is fc
    dumped = result.model_dump()
    assert dumped["fact_check"]["verified"] is False
    assert dumped["fact_check"]["citations"] == ["https://example.org/report"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_social_studies_fact_check_schemas.py -q`
Expected: FAIL with `ImportError: cannot import name 'FactCheckResult' from 'src.social_studies.schemas'`.

- [ ] **Step 3: Add `FactCheckResult` and extend `VerificationResult`**

In `src/social_studies/schemas.py`, add the new model directly after the `ChartVerificationResult` class (after line 35), before the existing `VerificationResult` class:

```python
class FactCheckResult(BaseModel):
    """Result of the web-search-backed fact-check pass (issue #104).

    `verified=True` means the checker found no contradiction between the
    question and the retrieved web sources. `verified=False` is a definitive
    negative — the verifier should force `passed=False`. Skips/failures use
    `VerificationResult.fact_check=None` instead of `verified=False`.
    """

    verified: bool
    citations: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
```

Update the `VerificationResult` class (currently lines 38-44) to add the new optional field:

```python
class VerificationResult(BaseModel):
    passed: bool
    answer_match: bool
    details: str
    my_answer: str = ""
    provided_answer: str = ""
    chart_verification: ChartVerificationResult | None = None
    fact_check: FactCheckResult | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_social_studies_fact_check_schemas.py -q`
Expected: PASS — 4 tests green.

- [ ] **Step 5: Regression check — existing SS verifier tests still pass**

Run: `uv run pytest tests/test_social_studies_verifier.py -q`
Expected: PASS — the pre-existing 3 tests still pass because `fact_check` defaults to `None`.

- [ ] **Step 6: Commit**

```bash
git add src/social_studies/schemas.py tests/test_social_studies_fact_check_schemas.py
git commit -m "feat(social-studies): add FactCheckResult + VerificationResult.fact_check (#104)"
```

---

### Task 3: `LLMClient.generate_with_tools` + `Citation` helper

**Files:**
- Modify: `src/llm_client.py` (add `Citation` dataclass + `generate_with_tools` method)
- Create: `tests/test_llm_client_generate_with_tools.py`

**Interfaces:**
- Consumes: `self.client.messages.create` (Anthropic SDK, already wired in `LLMClient.__init__`), `Config.rate_limit_delay`, `Config.model_execute`.
- Produces:
  - `Citation(url: str, title: str = "")` — Pydantic model exported from `src.llm_client`.
  - `LLMClient.generate_with_tools(system, user, tools, purpose="generate", max_iterations=3, model=None) -> tuple[str, list[Citation]]`. Called only by Task 4's `fact_check_question`. Returns the final assistant text (concatenated `text` blocks) and a de-duplicated list of `Citation` objects extracted from the text blocks' `citations` sub-blocks and from `web_search_tool_result` server blocks.

- [ ] **Step 1: Write the failing test**

Create `tests/test_llm_client_generate_with_tools.py`:

```python
"""Tests for LLMClient.generate_with_tools (issue #104, Anthropic web_search)."""

from __future__ import annotations

from types import SimpleNamespace

from src.config import Config
from src.llm_client import Citation, LLMClient


class _FakeMessagesAPI:
    """Records calls and replays scripted responses to messages.create."""

    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):  # noqa: ANN001 — mimic SDK signature
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _make_client(responses: list[object]) -> tuple[LLMClient, _FakeMessagesAPI]:
    cfg = Config(api_key="x")
    client = LLMClient(cfg)
    fake = _FakeMessagesAPI(responses)
    client.client = SimpleNamespace(messages=fake)
    return client, fake


def _text_block(text: str, citations: list[dict] | None = None):
    return SimpleNamespace(type="text", text=text, citations=citations or [])


def _web_search_result_block(url: str, title: str):
    result = SimpleNamespace(url=url, title=title)
    return SimpleNamespace(type="web_search_tool_result", content=[result])


def _response(stop_reason: str, blocks: list) -> object:
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=blocks,
        usage=SimpleNamespace(
            input_tokens=1,
            output_tokens=1,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        ),
    )


def test_generate_with_tools_end_turn_returns_text_and_citations() -> None:
    citation_dict = {"url": "https://example.org/a", "title": "Source A"}
    response = _response(
        "end_turn",
        [
            _web_search_result_block("https://example.org/a", "Source A"),
            _text_block("最終回覆", citations=[citation_dict]),
        ],
    )
    client, fake = _make_client([response])
    text, citations = client.generate_with_tools(
        system="sys",
        user="usr",
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
        purpose="fact_check",
    )
    assert text == "最終回覆"
    assert citations == [Citation(url="https://example.org/a", title="Source A")]
    assert len(fake.calls) == 1
    assert fake.calls[0]["tools"][0]["type"] == "web_search_20250305"


def test_generate_with_tools_handles_pause_turn_continuation() -> None:
    first = _response("pause_turn", [_text_block("查詢中…")])
    second = _response(
        "end_turn",
        [_text_block("完整答案", citations=[{"url": "https://example.org/b", "title": "B"}])],
    )
    client, fake = _make_client([first, second])
    text, citations = client.generate_with_tools(
        system="sys",
        user="usr",
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
        purpose="fact_check",
    )
    assert "完整答案" in text
    assert Citation(url="https://example.org/b", title="B") in citations
    assert len(fake.calls) == 2
    # Second call carries the assistant turn produced by the first response.
    assert fake.calls[1]["messages"][-1]["role"] == "assistant"


def test_generate_with_tools_stops_at_max_iterations() -> None:
    pause_forever = [
        _response("pause_turn", [_text_block(f"step {i}")]) for i in range(5)
    ]
    client, fake = _make_client(pause_forever)
    text, citations = client.generate_with_tools(
        system="sys",
        user="usr",
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
        purpose="fact_check",
        max_iterations=3,
    )
    assert len(fake.calls) == 3
    assert citations == []
    assert "step 0" in text  # Partial text is returned so callers can log it.


def test_generate_with_tools_deduplicates_citations_by_url() -> None:
    response = _response(
        "end_turn",
        [
            _text_block(
                "回覆",
                citations=[
                    {"url": "https://example.org/a", "title": "Source A"},
                    {"url": "https://example.org/a", "title": "Source A (dup)"},
                    {"url": "https://example.org/b", "title": "Source B"},
                ],
            ),
        ],
    )
    client, _ = _make_client([response])
    _, citations = client.generate_with_tools(
        system="sys",
        user="usr",
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
        purpose="fact_check",
    )
    urls = [c.url for c in citations]
    assert urls == ["https://example.org/a", "https://example.org/b"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_llm_client_generate_with_tools.py -q`
Expected: FAIL with `ImportError: cannot import name 'Citation' from 'src.llm_client'`.

- [ ] **Step 3: Implement `Citation` and `generate_with_tools`**

In `src/llm_client.py`, at the top of the file (after the `from openai import OpenAI` line on line 14), add:

```python
from pydantic import BaseModel
```

Then, immediately after the module-level `_PURPOSE_TO_AGENT` dict (after line 27), add:

```python
_PURPOSE_TO_AGENT["fact_check"] = "fact_checker"


class Citation(BaseModel):
    """A single web-search source cited by the model in its final response."""

    url: str
    title: str = ""
```

Inside the `LLMClient` class, after the existing `generate_image` method (after line 487), add the new method:

```python
    def generate_with_tools(
        self,
        system: str,
        user: str,
        tools: list[dict],
        purpose: str = "generate",
        max_iterations: int = 3,
        model: str | None = None,
    ) -> tuple[str, list[Citation]]:
        """Run an Anthropic ``messages.create`` loop with server-side tools.

        The Anthropic native ``web_search_20250305`` tool executes searches
        server-side, so this loop mainly handles ``pause_turn`` continuations
        and terminates on ``end_turn`` (or after ``max_iterations`` — treated
        as inconclusive; callers should fail-open). Returns the concatenated
        final text and a deduplicated list of :class:`Citation`.
        """
        if self.config.rate_limit_delay > 0:
            time.sleep(self.config.rate_limit_delay)
        call_model = model or self.config.model_execute
        agent = _PURPOSE_TO_AGENT.get(purpose, purpose)

        system_param = (
            [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
            if system else []
        )
        messages: list[dict] = [{"role": "user", "content": user}]
        collected_text: list[str] = []
        collected_citations: list[Citation] = []
        seen_urls: set[str] = set()

        def _record_citation(url: str, title: str = "") -> None:
            if not url or url in seen_urls:
                return
            seen_urls.add(url)
            collected_citations.append(Citation(url=url, title=title or ""))

        if self._observer:
            self._emit({
                "type": "llm_request",
                "purpose": purpose,
                "agent": agent,
                "model": call_model,
                "messages": [{"role": "system", "content": system}, *messages],
                "params": {"max_tokens": 8192, "temperature": 0.7, "tools": tools},
            })

        for iteration in range(max_iterations):
            response = self.client.messages.create(
                model=call_model,
                max_tokens=8192,
                temperature=0.7,
                system=system_param,
                messages=messages,  # type: ignore[arg-type]
                tools=tools,  # type: ignore[arg-type]
            )
            assistant_blocks: list = list(response.content)
            for block in assistant_blocks:
                btype = getattr(block, "type", None)
                if btype == "text":
                    collected_text.append(getattr(block, "text", "") or "")
                    for cit in getattr(block, "citations", None) or []:
                        _record_citation(
                            getattr(cit, "url", None) or (cit.get("url", "") if isinstance(cit, dict) else ""),
                            getattr(cit, "title", None) or (cit.get("title", "") if isinstance(cit, dict) else ""),
                        )
                elif btype == "web_search_tool_result":
                    for item in getattr(block, "content", None) or []:
                        _record_citation(
                            getattr(item, "url", "") or (item.get("url", "") if isinstance(item, dict) else ""),
                            getattr(item, "title", "") or (item.get("title", "") if isinstance(item, dict) else ""),
                        )

            stop_reason = getattr(response, "stop_reason", "end_turn")
            if stop_reason != "pause_turn":
                break
            # Continue the same turn: the assistant blocks are appended, and
            # the server executes any additional tool_use it produced.
            messages.append({"role": "assistant", "content": assistant_blocks})
            if iteration == max_iterations - 1:
                break

        final_text = "".join(collected_text)
        if self._observer:
            self._emit({
                "type": "llm_response",
                "purpose": purpose,
                "agent": agent,
                "model": call_model,
                "content": final_text,
                "reasoning": None,
                "usage": None,
            })
        return final_text, collected_citations
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_llm_client_generate_with_tools.py -q`
Expected: PASS — 4 tests green.

- [ ] **Step 5: Commit**

```bash
git add src/llm_client.py tests/test_llm_client_generate_with_tools.py
git commit -m "feat(llm-client): add generate_with_tools + Citation for web_search (#104)"
```

---

### Task 4: `src/social_studies/fact_check.py` — heuristic + fact-check call

**Files:**
- Create: `src/social_studies/fact_check.py`
- Create: `tests/test_social_studies_fact_check.py`

**Interfaces:**
- Consumes:
  - `Config.web_search_provider`, `Config.web_search_max_uses` (Task 1).
  - `FactCheckResult` from `src.social_studies.schemas` (Task 2).
  - `LLMClient.generate_with_tools`, `Citation` from `src.llm_client` (Task 3).
  - `extract_json` from `src.llm_client` for parsing the model's JSON envelope.
- Produces:
  - `is_current_events(question: ExamQuestion, *, explicit: bool = False) -> bool`.
  - `fact_check_question(client: LLMClient, question: ExamQuestion, *, provider: str, max_uses: int) -> FactCheckResult | None`. Returns `None` (fail-open) when `provider != "anthropic"`, the tool call raises, or the JSON envelope is malformed. Never raises.
  - Module-level constants: `_CURRENT_EVENTS_REGEX` (compiled) and `_CURRENT_EVENTS_LC_PREFIXES = ("公",)` used by `is_current_events`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_social_studies_fact_check.py`:

```python
"""Tests for src.social_studies.fact_check (issue #104)."""

from __future__ import annotations

import json
from typing import Any

from src.social_studies.fact_check import fact_check_question, is_current_events
from src.social_studies.schemas import (
    ExamQuestion,
    FactCheckResult,
    LearningContentRef,
    QuestionMetadata,
    SubQuestion,
)


def _question(
    *,
    core_question: str = "本題組核心問題。",
    passage: str = "本題組文本。",
    lc_codes: list[str] | None = None,
) -> ExamQuestion:
    codes = lc_codes or ["歷Ka-Ⅳ-1"]
    subqs = [
        SubQuestion(
            id="ss-test-01",
            序號=1,
            年級=8,
            科目=["歷史"],
            核心素養=[],
            學習內容=[LearningContentRef(編碼=c, 說明="") for c in codes],
            學習表現=[],
            出題概念="",
            題型="選擇題",
            題目="測試題目",
        )
    ]
    return ExamQuestion(
        id="ss-test",
        核心問題=core_question,
        文本=passage,
        subquestions=subqs,
        情境=["公共"],
        題型種類="題組題",
        題型="選擇題",
        閱讀歷程=["擷取訊息"],
        文本形式="連續文本—說明文",
        題目=[passage, "測試題目"],
        正確解題分析=["A"],
        metadata=QuestionMetadata(grade=8, model="fake-model"),
    )


def test_is_current_events_true_when_公民_learning_content_present() -> None:
    q = _question(lc_codes=["公Ba-Ⅳ-3"], core_question="說明地方治理原則。", passage="…")
    assert is_current_events(q) is True


def test_is_current_events_true_when_核心問題_matches_regex() -> None:
    q = _question(lc_codes=["歷Ka-Ⅳ-1"], core_question="近年來全球暖化對台灣有何衝擊？", passage="…")
    assert is_current_events(q) is True


def test_is_current_events_true_when_文本_matches_regex() -> None:
    q = _question(
        lc_codes=["歷Ka-Ⅳ-1"],
        core_question="工業革命的影響。",
        passage="根據今年公布的資料…",
    )
    assert is_current_events(q) is True


def test_is_current_events_true_when_explicit_flag() -> None:
    q = _question(lc_codes=["歷Ka-Ⅳ-1"], core_question="…", passage="…")
    assert is_current_events(q) is False
    assert is_current_events(q, explicit=True) is True


def test_is_current_events_false_for_non_time_sensitive_question() -> None:
    q = _question(
        lc_codes=["歷Ka-Ⅳ-1"],
        core_question="工業革命的重要性。",
        passage="十八世紀後半，蒸汽動力興起。",
    )
    assert is_current_events(q) is False


class _StubClient:
    """Records the last call and replays a scripted (text, citations) tuple."""

    def __init__(self, text: str = "", citations: list[dict] | None = None, raises: Exception | None = None) -> None:
        self._text = text
        self._citations = citations or []
        self._raises = raises
        self.last_tools: list[dict] | None = None
        self.last_purpose: str | None = None
        self.calls = 0

    def generate_with_tools(
        self,
        system: str,
        user: str,
        tools: list[dict],
        purpose: str = "generate",
        max_iterations: int = 3,
        model: str | None = None,
    ) -> tuple[str, list[Any]]:
        self.calls += 1
        self.last_tools = tools
        self.last_purpose = purpose
        if self._raises is not None:
            raise self._raises
        from src.llm_client import Citation
        cits = [Citation(url=c["url"], title=c.get("title", "")) for c in self._citations]
        return self._text, cits


def test_fact_check_question_returns_none_when_provider_disabled() -> None:
    client = _StubClient(text=json.dumps({"verified": False, "issues": ["x"]}))
    result = fact_check_question(
        client, _question(), provider="none", max_uses=5,
    )
    assert result is None
    assert client.calls == 0


def test_fact_check_question_returns_verified_result_on_success() -> None:
    payload = {
        "verified": False,
        "issues": ["文本聲稱2024年台北市長為某某，實際為另一人。"],
    }
    client = _StubClient(
        text=json.dumps(payload, ensure_ascii=False),
        citations=[
            {"url": "https://gov.tw/report", "title": "公開資料"},
            {"url": "https://news.example/2024", "title": "新聞報導"},
        ],
    )
    result = fact_check_question(
        client, _question(), provider="anthropic", max_uses=5,
    )
    assert isinstance(result, FactCheckResult)
    assert result.verified is False
    assert result.issues == ["文本聲稱2024年台北市長為某某，實際為另一人。"]
    assert result.citations == ["https://gov.tw/report", "https://news.example/2024"]
    assert client.last_purpose == "fact_check"
    assert client.last_tools is not None
    assert client.last_tools[0]["type"] == "web_search_20250305"
    assert client.last_tools[0]["max_uses"] == 5


def test_fact_check_question_fails_open_on_client_exception() -> None:
    client = _StubClient(raises=RuntimeError("boom"))
    result = fact_check_question(
        client, _question(), provider="anthropic", max_uses=5,
    )
    assert result is None


def test_fact_check_question_fails_open_on_malformed_json() -> None:
    client = _StubClient(text="not json at all")
    result = fact_check_question(
        client, _question(), provider="anthropic", max_uses=5,
    )
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_social_studies_fact_check.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.social_studies.fact_check'`.

- [ ] **Step 3: Write the module**

Create `src/social_studies/fact_check.py`:

```python
"""Web-search-backed fact-check pass for 時事 social-studies questions.

Additive to the teacher verification pass. See issue #104 and
`docs/superpowers/specs/2026-07-15-fact-check-web-search-design.md`.

The public surface is two pure/near-pure functions:

* :func:`is_current_events` — heuristic classifier, no I/O, no LLM.
* :func:`fact_check_question` — single ``generate_with_tools`` call with the
  Anthropic native ``web_search_20250305`` server tool. Fails open (returns
  ``None``) on any exception or malformed model output — a broken web search
  must never block generation.
"""

from __future__ import annotations

import logging
import re
from typing import Protocol

from src.llm_client import Citation, extract_json
from src.social_studies.schemas import ExamQuestion, FactCheckResult

logger = logging.getLogger(__name__)

# Regex signalling that the question depends on time-sensitive facts.
_CURRENT_EVENTS_REGEX = re.compile(r"近年|最近|今年|去年|本屆|現任|當前")

# 學習內容 編碼 prefixes whose subjects are the primary current-events surface
# in 108課綱 社會領域. 公民與社會 codes start with "公".
_CURRENT_EVENTS_LC_PREFIXES: tuple[str, ...] = ("公",)

_FACT_CHECK_SYSTEM_PROMPT = """\
你是一位協助審核108課綱社會領域考試題組的事實查證員。
你會收到題組的核心問題、文本素材與各小題敘述。請使用 web_search 查證文本中\
可能涉及時事、公開資料或近期事件的陳述是否屬實。

請以 JSON 格式回覆，且僅輸出 JSON：

```json
{
  "verified": true/false,
  "issues": ["若查得矛盾，逐條列出；若通過查證，回傳空陣列"]
}
```

判斷原則：
- 只有在網路資料明確與文本矛盾、或關鍵事實顯然錯誤，才回傳 verified=false。
- 若查無明確反例，或僅是措辭差異，請回傳 verified=true。
- 引用文獻由系統自動從 citation 塊中擷取，不需要在 JSON 中列出。
"""


class _ToolClient(Protocol):
    """Structural type for the subset of LLMClient we depend on."""

    def generate_with_tools(
        self,
        system: str,
        user: str,
        tools: list[dict],
        purpose: str = ...,
        max_iterations: int = ...,
        model: str | None = ...,
    ) -> tuple[str, list[Citation]]: ...


def is_current_events(question: ExamQuestion, *, explicit: bool = False) -> bool:
    """Return True when the question likely depends on time-sensitive facts.

    Signals (OR):
    * ``explicit=True`` supplied by the caller.
    * Any subquestion's 學習內容 編碼 starts with one of
      ``_CURRENT_EVENTS_LC_PREFIXES`` (public-affairs codes 公*).
    * ``核心問題`` or ``文本`` matches ``_CURRENT_EVENTS_REGEX``.
    """
    if explicit:
        return True
    for sub in question.subquestions or []:
        for ref in sub.學習內容 or []:
            code = (ref.編碼 or "").strip()
            if code.startswith(_CURRENT_EVENTS_LC_PREFIXES):
                return True
    haystack = f"{question.核心問題 or ''}\n{question.文本 or ''}"
    if _CURRENT_EVENTS_REGEX.search(haystack):
        return True
    return False


def _build_user_prompt(question: ExamQuestion) -> str:
    lines: list[str] = []
    lines.append("## 核心問題")
    lines.append(question.核心問題 or "（未提供）")
    lines.append("")
    lines.append("## 文本素材")
    lines.append(question.文本 or "（未提供）")
    lines.append("")
    if question.subquestions:
        lines.append("## 各小題敘述")
        for sub in question.subquestions:
            lines.append(f"### 小題 {sub.序號}")
            lines.append(sub.題目 or "")
            if sub.答案:
                lines.append(f"答案：{sub.答案}")
    lines.append("")
    lines.append("請依照系統指令進行查證，並僅輸出 JSON。")
    return "\n".join(lines)


def fact_check_question(
    client: _ToolClient,
    question: ExamQuestion,
    *,
    provider: str,
    max_uses: int,
) -> FactCheckResult | None:
    """Run the web-search fact-check pass. Fail-open.

    Returns ``None`` when the pass is skipped (provider disabled) or when any
    step fails (tool loop exhausts, endpoint rejects the tool, malformed JSON,
    unexpected exception). Otherwise returns a populated
    :class:`FactCheckResult` — including ``citations`` flattened to URL
    strings from the model's cited sources.
    """
    if provider != "anthropic":
        return None

    tools = [
        {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": int(max_uses),
        }
    ]
    user_prompt = _build_user_prompt(question)

    try:
        text, citations = client.generate_with_tools(
            system=_FACT_CHECK_SYSTEM_PROMPT,
            user=user_prompt,
            tools=tools,
            purpose="fact_check",
        )
    except Exception as exc:  # noqa: BLE001 — fail-open by design
        logger.warning("fact_check_question tool call failed: %s", exc)
        return None

    try:
        payload = extract_json(text)
    except Exception as exc:  # noqa: BLE001 — fail-open by design
        logger.warning("fact_check_question could not parse JSON envelope: %s", exc)
        return None

    verified_raw = payload.get("verified") if isinstance(payload, dict) else None
    if not isinstance(verified_raw, bool):
        logger.warning(
            "fact_check_question JSON missing boolean 'verified' field: %r", payload,
        )
        return None
    issues_raw = payload.get("issues") if isinstance(payload, dict) else []
    issues: list[str] = [str(x) for x in issues_raw] if isinstance(issues_raw, list) else []

    return FactCheckResult(
        verified=verified_raw,
        citations=[c.url for c in citations if getattr(c, "url", "")],
        issues=issues,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_social_studies_fact_check.py -q`
Expected: PASS — 9 tests green.

- [ ] **Step 5: Commit**

```bash
git add src/social_studies/fact_check.py tests/test_social_studies_fact_check.py
git commit -m "feat(social-studies): add is_current_events + fact_check_question (#104)"
```

---

### Task 5: Wire fact-check into `verify_question`

**Files:**
- Modify: `src/social_studies/verifier.py` (`verify_question` — add fact-check branch)
- Modify: `tests/test_social_studies_verifier.py` (extend `FakeClient` + add integration tests)

**Interfaces:**
- Consumes:
  - `Config.web_search_provider`, `Config.web_search_max_uses` (Task 1) — read from `client.config` inside `verify_question` (no new keyword argument, to avoid a breaking signature change in the CLI call sites).
  - `fact_check_question`, `is_current_events` from `src.social_studies.fact_check` (Task 4).
  - `FactCheckResult` from `src.social_studies.schemas` (Task 2).
- Produces: `verify_question` behaviour: when the provider is enabled AND `is_current_events(question)` is True, run the fact-check pass after the teacher pass, populate `result.fact_check`, and — when `fact_check.verified is False` — force `result.passed=False` and append issues to `result.details`. All other cases are unchanged.

- [ ] **Step 1: Write the failing tests — append to `tests/test_social_studies_verifier.py`**

Add these tests at the end of `tests/test_social_studies_verifier.py` (keep existing tests untouched):

```python
import types

from src.social_studies.schemas import (
    FactCheckResult,
    LearningContentRef,
    QuestionMetadata,
    SubQuestion,
)


def _question_with_公民_subquestion() -> "ExamQuestion":  # noqa: F821 — re-uses import
    return ExamQuestion(
        id="ss-fact-test",
        核心問題="說明近年地方治理趨勢。",
        文本="根據2024年公開資料…",
        subquestions=[
            SubQuestion(
                id="ss-fact-test-01",
                序號=1,
                年級=9,
                科目=["公民與社會"],
                核心素養=[],
                學習內容=[LearningContentRef(編碼="公Ba-Ⅳ-3", 說明="")],
                學習表現=[],
                題型="選擇題",
                題目="題幹",
                答案="A",
            )
        ],
        情境=["公共"],
        題型種類="題組題",
        題型="選擇題",
        閱讀歷程=["擷取訊息"],
        文本形式="連續文本—說明文",
        題目=["文本", "題幹"],
        正確解題分析=["A"],
        metadata=QuestionMetadata(grade=9, model="fake-model"),
    )


class FactCheckClient(FakeClient):
    """FakeClient with a configurable Config and fact_check hook."""

    def __init__(self, payload: dict, provider: str = "anthropic", max_uses: int = 5) -> None:
        super().__init__(payload)
        self.config = types.SimpleNamespace(
            web_search_provider=provider,
            web_search_max_uses=max_uses,
        )


def test_verify_skips_fact_check_when_provider_disabled(monkeypatch) -> None:
    called = {"n": 0}

    def _spy(*args, **kwargs):
        called["n"] += 1
        return FactCheckResult(verified=False, issues=["should not run"])

    monkeypatch.setattr("src.social_studies.verifier.fact_check_question", _spy)

    client = FactCheckClient(
        {
            "my_answer": "A",
            "provided_answer": "A",
            "answer_match": True,
            "passed": True,
            "details": "通過。",
        },
        provider="none",
    )
    result = verify_question(client, _question_with_公民_subquestion())
    assert result.passed is True
    assert result.fact_check is None
    assert called["n"] == 0


def test_verify_skips_fact_check_when_question_is_not_current_events(monkeypatch) -> None:
    called = {"n": 0}

    def _spy(*args, **kwargs):
        called["n"] += 1
        return None

    monkeypatch.setattr("src.social_studies.verifier.fact_check_question", _spy)

    client = FactCheckClient(
        {
            "my_answer": "A",
            "provided_answer": "A",
            "answer_match": True,
            "passed": True,
            "details": "通過。",
        },
        provider="anthropic",
    )
    result = verify_question(client, _question())  # non-時事 question from top of file
    assert result.fact_check is None
    assert called["n"] == 0


def test_verify_runs_fact_check_and_forces_fail_on_contradiction(monkeypatch) -> None:
    fake_result = FactCheckResult(
        verified=False,
        citations=["https://gov.tw/report"],
        issues=["文本聲稱2024年台北市長為某某，實際為另一人。"],
    )

    def _spy(client, question, *, provider, max_uses):
        assert provider == "anthropic"
        assert max_uses == 5
        return fake_result

    monkeypatch.setattr("src.social_studies.verifier.fact_check_question", _spy)

    client = FactCheckClient(
        {
            "my_answer": "A",
            "provided_answer": "A",
            "answer_match": True,
            "passed": True,
            "details": "教師端通過。",
        },
        provider="anthropic",
    )
    result = verify_question(client, _question_with_公民_subquestion())
    assert result.passed is False
    assert result.fact_check == fake_result
    assert "事實查證未通過" in result.details
    assert "文本聲稱2024年台北市長為某某" in result.details


def test_verify_keeps_pass_when_fact_check_verifies(monkeypatch) -> None:
    fake_result = FactCheckResult(verified=True, citations=["https://gov.tw/x"], issues=[])
    monkeypatch.setattr(
        "src.social_studies.verifier.fact_check_question",
        lambda *a, **kw: fake_result,
    )
    client = FactCheckClient(
        {
            "my_answer": "A",
            "provided_answer": "A",
            "answer_match": True,
            "passed": True,
            "details": "教師端通過。",
        },
        provider="anthropic",
    )
    result = verify_question(client, _question_with_公民_subquestion())
    assert result.passed is True
    assert result.fact_check == fake_result
    assert result.details == "教師端通過。"


def test_verify_leaves_details_untouched_when_fact_check_returns_none(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.social_studies.verifier.fact_check_question",
        lambda *a, **kw: None,
    )
    client = FactCheckClient(
        {
            "my_answer": "A",
            "provided_answer": "A",
            "answer_match": True,
            "passed": True,
            "details": "教師端通過。",
        },
        provider="anthropic",
    )
    result = verify_question(client, _question_with_公民_subquestion())
    assert result.passed is True
    assert result.fact_check is None
    assert result.details == "教師端通過。"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_social_studies_verifier.py -q`
Expected: FAIL — the new tests reference `src.social_studies.verifier.fact_check_question`, which does not exist yet in `verifier.py`.

- [ ] **Step 3: Wire fact-check into `verify_question`**

At the top of `src/social_studies/verifier.py`, extend the imports (line 7-9) so both the fact-check function and its result type are visible:

```python
from src.llm_client import LLMClient, extract_json
from src.social_studies.context_builder import _build_curriculum_section, _CONTENT_TEXT, _PERFORMANCE_TEXT, _PERFORMANCE_INTRO
from src.social_studies.fact_check import fact_check_question, is_current_events
from src.social_studies.schemas import (
    ChartVerificationResult,
    ExamQuestion,
    FactCheckResult,
    VerificationResult,
)
```

Replace the body of `verify_question` (currently lines 99-150) with the extended version:

```python
def verify_question(
    client: LLMClient,
    question: ExamQuestion,
    chart_image_path: str | None = None,
) -> VerificationResult:
    core_q, passage_text, subquestions_text = _build_question_text(question)
    if not subquestions_text:
        subquestions_text = "\n".join(question.題目)
    solution_text = "\n".join(question.正確解題分析)

    user_prompt = VERIFICATION_USER_TEMPLATE.format(
        core_question=core_q,
        passage_text=passage_text,
        subquestions_text=subquestions_text,
        solution_text=solution_text,
    )

    if chart_image_path is not None:
        user_prompt += (
            "\n\n## 附圖\n\n"
            "以下附上題目引用的素材圖片，請檢查素材內容與題目描述是否一致。"
        )

    try:
        raw = client.generate_with_image(
            VERIFICATION_SYSTEM_PROMPT, user_prompt, image_path=chart_image_path, purpose="verify"
        )
        result_json = extract_json(raw)

        chart_verif = None
        if "chart_verification" in result_json:
            cv = result_json["chart_verification"]
            chart_verif = ChartVerificationResult(
                chart_data_match=cv.get("chart_data_match", False),
                chart_labels_correct=cv.get("chart_labels_correct", False),
                chart_details=cv.get("chart_details", ""),
            )

        verification = VerificationResult(
            passed=result_json.get("passed", False),
            answer_match=result_json.get("answer_match", False),
            details=result_json.get("details", ""),
            my_answer=result_json.get("my_answer", ""),
            provided_answer=result_json.get("provided_answer", ""),
            chart_verification=chart_verif,
        )
    except (json.JSONDecodeError, ValueError, KeyError) as e:
        verification = VerificationResult(
            passed=False,
            answer_match=False,
            details=f"Verification failed to parse LLM response: {e}",
        )

    # Additive fact-check pass — only for 時事 questions when the provider is enabled.
    provider = getattr(getattr(client, "config", None), "web_search_provider", "none")
    max_uses = int(getattr(getattr(client, "config", None), "web_search_max_uses", 5))
    if provider == "anthropic" and is_current_events(question):
        fc = fact_check_question(
            client, question, provider=provider, max_uses=max_uses,
        )
        verification.fact_check = fc
        if fc is not None and fc.verified is False:
            joined_issues = "；".join(fc.issues) if fc.issues else "（未提供具體事項）"
            appended = f"事實查證未通過：{joined_issues}"
            verification.details = (
                f"{verification.details}\n\n{appended}" if verification.details else appended
            )
            verification.passed = False

    return verification
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_social_studies_verifier.py tests/test_social_studies_fact_check_schemas.py -q`
Expected: PASS — the 3 pre-existing verifier tests plus the 5 new integration tests plus the 4 schema tests all green.

- [ ] **Step 5: Regression check — full SS suite**

Run: `uv run pytest tests/test_social_studies_verifier.py tests/test_social_studies_context_builder.py tests/test_social_studies_corrector.py tests/test_social_studies_few_shot.py tests/test_social_studies_subquestion_images.py tests/test_social_studies_fact_check.py tests/test_social_studies_fact_check_schemas.py tests/test_llm_client_generate_with_tools.py tests/test_config_web_search.py -q`
Expected: PASS — all social-studies + new fact-check tests green. No regressions.

- [ ] **Step 6: Commit**

```bash
git add src/social_studies/verifier.py tests/test_social_studies_verifier.py
git commit -m "feat(social-studies): run fact-check pass after teacher verify for 時事 questions (#104)"
```

---

### Task 6: Documentation touch-up

**Files:**
- Modify: `CLAUDE.md` (project instructions — mention `WEB_SEARCH_PROVIDER` / `WEB_SEARCH_MAX_USES` and the fact-check pass)

**Interfaces:**
- Consumes: everything above.
- Produces: one paragraph documenting the new env vars and the additive fact-check pass so future contributors see it. No code changes.

- [ ] **Step 1: Add the fact-check paragraph to `CLAUDE.md`**

In `/workspace/exam-generation/CLAUDE.md`, add a new subsection immediately after the `### Verify + correct loop` block (search for the line beginning with `### Verify + correct loop` and insert **after** the `4. If \`passed=False\`` bullet):

```markdown
### Fact-check pass (social studies only)

Optional web-search fact-check runs after the teacher verify pass for
時事-flagged social-studies questions (issue #104). Enable by setting
`WEB_SEARCH_PROVIDER=anthropic` (default `none` — opt-in) and optionally
`WEB_SEARCH_MAX_USES=N` (default `5`). The pass uses the Anthropic native
`web_search_20250305` server tool via `LLMClient.generate_with_tools`. When
enabled, `src/social_studies/verifier.py::verify_question` calls
`src/social_studies/fact_check.py::fact_check_question` only when
`is_current_events(question)` is True (heuristic: any subquestion's 學習內容
編碼 starts with `公`, or `核心問題`/`文本` matches `近年|最近|今年|去年|本屆|
現任|當前`). A definitive negative (`fact_check.verified is False`) forces
`passed=False` and appends issues to `details` so the existing correction
loop sees them. Any failure — provider disabled, endpoint rejects the tool,
malformed JSON, exhausted iterations — fails open: `fact_check=None` and the
teacher verdict is unchanged.
```

- [ ] **Step 2: Verify the paragraph landed cleanly**

Run: `grep -n "Fact-check pass (social studies only)" /workspace/exam-generation/CLAUDE.md`
Expected: exactly one line matches.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: mention WEB_SEARCH_PROVIDER + fact-check pass in CLAUDE.md (#104)"
```

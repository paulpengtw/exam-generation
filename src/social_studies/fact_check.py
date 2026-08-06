"""Web-search-backed fact-check pass for 時事 social-studies questions.

Additive to the teacher verification pass. See issue #104 and
`docs/superpowers/specs/2026-07-15-fact-check-web-search-design.md`.

The public surface is two pure/near-pure functions:

* :func:`is_current_events` — heuristic classifier, no I/O, no LLM.
* :func:`fact_check_question` — provider-specific web-search call using either
  Anthropic's native ``web_search_20250305`` tool or Gemini grounding. Fails
  open (returns ``None``) on any exception or malformed model output — a broken
  web search must never block generation.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Protocol

from src.llm_client import Citation, extract_json, resolve_provider
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

    def generate_with_google_search(
        self,
        system: str,
        user: str,
        purpose: str = ...,
        max_uses: int = ...,
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
    on_error: Callable[[str], None] | None = None,
) -> FactCheckResult | None:
    """Run the web-search fact-check pass. Fail-open.

    Returns ``None`` when the pass is skipped (provider disabled or mismatched
    effective verify model) or when any step fails (tool loop exhausts, endpoint
    rejects the tool, malformed JSON, unexpected exception). Otherwise returns a populated
    :class:`FactCheckResult` — including ``citations`` flattened to URL
    strings from the model's cited sources.
    """
    if provider not in {"anthropic", "gemini"}:
        return None

    cfg = getattr(client, "config", None)
    effective_verify_model = (
        getattr(cfg, "model_verify", "") or getattr(cfg, "model_execute", "") or ""
    )
    if resolve_provider(effective_verify_model) != provider:
        logger.info(
            "fact_check skipped: effective verify model %r does not match provider %r",
            effective_verify_model,
            provider,
        )
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
        if provider == "anthropic":
            text, citations = client.generate_with_tools(
                system=_FACT_CHECK_SYSTEM_PROMPT,
                user=user_prompt,
                tools=tools,
                purpose="fact_check",
            )
        else:
            text, citations = client.generate_with_google_search(
                system=_FACT_CHECK_SYSTEM_PROMPT,
                user=user_prompt,
                purpose="fact_check",
                max_uses=max_uses,
            )
    except Exception as exc:  # noqa: BLE001 — fail-open by design
        msg = f"fact_check_question tool call failed: {exc}"
        logger.warning("fact_check_question tool call failed: %s", exc)
        if on_error is not None:
            on_error(msg)
        return None

    try:
        payload = extract_json(text)
    except Exception as exc:  # noqa: BLE001 — fail-open by design
        msg = f"fact_check_question could not parse JSON envelope: {exc}"
        logger.warning("fact_check_question could not parse JSON envelope: %s", exc)
        if on_error is not None:
            on_error(msg)
        return None

    verified_raw = payload.get("verified") if isinstance(payload, dict) else None
    if not isinstance(verified_raw, bool):
        msg = f"fact_check_question JSON missing boolean 'verified' field: {payload!r}"
        logger.warning(
            "fact_check_question JSON missing boolean 'verified' field: %r", payload,
        )
        if on_error is not None:
            on_error(msg)
        return None
    issues_raw = payload.get("issues") if isinstance(payload, dict) else []
    issues: list[str] = [str(x) for x in issues_raw] if isinstance(issues_raw, list) else []

    try:
        return FactCheckResult(
            verified=verified_raw,
            citations=[c.url for c in citations if getattr(c, "url", "")],
            issues=issues,
        )
    except Exception as exc:  # noqa: BLE001 — fail-open by design
        msg = f"fact_check_question could not construct FactCheckResult: {exc}"
        logger.warning("fact_check_question could not construct FactCheckResult: %s", exc)
        if on_error is not None:
            on_error(msg)
        return None

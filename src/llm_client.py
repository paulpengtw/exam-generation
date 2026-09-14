"""LLM client with Anthropic SDK and automatic prompt caching."""

from __future__ import annotations

import base64
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Callable, Literal

from anthropic import Anthropic
from openai import OpenAI
from pydantic import BaseModel

from src.config import Config

logger = logging.getLogger(__name__)

# Observer ids that have already emitted a failure warning (once-per-observer
# suppression — avoids log spam on repeated observer failures).
_warned_emit_stage_observers: set[int] = set()

# (provider, effort) pairs for which we have already emitted the "effort
# parameter dropped" warning — avoids log spam on repeated calls.
_warned_effort_drops: set[tuple[str, str]] = set()

# Exact model ids: proxy ids and models that already think by default are untouched.
_ADAPTIVE_THINKING_MODELS: frozenset[str] = frozenset({"claude-opus-4-6"})


def _anthropic_output_kwargs(model: str) -> dict:
    """Reserve output room for both adaptive thinking and the stage's JSON."""
    if model in _ADAPTIVE_THINKING_MODELS:
        return {"thinking": {"type": "adaptive"}, "max_tokens": 16384}
    return {"max_tokens": 8192}


_SAMPLING_REJECT_PREFIXES: tuple[str, ...] = (
    "claude-opus-5",
    "claude-sonnet-5",
    "claude-fable-5",
    "claude-opus-4-7",
    "claude-opus-4-8",
    # issue #340: gemini-3.x and OpenAI o-series / gpt-5.x reasoning models
    "gemini-3",
    "gpt-5",
    "o1",
    "o3",
    "o4",
)


def _accepts_sampling(model: str) -> bool:
    """Return False for models known to reject sampling parameters."""
    # Opus 4.6 rejects temperature while adaptive thinking is enabled.
    # Use the exact thinking roster so unrecognised proxy ids stay untouched.
    if model in _ADAPTIVE_THINKING_MODELS:
        return False
    for prefix in _SAMPLING_REJECT_PREFIXES:
        if model == prefix or model.startswith(prefix + "-") or model.startswith(prefix + "."):
            return False
    return True


def _max_tokens_kwargs(provider: str) -> dict:
    """Return the appropriate token-limit kwarg for the given provider.

    OpenAI's gpt-5.x / o-series reasoning models require ``max_completion_tokens``
    instead of ``max_tokens``.  All other providers (including Gemini's
    OpenAI-compat surface) accept the standard ``max_tokens`` key.
    """
    if provider == "openai":
        return {"max_completion_tokens": 8192}
    return {"max_tokens": 8192}


Provider = Literal["anthropic", "gemini", "openai"]
_OPENAI_O_SERIES_RE = re.compile(r"^o\d")

_PROVIDER_ENV: dict[str, tuple[str, str, str]] = {
    "gemini": ("gemini_api_key", "GEMINI_API_KEY", "gemini_base_url"),
    "openai": ("openai_api_key", "OPENAI_API_KEY", "openai_base_url"),
}


def resolve_provider(model: str) -> Provider:
    if model.startswith("gemini-"):
        return "gemini"
    if model.startswith("gpt-") or _OPENAI_O_SERIES_RE.match(model):
        return "openai"
    return "anthropic"


def _openai_usage_to_internal(u) -> dict:
    if u is None:
        return {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}
    details = getattr(u, "prompt_tokens_details", None)
    cached = getattr(details, "cached_tokens", None) or 0
    return {
        "input": u.prompt_tokens,
        "output": u.completion_tokens,
        "cache_read": cached,
        "cache_creation": 0,
    }


LLMObserver = Callable[[dict], None]

_PURPOSE_TO_AGENT: dict[str, str] = {
    "generate": "generator",
    "verify": "verifier",
    "correct": "corrector",
    "html_image": "image_agent",
    "gpt_image": "image_agent",
    "plan": "planner",
    "plan_core_questions": "planner",
    "plan_context_angles": "planner",
}
_PURPOSE_TO_AGENT["fact_check"] = "fact_checker"

# All purpose strings that belong to the planning tier (→ effort_plan).
_PLAN_PURPOSES: frozenset[str] = frozenset({"plan", "plan_core_questions", "plan_context_angles"})

# Purpose strings that belong to the 驗證 / 修正 model tiers (→ model_verify / model_correct).
# Exact-string sets, mirroring _PLAN_PURPOSES — see issue #346: a `purpose == "..."`
# equality check against a string no caller sends silently degrades to the execute tier.
_VERIFY_PURPOSES: frozenset[str] = frozenset({"verify", "fact_check"})
_CORRECT_PURPOSES: frozenset[str] = frozenset({"correct"})


class Citation(BaseModel):
    """A single web-search source cited by the model in its final response."""

    url: str
    title: str = ""


def _safe_field(obj: object, name: str, default: object | None = None) -> object | None:
    """Read a field from either a mapping or an SDK object without raising."""
    try:
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)
    except Exception:  # noqa: BLE001 — response metadata must never break fact-checking
        return default


def _first_field(obj: object, names: tuple[str, ...]) -> object | None:
    """Return the first non-None field value from a mapping or SDK object."""
    for name in names:
        value = _safe_field(obj, name)
        if value is not None:
            return value
    return None


def _first_item(value: object) -> object | None:
    """Return the first item from a likely sequence without assuming its type."""
    try:
        if isinstance(value, (list, tuple)):
            return value[0] if value else None
        if isinstance(value, (str, bytes, dict)) or value is None:
            return None
        return next(iter(value))
    except Exception:  # noqa: BLE001 — defensive response probing
        return None


def _entries(value: object) -> list[object]:
    """Normalize a grounding-chunk container for defensive iteration."""
    try:
        if isinstance(value, dict):
            return [value]
        if isinstance(value, (list, tuple)):
            return list(value)
        if isinstance(value, (str, bytes)) or value is None:
            return []
        return list(value)
    except Exception:  # noqa: BLE001 — defensive response probing
        return []


def _extract_google_search_citations(response: object) -> list[Citation]:
    """Extract and deduplicate Gemini grounding citations without trusting its shape.

    The Gemini OpenAI-compat grounding response shape is unverified against a live
    endpoint (issue #370); an empty citation list is an accepted outcome, not a
    failure.
    """
    citations: list[Citation] = []
    seen_urls: set[str] = set()
    try:
        model_extra = _safe_field(response, "model_extra")
        metadata_sources: list[object] = []
        sources: list[object] = []
        if model_extra is not None:
            sources.append(model_extra)
            root_metadata = _first_field(model_extra, ("groundingMetadata", "grounding_metadata"))
            if root_metadata is not None:
                metadata_sources.append(root_metadata)

        for candidate_source in (model_extra, response):
            candidates = _safe_field(candidate_source, "candidates")
            candidate = _first_item(candidates)
            if candidate is None:
                continue
            metadata = _first_field(candidate, ("groundingMetadata", "grounding_metadata"))
            if metadata is not None:
                metadata_sources.append(metadata)

        sources.extend(metadata_sources)
        for source in sources:
            chunks = _first_field(source, ("groundingChunks", "grounding_chunks"))
            for chunk in _entries(chunks):
                web = _safe_field(chunk, "web")
                url = _safe_field(web, "uri")
                if not isinstance(url, str) or not url or url in seen_urls:
                    continue
                title = _safe_field(web, "title", "")
                citations.append(Citation(url=url, title=title if isinstance(title, str) else ""))
                seen_urls.add(url)
    except Exception:  # noqa: BLE001 — citation extraction must never fail the pass
        return citations
    return citations


def emit_stage(
    observer: LLMObserver | None,
    agent: str,
    stage: str,
    status: str,
    **extra: object,
) -> None:
    """Emit a stage lifecycle event to the observer (if any)."""
    if observer is None:
        return
    event: dict = {
        "type": "stage", "agent": agent, "stage": stage, "status": status, "ts": time.time(),
    }
    event.update(extra)
    try:
        observer(event)
    except Exception as exc:
        obs_id = id(observer)
        if obs_id not in _warned_emit_stage_observers:
            _warned_emit_stage_observers.add(obs_id)
            print(
                f"[emit_stage] observer raised on event type 'stage': "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )


def make_render_error_sink(
    observer: LLMObserver | None,
    agent: str = "image_agent",
) -> tuple[Callable[[str], None], list[str]]:
    """Return an (on_error, failed) pair for use at render_image call sites.

    on_error(msg) emits a "render_image" error stage event and appends msg to
    failed.  Pass on_error to render_image(..., on_error=on_error); check
    ``if not failed`` before emitting the matching "end" event.

    Example::

        on_error, render_failed = make_render_error_sink(obs)
        emit_stage(obs, "image_agent", "render_image", "start")
        rendered = render_image(..., on_error=on_error)
        if not render_failed:
            emit_stage(obs, "image_agent", "render_image", "end")
    """
    failed: list[str] = []

    def on_error(err: str) -> None:
        emit_stage(observer, agent, "render_image", "error", message=err)
        failed.append(err)

    return on_error, failed


def emit_plan(observer: LLMObserver | None, sub_question_total: int) -> None:
    """Emit the resolved sub-question plan total to the observer (if any)."""
    if observer is None:
        return
    try:
        observer({
            "type": "plan",
            "agent": "generator",
            "sub_question_total": sub_question_total,
            "ts": time.time(),
        })
    except Exception:
        pass


def make_stderr_observer(truncate: int | None = None) -> LLMObserver:
    """Return an observer that prints LLM events to stderr."""
    _reasoning_started = [False]

    def observer(event: dict) -> None:
        t = event.get("type", "")

        if t == "llm_request":
            purpose = event.get("purpose", "")
            model = event.get("model", "")
            msgs = event.get("messages", [])
            total_chars = 0
            for m in msgs:
                c = m.get("content", "")
                if isinstance(c, str):
                    total_chars += len(c)
                elif isinstance(c, list):
                    for part in c:
                        if isinstance(part, dict) and part.get("type") == "text":
                            total_chars += len(part.get("text", ""))
            print(f"\n{'='*60}", file=sys.stderr)
            print(f"  LLM REQUEST [{purpose}] model={model} ~{total_chars} chars", file=sys.stderr)
            print(f"{'='*60}", file=sys.stderr)
            for msg in msgs:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if isinstance(content, list):
                    parts: list[str] = []
                    for part in content:
                        if isinstance(part, dict):
                            if part.get("type") == "text":
                                parts.append(part.get("text", ""))
                            elif part.get("type") == "image_url":
                                url = part.get("image_url", {}).get("url", "")
                                parts.append(f"[image len={len(url)}]")
                    content = "\n".join(parts)
                if truncate and len(content) > truncate:
                    tail = f"\n...(+{len(content) - truncate} chars truncated)"
                    content = content[:truncate] + tail
                print(f"\n--- {role} ---", file=sys.stderr)
                print(content, file=sys.stderr)
            print(f"{'='*60}", file=sys.stderr)
            _reasoning_started[0] = False

        elif t == "llm_reasoning_delta":
            text = event.get("text", "")
            if not _reasoning_started[0]:
                print("\n[thinking] ", end="", file=sys.stderr)
                _reasoning_started[0] = True
            print(text, end="", flush=True, file=sys.stderr)

        elif t == "llm_content_delta":
            print(event.get("text", ""), end="", flush=True, file=sys.stderr)

        elif t == "llm_response":
            usage = event.get("usage", {})
            purpose = event.get("purpose", "")
            print(f"\n{'='*60}", file=sys.stderr)
            print(f"  LLM RESPONSE [{purpose}] usage={usage}", file=sys.stderr)
            print(f"{'='*60}\n", file=sys.stderr)
            _reasoning_started[0] = False

    return observer


def _strip_v1(base_url: str) -> str:
    """Remove trailing /v1 so the Anthropic SDK can append its own versioned paths."""
    url = base_url.rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    return url


def _to_anthropic_content(content: str | list[dict]) -> str | list[dict]:
    """Convert OpenAI-style content blocks to Anthropic format."""
    if isinstance(content, str):
        return content
    result: list[dict] = []
    for part in content:
        if part.get("type") == "text":
            result.append({"type": "text", "text": part["text"]})
        elif part.get("type") == "image_url":
            url: str = part["image_url"]["url"]
            if url.startswith("data:"):
                header, data = url.split(",", 1)
                media_type = header.split(";")[0].replace("data:", "")
                result.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": data},
                })
    return result


class LLMClient:
    """Client for calling Claude via the Anthropic SDK with automatic prompt caching."""

    def __init__(self, config: Config):
        self.config = config
        self.client = Anthropic(
            api_key=config.api_key,
            base_url=_strip_v1(config.base_url),
        )
        self._image_client: OpenAI | None = None
        self._compat_clients: dict[str, OpenAI] = {}
        self._observer: LLMObserver | None = None
        self._observer_warned: bool = False

    def set_observer(self, cb: LLMObserver) -> None:
        self._observer = cb

    def clear_observer(self) -> None:
        self._observer = None

    def get_observer(self) -> LLMObserver | None:
        return self._observer

    def _emit(self, event: dict) -> None:
        if self._observer:
            try:
                self._observer(event)
            except Exception as exc:
                if not self._observer_warned:
                    self._observer_warned = True
                    event_type = event.get("type", "unknown")
                    print(
                        f"[LLMClient._emit] observer raised on event type {event_type!r}: "
                        f"{type(exc).__name__}: {exc}",
                        file=sys.stderr,
                    )

    def _summarize_for_observer(self, messages: list[dict]) -> list[dict]:
        """Replace image data URLs with size summaries to avoid huge SSE payloads."""
        result = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                new_parts: list[dict] = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        mime = (
                            url.split(";")[0].replace("data:", "")
                            if url.startswith("data:") else "unknown"
                        )
                        new_parts.append({
                            "type": "image_url",
                            "image_url": {"url": f"{mime}; len={len(url)}"},
                        })
                    else:
                        new_parts.append(part)
                result.append({"role": msg["role"], "content": new_parts})
            else:
                result.append(msg)
        return result

    def _temperature_kwargs(self, model: str) -> dict:
        """Return {'temperature': value} if configured and model accepts it, else {}."""
        t = self.config.temperature
        if t is None:
            return {}
        if _accepts_sampling(model):
            return {"temperature": t}
        logger.warning(
            "LLM_TEMPERATURE ignored for %s — model does not accept sampling params", model
        )
        return {}

    def _model_for_purpose(self, purpose: str) -> str:
        """Resolve the model tier for a call purpose: tier override → effective execute model.

        Resolution chain per tier (issue #374):
            env var (model_verify / model_correct) → effective execute model (resolved at
            call time, NOT at Config construction time, so per-request
            ``dataclasses.replace(cfg, model_execute=...)`` overrides land correctly).
        """
        if purpose in _VERIFY_PURPOSES:
            return self.config.model_verify or self.config.model_execute
        if purpose in _CORRECT_PURPOSES:
            return self.config.model_correct or self.config.model_execute
        return self.config.model_execute

    def _effort_for_purpose(self, purpose: str) -> str:
        """Resolve the effort tier for a call purpose: tier override → effort_execute.

        Resolution chain per tier (issue #377):
            plan purposes    → effort_plan
            verify purposes  → effort_verify or effort_execute (resolved at call time)
            correct purposes → effort_correct or effort_execute (resolved at call time)
            everything else  → effort_execute

        The ``or effort_execute`` fallback resolves at call time (NOT at Config
        construction time) so that per-request ``dataclasses.replace(cfg,
        effort_execute=...)`` overrides flow through to the tiers when their own
        effort is unset.
        """
        if purpose in _PLAN_PURPOSES:
            return self.config.effort_plan
        if purpose in _VERIFY_PURPOSES:
            return self.config.effort_verify or self.config.effort_execute
        if purpose in _CORRECT_PURPOSES:
            return self.config.effort_correct or self.config.effort_execute
        return self.config.effort_execute

    def _effort_kwargs(self, purpose: str, provider: str = "anthropic") -> dict:
        """Return effort kwargs appropriate for the provider and call purpose.

        Delegates tier selection to ``_effort_for_purpose`` (plan/verify/correct/execute).

        Anthropic: wraps effort in ``{"extra_body": {"output_config": {"effort": ...}}}``.
        gemini / openai: maps low/medium/high to ``{"reasoning_effort": effort}``.
            Any other effort value is unsupported on these providers — the parameter
            is omitted entirely and a WARNING is emitted once per (provider, effort)
            pair (module-level ``_warned_effort_drops`` suppresses repeats).

        Route-level validation (issue #377) ensures that the effective effort is
        compatible with the tier's model before any LLM call, so invalid values
        are caught upstream rather than being silently dropped here.
        """
        effort = self._effort_for_purpose(purpose)

        if provider == "anthropic":
            return {"extra_body": {"output_config": {"effort": effort}}}
        # gemini / openai — reasoning_effort only accepts low / medium / high
        if effort in ("low", "medium", "high"):
            return {"reasoning_effort": effort}
        key = (provider, effort)
        if key not in _warned_effort_drops:
            _warned_effort_drops.add(key)
            logger.warning(
                "reasoning_effort omitted for provider=%s effort=%r — "
                "value is not in ('low', 'medium', 'high'); parameter dropped",
                provider,
                effort,
            )
        return {}

    def _provider_options(self, model: str, purpose: str, provider: str) -> dict:
        """Resolve the provider options shared by dispatch and observation."""
        options = (
            _anthropic_output_kwargs(model)
            if provider == "anthropic"
            else _max_tokens_kwargs(provider)
        )
        options.update(self._temperature_kwargs(model))
        options.update(self._effort_kwargs(purpose, provider))
        return options

    def _openai_compat_client(self, provider: str) -> OpenAI:
        if provider in self._compat_clients:
            return self._compat_clients[provider]
        key_attr, env_name, url_attr = _PROVIDER_ENV[provider]
        api_key = getattr(self.config, key_attr)
        if not api_key:
            raise ValueError(f"{env_name} is required to call {provider} models.")
        base_url = getattr(self.config, url_attr)
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=self.config.llm_timeout_seconds)
        self._compat_clients[provider] = client
        return client

    def _generate_streaming(
        self,
        system: str,
        messages: list[dict],
        model: str,
        purpose: str,
        options: dict,
        agent_override: str | None = None,
    ) -> str:
        """Stream via Anthropic SDK, emitting deltas to observer. Returns assembled content."""
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        usage: dict = {}
        agent = (
            agent_override if agent_override is not None
            else _PURPOSE_TO_AGENT.get(purpose, purpose)
        )

        system_param = (
            [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
            if system else []
        )
        with self.client.messages.stream(
            model=model,
            **options,
            system=system_param,
            messages=messages,  # type: ignore[arg-type]
        ) as stream:
            for event in stream:
                if getattr(event, "type", None) == "content_block_delta":
                    delta = event.delta
                    dtype = getattr(delta, "type", None)
                    if dtype == "text_delta":
                        text = delta.text
                        content_parts.append(text)
                        self._emit({
                            "type": "llm_content_delta",
                            "purpose": purpose,
                            "agent": agent,
                            "text": text,
                        })
                    elif dtype == "thinking_delta":
                        thinking = delta.thinking
                        reasoning_parts.append(thinking)
                        self._emit({
                            "type": "llm_reasoning_delta",
                            "purpose": purpose,
                            "agent": agent,
                            "text": thinking,
                        })

            final = stream.get_final_message()
            u = final.usage
            usage = {
                "input": u.input_tokens,
                "output": u.output_tokens,
                "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
                "cache_creation": getattr(u, "cache_creation_input_tokens", 0) or 0,
            }

        content = "".join(content_parts)
        self._emit({
            "type": "llm_response",
            "purpose": purpose,
            "agent": agent,
            "model": model,
            "content": content,
            "reasoning": "".join(reasoning_parts) or None,
            "usage": usage,
        })
        return content

    def _call(
        self,
        messages: list[dict],
        model: str,
        purpose: str,
        agent_override: str | None = None,
    ) -> str:
        """Emit request event, dispatch to provider-specific call, emit response event."""
        agent = (
            agent_override if agent_override is not None
            else _PURPOSE_TO_AGENT.get(purpose, purpose)
        )

        provider = resolve_provider(model)
        options = self._provider_options(model, purpose, provider)
        if provider != "anthropic" and self._observer and self.config.llm_stream:
            options.update({
                "stream": True,
                "stream_options": {"include_usage": True},
            })
        if self._observer:
            self._emit({
                "type": "llm_request",
                "purpose": purpose,
                "agent": agent,
                "model": model,
                "messages": self._summarize_for_observer(messages),
                "params": dict(options),
            })

        if provider == "anthropic":
            return self._anthropic_call(
                messages, model, purpose, options, agent_override, agent
            )
        return self._openai_compat_call(provider, messages, model, purpose, options, agent)

    def _anthropic_call(
        self,
        messages: list[dict],
        model: str,
        purpose: str,
        options: dict,
        agent_override: str | None,
        agent: str,
    ) -> str:
        """Call the Anthropic API (streaming or non-streaming)."""
        system = ""
        user_messages_raw: list[dict] = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"] if isinstance(msg["content"], str) else ""
            else:
                user_messages_raw.append(msg)

        anthropic_messages = [
            {"role": msg["role"], "content": _to_anthropic_content(msg["content"])}
            for msg in user_messages_raw
        ]

        if self._observer and self.config.llm_stream:
            return self._generate_streaming(
                system, anthropic_messages, model, purpose, options, agent_override
            )

        system_param = (
            [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
            if system else []
        )
        response = self.client.messages.create(
            model=model,
            **options,
            system=system_param,
            messages=anthropic_messages,  # type: ignore[arg-type]
        )
        # Thinking (including redacted blocks) can precede the text response.
        content = "".join(getattr(block, "text", "") for block in response.content)
        if self._observer:
            u = response.usage
            self._emit({
                "type": "llm_response",
                "purpose": purpose,
                "agent": agent,
                "model": model,
                "content": content,
                "reasoning": "".join(
                    getattr(block, "thinking", "") for block in response.content
                ) or None,
                "usage": {
                    "input": u.input_tokens,
                    "output": u.output_tokens,
                    "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
                    "cache_creation": getattr(u, "cache_creation_input_tokens", 0) or 0,
                },
            })
        return content

    def _openai_compat_streaming(
        self,
        oc,
        kwargs: dict,
        model: str,
        purpose: str,
        agent: str,
    ) -> str:
        """Stream via OpenAI-compat surface, emitting deltas to observer.

        Returns assembled content.
        """
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        usage: dict = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0}

        stream = oc.chat.completions.create(**kwargs)
        for chunk in stream:
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                usage = _openai_usage_to_internal(chunk_usage)

            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue

            delta = choices[0].delta
            reasoning_text = (
                getattr(delta, "reasoning_content", None)
                or getattr(delta, "reasoning", None)
            )
            if reasoning_text:
                reasoning_parts.append(reasoning_text)
                self._emit({
                    "type": "llm_reasoning_delta",
                    "purpose": purpose,
                    "agent": agent,
                    "text": reasoning_text,
                })

            content_text = getattr(delta, "content", None)
            if content_text:
                content_parts.append(content_text)
                self._emit({
                    "type": "llm_content_delta",
                    "purpose": purpose,
                    "agent": agent,
                    "text": content_text,
                })

        content = "".join(content_parts)
        self._emit({
            "type": "llm_response",
            "purpose": purpose,
            "agent": agent,
            "model": model,
            "content": content,
            "reasoning": "".join(reasoning_parts) or None,
            "usage": usage,
        })
        return content

    def _openai_compat_call(
        self,
        provider: str,
        messages: list[dict],
        model: str,
        purpose: str,
        options: dict,
        agent: str,
    ) -> str:
        """Call through the OpenAI-compatible surface (gemini/openai providers).

        Builds a shared kwargs dict once and delegates to the streaming path when
        ``self._observer and self.config.llm_stream`` are both set; otherwise falls
        through to the non-streaming path.
        """
        oc = self._openai_compat_client(provider)
        kwargs: dict = {
            "model": model,
            "messages": messages,  # type: ignore[arg-type]
            **options,
        }

        if self._observer and self.config.llm_stream:
            return self._openai_compat_streaming(oc, kwargs, model, purpose, agent)

        response = oc.chat.completions.create(**kwargs)
        choices = response.choices if response.choices else []
        content = (choices[0].message.content or "") if choices else ""
        if self._observer:
            self._emit({
                "type": "llm_response",
                "purpose": purpose,
                "agent": agent,
                "model": model,
                "content": content,
                "reasoning": None,
                "usage": _openai_usage_to_internal(getattr(response, "usage", None)),
            })
        return content

    def generate(
        self,
        system: str,
        user: str,
        model: str | None = None,
        images: list[Path] | None = None,
        purpose: str = "generate",
    ) -> str:
        """Call the execution model (default: Sonnet) and return raw text response."""
        if self.config.rate_limit_delay > 0:
            time.sleep(self.config.rate_limit_delay)
        model = model or self._model_for_purpose(purpose)

        if images:
            user_content: list[dict] = [{"type": "text", "text": user}]
            for img_path in images:
                ext = Path(img_path).suffix.lower().lstrip(".")
                mime = "jpeg" if ext in ("jpg", "jpeg") else ext or "png"
                b64 = base64.b64encode(Path(img_path).read_bytes()).decode("utf-8")
                user_content.append(
                    {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{b64}"}}
                )
        else:
            user_content = user  # type: ignore[assignment]

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]
        return self._call(messages, model, purpose)

    def generate_with_image(
        self,
        system: str,
        user: str,
        image_path: str | Path | None = None,
        model: str | None = None,
        purpose: str = "generate",
    ) -> str:
        """Call the execution model with an optional image attachment."""
        if image_path is None:
            return self.generate(system, user, model, purpose=purpose)
        if self.config.rate_limit_delay > 0:
            time.sleep(self.config.rate_limit_delay)
        model = model or self._model_for_purpose(purpose)
        b64_data = base64.b64encode(Path(image_path).read_bytes()).decode("utf-8")
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "text", "text": user},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_data}"}},
            ]},
        ]
        return self._call(messages, model, purpose)

    def plan(self, system: str, user: str, purpose: str = "plan") -> str:
        """Call the planning model (default: Opus) and return raw text response."""
        return self.generate(system, user, model=self.config.model_plan, purpose=purpose)

    def generate_json(
        self,
        system: str,
        user: str,
        model: str | None = None,
        images: list[Path] | None = None,
        purpose: str = "generate",
        max_parse_retries: int = 2,
        agent_override: str | None = None,
    ) -> dict:
        """Call the execution model and parse the response as JSON."""
        last_err: Exception | None = None
        current_user = user
        for attempt in range(max_parse_retries):
            if self.config.rate_limit_delay > 0:
                time.sleep(self.config.rate_limit_delay)
            call_model = model or self._model_for_purpose(purpose)

            if images:
                user_content: list[dict] = [{"type": "text", "text": current_user}]
                for img_path in images:
                    ext = Path(img_path).suffix.lower().lstrip(".")
                    mime = "jpeg" if ext in ("jpg", "jpeg") else ext or "png"
                    b64 = base64.b64encode(Path(img_path).read_bytes()).decode("utf-8")
                    user_content.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/{mime};base64,{b64}"},
                        }
                    )
            else:
                user_content = current_user  # type: ignore[assignment]

            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ]
            raw = self._call(messages, call_model, purpose, agent_override)
            try:
                return extract_json(raw)
            except (ValueError, json.JSONDecodeError) as e:
                last_err = e
                self._emit({
                    "type": "llm_json_parse_retry",
                    "purpose": purpose,
                    "attempt": attempt + 1,
                    "error": str(e),
                })
                current_user = (
                    f"{user}\n\n"
                    f"[Previous response had invalid JSON: {e}. "
                    f"Return ONLY a valid JSON object, no prose or markdown.]"
                )
        raise last_err

    def generate_image(self, prompt: str, output_path: str | Path) -> str:
        """Generate a PNG image via OpenAI image API and write it to output_path."""
        if not self.config.image_api_key:
            raise ValueError("IMAGE_API_KEY is required for GPT image generation.")
        if self.config.rate_limit_delay > 0:
            time.sleep(self.config.rate_limit_delay)

        if self._image_client is None:
            self._image_client = OpenAI(
                api_key=self.config.image_api_key,
                base_url=self.config.image_base_url,
                timeout=self.config.image_timeout_seconds,
            )

        purpose = "gpt_image"
        self._emit({
            "type": "llm_request",
            "purpose": purpose,
            "agent": _PURPOSE_TO_AGENT[purpose],
            "model": self.config.image_model,
            "messages": [{"role": "user", "content": prompt}],
            "params": {"size": "1024x1024", "n": 1},
        })
        response = self._image_client.images.generate(
            model=self.config.image_model,
            prompt=prompt,
            size="1024x1024",
            n=1,
        )
        image_data = response.data[0]
        b64_json = getattr(image_data, "b64_json", None)
        if not b64_json:
            raise ValueError("Image generation response did not include b64_json data.")

        output = Path(output_path)
        output.write_bytes(base64.b64decode(b64_json))
        self._emit({
            "type": "llm_response",
            "purpose": purpose,
            "agent": _PURPOSE_TO_AGENT[purpose],
            "model": self.config.image_model,
            "content": str(output),
            "reasoning": None,
            "usage": None,
        })
        return str(output)

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
        call_model = model or self._model_for_purpose(purpose)
        agent = _PURPOSE_TO_AGENT.get(purpose, purpose)
        options = self._provider_options(call_model, purpose, "anthropic")
        options["tools"] = tools

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

        def _field(obj: object, name: str) -> str:
            if isinstance(obj, dict):
                return obj.get(name, "") or ""
            return getattr(obj, name, "") or ""

        if self._observer:
            self._emit({
                "type": "llm_request",
                "purpose": purpose,
                "agent": agent,
                "model": call_model,
                "messages": [{"role": "system", "content": system}, *messages],
                "params": dict(options),
            })

        for iteration in range(max_iterations):
            response = self.client.messages.create(
                model=call_model,
                **options,
                system=system_param,
                messages=messages,  # type: ignore[arg-type]
            )
            assistant_blocks: list = list(response.content)
            for block in assistant_blocks:
                btype = getattr(block, "type", None)
                if btype == "text":
                    collected_text.append(getattr(block, "text", "") or "")
                    for cit in getattr(block, "citations", None) or []:
                        _record_citation(_field(cit, "url"), _field(cit, "title"))
                elif btype == "web_search_tool_result":
                    for item in getattr(block, "content", None) or []:
                        _record_citation(_field(item, "url"), _field(item, "title"))

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

    def generate_with_google_search(
        self,
        system: str,
        user: str,
        purpose: str = "fact_check",
        max_uses: int = 5,
        model: str | None = None,
    ) -> tuple[str, list[Citation]]:
        """Call Gemini grounding through its OpenAI-compatible endpoint.

        ``max_uses`` is accepted for signature parity with
        :meth:`generate_with_tools`; Gemini has no equivalent limit, so it is
        intentionally ignored. Grounding citation metadata is best-effort and
        may produce an empty citation list when the endpoint omits it.
        """
        if self.config.rate_limit_delay > 0:
            time.sleep(self.config.rate_limit_delay)
        call_model = model or self._model_for_purpose(purpose)
        agent = _PURPOSE_TO_AGENT.get(purpose, purpose)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        extra_body = {"tools": [{"google_search": {}}]}
        options = self._provider_options(call_model, purpose, "gemini")
        options["extra_body"] = extra_body

        if self._observer:
            self._emit({
                "type": "llm_request",
                "purpose": purpose,
                "agent": agent,
                "model": call_model,
                "messages": messages,
                "params": dict(options),
            })

        oc = self._openai_compat_client("gemini")
        response = oc.chat.completions.create(
            model=call_model,
            messages=messages,
            **options,
        )
        content = response.choices[0].message.content or ""
        citations = _extract_google_search_citations(response)

        if self._observer:
            self._emit({
                "type": "llm_response",
                "purpose": purpose,
                "agent": agent,
                "model": call_model,
                "content": content,
                "reasoning": None,
                "usage": _openai_usage_to_internal(getattr(response, "usage", None)),
            })
        return content, citations


def _try_loads(text: str) -> dict:
    """Try json.loads; on failure, attempt repair via json_repair."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    try:
        from json_repair import repair_json
        repaired = repair_json(text, return_objects=True)
        if isinstance(repaired, (dict, list)):
            return repaired
    except Exception:
        pass
    return json.loads(text)  # re-raises original JSONDecodeError


def extract_json(text: str) -> dict:
    """Extract JSON from LLM response text, handling markdown code blocks."""
    code_block_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if code_block_match:
        return _try_loads(code_block_match.group(1))

    text = text.strip()
    if text.startswith("{") or text.startswith("["):
        return _try_loads(text)

    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        return _try_loads(brace_match.group(0))

    raise ValueError(f"Could not extract JSON from LLM response:\n{text[:500]}")

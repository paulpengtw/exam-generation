"""LLM client with Anthropic SDK and automatic prompt caching."""

from __future__ import annotations

import base64
import json
import re
import sys
import time
from pathlib import Path
from typing import Callable

from anthropic import Anthropic
from openai import OpenAI
from pydantic import BaseModel

from src.config import Config

LLMObserver = Callable[[dict], None]

_PURPOSE_TO_AGENT: dict[str, str] = {
    "generate": "generator",
    "verify": "verifier",
    "correct": "corrector",
    "html_image": "image_agent",
    "gpt_image": "image_agent",
    "plan": "planner",
}
_PURPOSE_TO_AGENT["fact_check"] = "fact_checker"


class Citation(BaseModel):
    """A single web-search source cited by the model in its final response."""

    url: str
    title: str = ""


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
    except Exception:
        pass


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
        self._observer: LLMObserver | None = None

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
            except Exception:
                pass

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

    def _generate_streaming(
        self,
        system: str,
        messages: list[dict],
        model: str,
        purpose: str,
        agent_override: str | None = None,
    ) -> str:
        """Stream via Anthropic SDK, emitting deltas to observer. Returns assembled content."""
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        usage: dict = {}
        agent = agent_override if agent_override is not None else _PURPOSE_TO_AGENT.get(purpose, purpose)

        system_param = (
            [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
            if system else []
        )
        with self.client.messages.stream(
            model=model,
            max_tokens=8192,
            temperature=0.7,
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
        """Emit request event, call Anthropic API (streaming or not), emit response event."""
        agent = agent_override if agent_override is not None else _PURPOSE_TO_AGENT.get(purpose, purpose)
        # Separate system message from user/assistant turns
        system = ""
        user_messages_raw: list[dict] = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"] if isinstance(msg["content"], str) else ""
            else:
                user_messages_raw.append(msg)

        if self._observer:
            self._emit({
                "type": "llm_request",
                "purpose": purpose,
                "agent": agent,
                "model": model,
                "messages": self._summarize_for_observer(messages),
                "params": {"max_tokens": 8192, "temperature": 0.7},
            })

        # Convert image format to Anthropic style
        anthropic_messages = [
            {"role": msg["role"], "content": _to_anthropic_content(msg["content"])}
            for msg in user_messages_raw
        ]

        if self._observer and self.config.llm_stream:
            return self._generate_streaming(system, anthropic_messages, model, purpose, agent_override)

        system_param = (
            [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
            if system else []
        )
        response = self.client.messages.create(
            model=model,
            max_tokens=8192,
            temperature=0.7,
            system=system_param,
            messages=anthropic_messages,  # type: ignore[arg-type]
        )
        content = response.content[0].text
        if self._observer:
            u = response.usage
            self._emit({
                "type": "llm_response",
                "purpose": purpose,
                "agent": agent,
                "model": model,
                "content": content,
                "reasoning": None,
                "usage": {
                    "input": u.input_tokens,
                    "output": u.output_tokens,
                    "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0,
                    "cache_creation": getattr(u, "cache_creation_input_tokens", 0) or 0,
                },
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
        model = model or self.config.model_execute

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
        model = model or self.config.model_execute
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
            call_model = model or self.config.model_execute

            if images:
                user_content: list[dict] = [{"type": "text", "text": current_user}]
                for img_path in images:
                    ext = Path(img_path).suffix.lower().lstrip(".")
                    mime = "jpeg" if ext in ("jpg", "jpeg") else ext or "png"
                    b64 = base64.b64encode(Path(img_path).read_bytes()).decode("utf-8")
                    user_content.append(
                        {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{b64}"}}
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

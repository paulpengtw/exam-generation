"""OpenAI-compatible LLM client with model routing."""

from __future__ import annotations

import base64
import json
import re
import sys
import time
from pathlib import Path
from typing import Callable

from openai import OpenAI

from src.config import Config

LLMObserver = Callable[[dict], None]


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
                    content = content[:truncate] + f"\n...(+{len(content) - truncate} chars truncated)"
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


class LLMClient:
    """Client for calling LLMs via OpenAI-compatible endpoints."""

    def __init__(self, config: Config):
        self.config = config
        self.client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        self._image_client: OpenAI | None = None
        self._observer: LLMObserver | None = None

    def set_observer(self, cb: LLMObserver) -> None:
        self._observer = cb

    def clear_observer(self) -> None:
        self._observer = None

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
                        mime = url.split(";")[0].replace("data:", "") if url.startswith("data:") else "unknown"
                        new_parts.append({"type": "image_url", "image_url": {"url": f"{mime}; len={len(url)}"}})
                    else:
                        new_parts.append(part)
                result.append({"role": msg["role"], "content": new_parts})
            else:
                result.append(msg)
        return result

    def _generate_streaming(self, messages: list[dict], model: str, purpose: str) -> str:
        """Stream response, emitting deltas to observer. Returns assembled content."""
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        usage: dict = {}

        stream = self.client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=8192,
            temperature=0.7,
            stream=True,
            stream_options={"include_usage": True},
        )

        for chunk in stream:
            if hasattr(chunk, "usage") and chunk.usage:
                usage = {
                    "input": chunk.usage.prompt_tokens,
                    "output": chunk.usage.completion_tokens,
                }
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            # Reasoning tokens: OpenAI/DeepSeek style
            reasoning_text = (
                getattr(delta, "reasoning_content", None)
                or getattr(delta, "reasoning", None)
            )
            # Anthropic thinking_delta via raw chunk (some shims expose this)
            if reasoning_text is None:
                raw_chunk = getattr(chunk, "model_extra", None) or {}
                if isinstance(raw_chunk, dict) and raw_chunk.get("type") == "content_block_delta":
                    inner = raw_chunk.get("delta", {})
                    if inner.get("type") == "thinking_delta":
                        reasoning_text = inner.get("thinking", "")
            if reasoning_text:
                reasoning_parts.append(reasoning_text)
                self._emit({"type": "llm_reasoning_delta", "text": reasoning_text})

            if delta.content:
                content_parts.append(delta.content)
                self._emit({"type": "llm_content_delta", "text": delta.content})

        content = "".join(content_parts)
        self._emit({
            "type": "llm_response",
            "purpose": purpose,
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
    ) -> str:
        """Emit request event, call API (streaming or not), emit response event."""
        if self._observer:
            self._emit({
                "type": "llm_request",
                "purpose": purpose,
                "model": model,
                "messages": self._summarize_for_observer(messages),
                "params": {"max_tokens": 8192, "temperature": 0.7},
            })

        if self._observer and self.config.llm_stream:
            return self._generate_streaming(messages, model, purpose)

        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=8192,
            temperature=0.7,
        )
        content = response.choices[0].message.content
        if self._observer:
            usage: dict = {}
            if response.usage:
                usage = {
                    "input": response.usage.prompt_tokens,
                    "output": response.usage.completion_tokens,
                }
            self._emit({
                "type": "llm_response",
                "purpose": purpose,
                "model": model,
                "content": content,
                "reasoning": None,
                "usage": usage,
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
    ) -> dict:
        """Call the execution model and parse the response as JSON."""
        raw = self.generate(system, user, model, images=images, purpose=purpose)
        return extract_json(raw)

    def generate_image(self, prompt: str, output_path: str | Path) -> str:
        """Generate a PNG image and write it to output_path."""
        if not self.config.image_api_key:
            raise ValueError("IMAGE_API_KEY is required for GPT image generation.")
        if self.config.rate_limit_delay > 0:
            time.sleep(self.config.rate_limit_delay)

        if self._image_client is None:
            self._image_client = OpenAI(
                api_key=self.config.image_api_key,
                base_url=self.config.image_base_url,
            )

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
        return str(output)


def extract_json(text: str) -> dict:
    """Extract JSON from LLM response text, handling markdown code blocks."""
    code_block_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if code_block_match:
        return json.loads(code_block_match.group(1))

    text = text.strip()
    if text.startswith("{") or text.startswith("["):
        return json.loads(text)

    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        return json.loads(brace_match.group(0))

    raise ValueError(f"Could not extract JSON from LLM response:\n{text[:500]}")

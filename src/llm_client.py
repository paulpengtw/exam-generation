"""OpenAI-compatible LLM client with model routing."""

from __future__ import annotations

import json
import re

from openai import OpenAI

from src.config import Config


class LLMClient:
    """Client for calling LLMs via OpenAI-compatible endpoints."""

    def __init__(self, config: Config):
        self.config = config
        self.client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )

    def generate(self, system: str, user: str, model: str | None = None) -> str:
        """Call the execution model (default: Sonnet) and return raw text response."""
        model = model or self.config.model_execute
        response = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=8192,
            temperature=0.7,
        )
        return response.choices[0].message.content

    def plan(self, system: str, user: str) -> str:
        """Call the planning model (default: Opus) and return raw text response."""
        return self.generate(system, user, model=self.config.model_plan)

    def generate_json(self, system: str, user: str, model: str | None = None) -> dict:
        """Call the execution model and parse the response as JSON."""
        raw = self.generate(system, user, model)
        return extract_json(raw)


def extract_json(text: str) -> dict:
    """Extract JSON from LLM response text, handling markdown code blocks."""
    # Try to find JSON in code blocks first
    code_block_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if code_block_match:
        return json.loads(code_block_match.group(1))

    # Try parsing the whole text as JSON
    text = text.strip()
    if text.startswith("{") or text.startswith("["):
        return json.loads(text)

    # Try to find the first { ... } block
    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        return json.loads(brace_match.group(0))

    raise ValueError(f"Could not extract JSON from LLM response:\n{text[:500]}")

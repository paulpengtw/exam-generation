"""Probe whether the configured LLM endpoint actually streams tokens.

Usage:
    uv run python scripts/probe_stream.py

Prints received event types; exits 0 if at least one llm_content_delta arrived,
exits 1 if streaming appears broken (only llm_response with no deltas).
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.config import Config
from src.llm_client import LLMClient

events: list[dict] = []

def observer(event: dict) -> None:
    t = event.get("type", "")
    if t == "llm_request":
        print(f"[request] purpose={event.get('purpose')} model={event.get('model')}")
    elif t == "llm_content_delta":
        print(f"[content_delta] {repr(event.get('text', '')[:40])}", end="", flush=True)
    elif t == "llm_reasoning_delta":
        print(f"[reasoning_delta] {repr(event.get('text', '')[:40])}", end="", flush=True)
    elif t == "llm_response":
        print(f"\n[response] usage={event.get('usage')}")
    events.append(event)

config = Config.from_env()
config.validate()

client = LLMClient(config)
client.set_observer(observer)

print(f"Probing streaming at {config.base_url} with model {config.model_execute}...")
client.generate(
    system="You are a helpful assistant.",
    user="Count from 1 to 5, one number per line.",
    purpose="generate",
)

deltas = [e for e in events if e.get("type") == "llm_content_delta"]
if deltas:
    print(f"\n✓ Streaming works: received {len(deltas)} content delta(s).")
    sys.exit(0)
else:
    print("\n✗ No content deltas received — provider may not stream or LLM_STREAM=0.")
    sys.exit(1)

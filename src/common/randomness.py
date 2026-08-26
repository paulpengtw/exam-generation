"""Deterministic keyed random streams used by subject samplers."""

from __future__ import annotations

import hashlib
import random


def draw_rng(seed: int | str | None, field_path: str, counter: int = 0) -> random.Random:
    """Return the deterministic RNG for one request field draw.

    Seeded streams are keyed by ``(seed, field_path, counter)`` using SHA-256,
    never Python's process-salted ``hash()``.  Field paths use the serialized
    parameter names: top-level fields are dotted-free (for example ``題型`` or
    ``學習內容``), while per-小題 fields use indexed dotted paths such as
    ``subquestion_configs[2].question_type``.  A child field keeps its own
    path and is drawn only after its resolved parent has determined its pool.

    ``None`` preserves the existing unseeded behavior by returning an
    independent system-seeded ``random.Random`` instance.
    """
    if seed is None:
        return random.Random()

    material = f"{seed}\x00{field_path}\x00{counter}".encode("utf-8")
    stream_seed = int.from_bytes(hashlib.sha256(material).digest(), "big")
    return random.Random(stream_seed)

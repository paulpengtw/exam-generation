"""Batch-level coverage planning for balanced social-studies generation (#112).

Used only when the request has `count > 1` and `coverage_mode == "balanced"`.
Pre-plans a length-`count` 題型 assignment list by round-robin over a shuffled
pool (order-shuffled afterwards so the resulting batch isn't sorted by type),
plus a stratified sequence of 學習內容 draws that spreads across distinct
codes before repeating any.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from typing import Generic, TypeVar

Q = TypeVar("Q")


class BatchSampler(Generic[Q]):
    """Pre-plan balanced per-question assignments across a whole batch."""

    def __init__(
        self,
        count: int,
        q_type_pool: Sequence[Q],
        learning_content_pool: Sequence[str],
        rng: random.Random,
    ) -> None:
        if count < 1:
            raise ValueError("count must be >= 1")
        self.count = count
        self._rng = rng
        self.q_type_assignments: list[Q] = self._plan_q_types(list(q_type_pool))
        self.learning_content_assignments: list[list[str]] = (
            self._plan_learning_content(list(learning_content_pool))
        )

    # ---- 題型 ----------------------------------------------------------------

    def _plan_q_types(self, pool: list[Q]) -> list[Q]:
        """Round-robin over a shuffled pool, then shuffle the resulting order."""
        if not pool:
            raise ValueError("q_type_pool must not be empty")
        shuffled_pool = pool[:]
        self._rng.shuffle(shuffled_pool)
        # Round-robin fill: assignments[i] = shuffled_pool[i % |pool|].
        # For count >= |pool|, this guarantees every type appears
        # floor(count/|pool|) or floor(count/|pool|) + 1 times.
        assignments = [shuffled_pool[i % len(shuffled_pool)] for i in range(self.count)]
        self._rng.shuffle(assignments)
        return assignments

    # ---- 學習內容 ------------------------------------------------------------

    def _plan_learning_content(self, pool: list[str]) -> list[list[str]]:
        """Draw one code per question without replacement until the pool is
        exhausted, then reshuffle and repeat. Each question receives a length-1
        list (the primary code) — callers that want a multi-code pool can
        extend with additional codes; v1 keeps each question narrowly focused
        so batch coverage remains observable.
        """
        if not pool:
            return [[] for _ in range(self.count)]
        assignments: list[list[str]] = []
        cursor = pool[:]
        self._rng.shuffle(cursor)
        idx = 0
        for _ in range(self.count):
            if idx >= len(cursor):
                cursor = pool[:]
                self._rng.shuffle(cursor)
                idx = 0
            assignments.append([cursor[idx]])
            idx += 1
        return assignments

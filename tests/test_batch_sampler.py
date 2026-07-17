"""Tests for BatchSampler (issue #112 balanced coverage)."""

from __future__ import annotations

import random

from src.batch_sampler import BatchSampler


def test_pool_ge_count_all_distinct() -> None:
    # 5 questions from a 6-item pool -> 5 distinct assignments.
    bs = BatchSampler(
        count=5,
        q_type_pool=["A", "B", "C", "D", "E", "F"],
        learning_content_pool=["lc-1", "lc-2", "lc-3"],
        rng=random.Random(0),
    )
    assert len(bs.q_type_assignments) == 5
    assert len(set(bs.q_type_assignments)) == 5


def test_pool_lt_count_round_robin_within_one() -> None:
    # 6 questions over a 3-type pool -> each type appears exactly twice.
    bs = BatchSampler(
        count=6,
        q_type_pool=["A", "B", "C"],
        learning_content_pool=["lc-1"],
        rng=random.Random(0),
    )
    counts = {t: bs.q_type_assignments.count(t) for t in ["A", "B", "C"]}
    assert counts == {"A": 2, "B": 2, "C": 2}


def test_pool_lt_count_uneven_within_one() -> None:
    # 5 over 4-type pool -> 4 distinct types + 1 repeat, so counts in {1, 2}.
    bs = BatchSampler(
        count=5,
        q_type_pool=["A", "B", "C", "D"],
        learning_content_pool=["lc-1"],
        rng=random.Random(0),
    )
    counts = sorted(
        [bs.q_type_assignments.count(t) for t in ["A", "B", "C", "D"]]
    )
    assert counts == [1, 1, 1, 2]
    # Each of 4 types must appear at least once.
    assert set(bs.q_type_assignments) == {"A", "B", "C", "D"}


def test_deterministic_under_fixed_seed() -> None:
    bs1 = BatchSampler(
        count=5,
        q_type_pool=["A", "B", "C", "D"],
        learning_content_pool=["lc-1", "lc-2", "lc-3", "lc-4"],
        rng=random.Random(42),
    )
    bs2 = BatchSampler(
        count=5,
        q_type_pool=["A", "B", "C", "D"],
        learning_content_pool=["lc-1", "lc-2", "lc-3", "lc-4"],
        rng=random.Random(42),
    )
    assert bs1.q_type_assignments == bs2.q_type_assignments
    assert bs1.learning_content_assignments == bs2.learning_content_assignments


def test_assignment_order_shuffled_not_sorted_by_type() -> None:
    # With a 4-type pool and count=8 (two full cycles), a deterministic
    # round-robin without an order shuffle would be [A,B,C,D,A,B,C,D];
    # BatchSampler must break that pattern for at least one seed.
    saw_break = False
    for seed in range(20):
        bs = BatchSampler(
            count=8,
            q_type_pool=["A", "B", "C", "D"],
            learning_content_pool=["lc-1"],
            rng=random.Random(seed),
        )
        if bs.q_type_assignments != ["A", "B", "C", "D", "A", "B", "C", "D"]:
            saw_break = True
            break
    assert saw_break


def test_learning_content_stratified_before_repeat() -> None:
    # 4 questions over a 4-code pool -> every code appears exactly once
    # in the union of the four per-question assignments (each of which is
    # a length-1..3 list).
    bs = BatchSampler(
        count=4,
        q_type_pool=["A"],
        learning_content_pool=["lc-1", "lc-2", "lc-3", "lc-4"],
        rng=random.Random(7),
    )
    used = [code for lst in bs.learning_content_assignments for code in lst]
    # The first 4 codes drawn (one per question, in order) must be a
    # permutation of the pool — sampling without replacement across the batch.
    firsts = [lst[0] for lst in bs.learning_content_assignments]
    assert sorted(firsts) == ["lc-1", "lc-2", "lc-3", "lc-4"]
    assert set(used) == {"lc-1", "lc-2", "lc-3", "lc-4"}


def test_empty_learning_content_pool_yields_empty_lists() -> None:
    bs = BatchSampler(
        count=3,
        q_type_pool=["A", "B"],
        learning_content_pool=[],
        rng=random.Random(0),
    )
    assert bs.learning_content_assignments == [[], [], []]

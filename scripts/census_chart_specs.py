"""Chart-spec census over production/staging generation records (issue #110).

Collects the Phase A gate evidence required by docs/figure-rendering-policy.md:
per-subject question counts and chart_spec category / render_mode distributions,
read from the ``generation_records`` table (per-user history, server/models.py).
The gate is MET when every subject in GATE_SUBJECTS has >= --min-per-subject
questions recorded.

Run (aiosqlite dev DB by default; point DATABASE_URL at staging/production):
    uv run python scripts/census_chart_specs.py
    DATABASE_URL=postgresql+asyncpg://... uv run python scripts/census_chart_specs.py --check
"""

from __future__ import annotations

import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.analyze_chart_spec_coverage import classify_spec, iter_item_specs  # noqa: E402

GATE_SUBJECTS = ("math", "social_studies", "natural_sciences")
DEFAULT_MIN_PER_SUBJECT = 30


@dataclass
class SubjectCensus:
    """Aggregated chart_spec statistics for one subject."""

    questions: int = 0
    questions_with_spec: int = 0
    specs_by_category: Counter = field(default_factory=Counter)
    specs_by_render_mode: Counter = field(default_factory=Counter)


@dataclass
class CensusResult:
    per_subject: dict[str, SubjectCensus]
    min_per_subject: int

    @property
    def gate_met(self) -> bool:
        return all(
            self.per_subject.get(s, SubjectCensus()).questions >= self.min_per_subject
            for s in GATE_SUBJECTS
        )


def summarize_census(
    rows: list[tuple[str, dict]],
    min_per_subject: int = DEFAULT_MIN_PER_SUBJECT,
) -> CensusResult:
    """Aggregate (subject, question_json) rows into per-subject census stats."""
    per_subject: dict[str, SubjectCensus] = {}
    for subject, item in rows:
        census = per_subject.setdefault(subject, SubjectCensus())
        census.questions += 1
        specs = list(iter_item_specs(item)) if isinstance(item, dict) else []
        if specs:
            census.questions_with_spec += 1
        for spec in specs:
            census.specs_by_category[classify_spec(spec)] += 1
            mode = (spec.get("render_mode") or "").lower() or "(missing)"
            census.specs_by_render_mode[mode] += 1
    return CensusResult(per_subject=per_subject, min_per_subject=min_per_subject)


def render_census_markdown(result: CensusResult) -> str:
    """Render the census as Markdown ready to paste into figure-rendering-evaluation.md."""
    n = result.min_per_subject
    lines = [
        "# chart_spec census (issue #110 gate evidence)",
        "",
        f"| subject | questions | with chart_spec | chart | table | geometry "
        f"| scenario_card | other | gate (>= {n}) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for subject in sorted(set(result.per_subject) | set(GATE_SUBJECTS)):
        c = result.per_subject.get(subject, SubjectCensus())
        gate = "MET" if c.questions >= n else "NOT MET"
        cat = c.specs_by_category
        lines.append(
            f"| {subject} | {c.questions} | {c.questions_with_spec} | {cat.get('chart', 0)} "
            f"| {cat.get('table', 0)} | {cat.get('geometry', 0)} "
            f"| {cat.get('scenario_card', 0)} | {cat.get('other', 0)} | {gate} |"
        )
    lines += ["", "## render_mode distribution", "", "| subject | render_mode | count |",
              "| --- | --- | --- |"]
    for subject in sorted(result.per_subject):
        for mode, count in sorted(result.per_subject[subject].specs_by_render_mode.items()):
            lines.append(f"| {subject} | {mode} | {count} |")
    verdict = "MET" if result.gate_met else "NOT MET"
    lines += [
        "",
        f"**GATE {verdict}** — requires >= {n} questions per subject "
        f"for {', '.join(GATE_SUBJECTS)}.",
    ]
    return "\n".join(lines)

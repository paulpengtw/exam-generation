"""Property test for src.common.resolver across all three subjects (#838).

Guards the whole class of 從屬參數-narrowing bug fixed by #833-#837: a fixed-seed
``random.Random`` generator builds payloads for math, social studies, and natural
sciences (count 1-3; blank or sampled valid subject-specific 科目 / 內容領域 /
情境 / 情境子類別 inputs; multi-valued only where the request contract allows a
list -- 內容領域 stays scalar; random 釘選 學習內容/學習表現 codes drawn from the
real curriculum pools at request, per-question ("問題"), and per-小題 level;
random 重抽 counters).

For every generated payload, exactly one of the following must hold:

* ``resolve`` succeeds, and resolving its own result again returns an
  identical payload with empty ``drawn`` and ``cleared`` (idempotence); or
* ``resolve`` raises ``ResolveConflictError`` whose every error carries a
  ``code`` from the resolver's own contract (``incompatible_parent`` /
  ``no_admitting_parent`` -- ``unresolved`` is added only by the HTTP gate,
  never by the pure resolver) and a ``field`` path that, after stripping any
  ``per_question_params[i].`` batch prefix, addresses a value that is actually
  present in the per-question-merged payload (a request-level pin inherited
  by a batch row counts as present through that row).

This module imports only ``src.common.resolver`` and subject schema /
curriculum-loader modules -- never ``server.*`` or fastapi -- so it runs
without the web extras installed.
"""

from __future__ import annotations

import random
import re

from src.common.admission import admitted_parents_by_code
from src.common.curriculum_loader import (
    allowed_learning_content as _math_allowed_lc,
)
from src.common.curriculum_loader import (
    allowed_learning_performance as _math_allowed_lp,
)
from src.common.resolver import ResolveConflictError, _resolved_subquestion_count, resolve
from src.natural_sciences.curriculum_loader import (
    allowed_learning_content as _ns_allowed_lc,
)
from src.natural_sciences.curriculum_loader import (
    allowed_learning_performance as _ns_allowed_lp,
)
from src.natural_sciences.curriculum_loader import (
    load_learning_content as _load_ns_lc,
)
from src.natural_sciences.curriculum_loader import (
    load_learning_performance as _load_ns_lp,
)
from src.natural_sciences.schemas import QuestionContext as NaturalContext
from src.natural_sciences.schemas import QuestionSubContext as NaturalSubContext
from src.sampler import _LC_DATA as _MATH_LC_DATA
from src.sampler import _LP_DATA as _MATH_LP_DATA
from src.sampler import _MATH_SUBJECT_TO_PREFIXES
from src.schemas import QuestionContext as MathContext
from src.social_studies.curriculum_loader import (
    allowed_learning_content as _ss_allowed_lc,
)
from src.social_studies.curriculum_loader import (
    allowed_learning_performance as _ss_allowed_lp,
)
from src.social_studies.curriculum_loader import (
    load_learning_content as _load_ss_lc,
)
from src.social_studies.curriculum_loader import (
    load_learning_performance as _load_ss_lp,
)
from src.social_studies.schemas import ContentDomain, QuestionSubject
from src.social_studies.schemas import QuestionContext as SocialContext

# ---------------------------------------------------------------------------
# Real curriculum pools (grade 7 / 第四學習階段, per the plan's Global
# Constraints), loaded once through the same public loaders the samplers use.
# ---------------------------------------------------------------------------

_STAGE_4 = "第四學習階段"

_MATH_LC_POOL: list[str] = [
    e["value"]
    for e in _math_allowed_lc(
        _MATH_LC_DATA, _STAGE_4, subject_to_prefixes=_MATH_SUBJECT_TO_PREFIXES
    )
]
_MATH_LP_POOL: list[str] = [
    e["value"]
    for e in _math_allowed_lp(
        _MATH_LP_DATA, _STAGE_4, subject_to_prefixes=_MATH_SUBJECT_TO_PREFIXES
    )
]

_SS_LC_POOL: list[str] = [e["value"] for e in _ss_allowed_lc(_load_ss_lc(), _STAGE_4)]
_SS_LP_POOL: list[str] = [e["value"] for e in _ss_allowed_lp(_load_ss_lp(), _STAGE_4)]

_NS_LC_POOL: list[str] = [e["value"] for e in _ns_allowed_lc(_load_ns_lc(), _STAGE_4)]
_NS_LP_POOL: list[str] = [e["value"] for e in _ns_allowed_lp(_load_ns_lp(), _STAGE_4)]

_MATH_CONTEXTS = [c.value for c in MathContext]
_SOCIAL_CONTEXTS = [c.value for c in SocialContext]
_NATURAL_CONTEXTS = [c.value for c in NaturalContext]
_NATURAL_SUBCONTEXTS = [c.value for c in NaturalSubContext]
_SOCIAL_SUBJECTS = [s.value for s in QuestionSubject]
_SOCIAL_DOMAINS = [d.value for d in ContentDomain]
_MATH_SUBJECT_FILTERS = list(_MATH_SUBJECT_TO_PREFIXES)

# Independent admission maps for the #838 necessity check below -- computed
# straight from the raw curriculum data via src.common.admission, never
# through the resolver/sampler's own bookkeeping, so a bug in how the
# resolver threads pins/subject/domain around cannot also hide from this
# check just because it shares the same low-level admission primitive.
_SS_LC_SUBJECT_ADMISSION = admitted_parents_by_code(_load_ss_lc(), "學習內容", "科目")
_SS_LP_SUBJECT_ADMISSION = admitted_parents_by_code(_load_ss_lp(), "學習表現", "科目")
_SS_LC_DOMAIN_ADMISSION = admitted_parents_by_code(_load_ss_lc(), "學習內容", "內容領域")

_KNOWN_ERROR_CODES = frozenset({"incompatible_parent", "no_admitting_parent"})
_SUBQ_FIELD_RE = re.compile(
    r"^subquestion_configs\[(\d+)\]\.(learning_content|learning_performance)$"
)

_REDRAW_KEYS = {
    "math": ["學習內容", "學習表現", "核心素養", "content_type", "grade"],
    "social_studies": [
        "科目",
        "內容領域",
        "subject_filter",
        "content_domain",
        "學習內容",
        "學習表現",
        "sub_question_count",
        "情境",
    ],
    "natural_sciences": [
        "情境",
        "情境子類別",
        "sub_context",
        "context",
        "學習內容",
        "學習表現",
        "sub_question_count",
    ],
}


def _blank(value: object) -> bool:
    if isinstance(value, str):
        return not value.strip()
    return value is None or value == []


def _pick_codes(rng: random.Random, pool: list[str], lo: int, hi: int) -> list[str]:
    if not pool:
        return []
    k = rng.randint(lo, min(hi, len(pool)))
    return rng.sample(pool, k)


def _maybe(rng: random.Random, probability: float) -> bool:
    return rng.random() < probability


# ---------------------------------------------------------------------------
# Per-subject field generators. Each returns a dict of fields suitable for a
# request-level payload, a per_question_params row ("question" level), or a
# subquestion_configs row ("小題" level, for the two curriculum fields).
# ---------------------------------------------------------------------------


def _gen_math_fields(rng: random.Random) -> dict:
    fields: dict = {}
    if _maybe(rng, 0.5):
        n = rng.randint(1, len(_MATH_CONTEXTS))
        fields["context"] = rng.sample(_MATH_CONTEXTS, n)
    if _maybe(rng, 0.5):
        fields["subject_filter"] = rng.choice(_MATH_SUBJECT_FILTERS)
    if _maybe(rng, 0.6):
        fields["learning_content"] = _pick_codes(rng, _MATH_LC_POOL, 1, 3)
    if _maybe(rng, 0.6):
        fields["learning_performance"] = _pick_codes(rng, _MATH_LP_POOL, 1, 2)
    return fields


def _gen_social_fields(rng: random.Random) -> dict:
    fields: dict = {}
    if _maybe(rng, 0.5):
        n = rng.randint(1, len(_SOCIAL_CONTEXTS))
        fields["context"] = rng.sample(_SOCIAL_CONTEXTS, n)
    if _maybe(rng, 0.6):
        n = rng.randint(1, 2)
        fields["subject_filter"] = rng.sample(_SOCIAL_SUBJECTS, n)
    if _maybe(rng, 0.5):
        fields["content_domain"] = rng.choice(_SOCIAL_DOMAINS)
    if _maybe(rng, 0.6):
        fields["learning_content"] = _pick_codes(rng, _SS_LC_POOL, 1, 3)
    if _maybe(rng, 0.5):
        fields["learning_performance"] = _pick_codes(rng, _SS_LP_POOL, 1, 2)
    if _maybe(rng, 0.3):
        fields["target_surface"] = rng.choice(["紙本", "數位"])
    return fields


def _gen_social_subquestion_configs(rng: random.Random) -> list[dict] | None:
    if not _maybe(rng, 0.5):
        return None
    n = rng.randint(3, 7)
    rows = []
    for _ in range(n):
        row: dict = {}
        if _maybe(rng, 0.4):
            row["learning_content"] = _pick_codes(rng, _SS_LC_POOL, 1, 2)
        if _maybe(rng, 0.3):
            row["learning_performance"] = _pick_codes(rng, _SS_LP_POOL, 1, 2)
        rows.append(row)
    return rows


def _gen_natural_fields(rng: random.Random) -> dict:
    fields: dict = {}
    if _maybe(rng, 0.6):
        n = rng.randint(1, len(_NATURAL_CONTEXTS))
        fields["context"] = rng.sample(_NATURAL_CONTEXTS, n)
    if _maybe(rng, 0.6):
        fields["sub_context"] = rng.choice(_NATURAL_SUBCONTEXTS)
    if _maybe(rng, 0.5):
        fields["learning_content"] = _pick_codes(rng, _NS_LC_POOL, 1, 3)
    if _maybe(rng, 0.5):
        fields["learning_performance"] = _pick_codes(rng, _NS_LP_POOL, 1, 2)
    return fields


def _gen_natural_subquestion_configs(rng: random.Random) -> list[dict] | None:
    if not _maybe(rng, 0.5):
        return None
    n = rng.randint(3, 7)
    rows = []
    for _ in range(n):
        row: dict = {}
        if _maybe(rng, 0.4):
            row["learning_content"] = _pick_codes(rng, _NS_LC_POOL, 1, 2)
        if _maybe(rng, 0.3):
            row["learning_performance"] = _pick_codes(rng, _NS_LP_POOL, 1, 2)
        rows.append(row)
    return rows


def _gen_redraws(rng: random.Random, subject: str, *, batch: bool, count: int) -> dict:
    pool = _REDRAW_KEYS[subject]
    keys = rng.sample(pool, rng.randint(1, min(3, len(pool))))
    redraws: dict = {}
    for key in keys:
        path = key
        if batch:
            idx = rng.randrange(count)
            path = f"per_question_params[{idx}].{key}"
        redraws[path] = rng.randint(0, 3)
    if _maybe(rng, 0.3):
        j = rng.randint(0, 6)
        subpath = f"subquestion_configs[{j}].learning_content"
        if batch:
            idx = rng.randrange(count)
            subpath = f"per_question_params[{idx}].{subpath}"
        redraws[subpath] = rng.randint(0, 2)
    return redraws


def _build_payload(rng: random.Random) -> dict:
    subject = rng.choice(["math", "social_studies", "natural_sciences"])
    count = rng.randint(1, 3)
    payload: dict = {
        "subject": subject,
        "seed": rng.randint(1, 2**31 - 1),
        # Global Constraints: use grade 7 for 第四學習階段 examples so the
        # pinned codes above (drawn from the stage-4 pools) are meaningful.
        "grade": 7,
    }

    if subject == "math":
        payload.update(_gen_math_fields(rng))
    elif subject == "social_studies":
        payload["set_type"] = "題組題"
        payload.update(_gen_social_fields(rng))
    else:
        payload.update(_gen_natural_fields(rng))

    use_batch = count > 1 or _maybe(rng, 0.3)
    if use_batch:
        payload["count"] = count
        rows = []
        for _ in range(count):
            row: dict = {}
            if _maybe(rng, 0.5):
                if subject == "math":
                    row.update(_gen_math_fields(rng))
                elif subject == "social_studies":
                    row.update(_gen_social_fields(rng))
                    configs = _gen_social_subquestion_configs(rng)
                    if configs is not None:
                        row["subquestion_configs"] = configs
                else:
                    row.update(_gen_natural_fields(rng))
                    configs = _gen_natural_subquestion_configs(rng)
                    if configs is not None:
                        row["subquestion_configs"] = configs
            rows.append(row)
        payload["per_question_params"] = rows
    else:
        payload["count"] = 1
        if subject == "social_studies":
            configs = _gen_social_subquestion_configs(rng)
            if configs is not None:
                payload["subquestion_configs"] = configs
        elif subject == "natural_sciences":
            configs = _gen_natural_subquestion_configs(rng)
            if configs is not None:
                payload["subquestion_configs"] = configs

    if _maybe(rng, 0.4):
        payload["redraws"] = _gen_redraws(subject=subject, rng=rng, batch=use_batch, count=count)

    return payload


# ---------------------------------------------------------------------------
# Error-shape validation: every error must use a known code and a field path
# that addresses an input actually present in the per-question-merged view of
# the *original* payload passed to resolve() (a request-level pin inherited by
# a batch row is "present" through that row's merged view).
# ---------------------------------------------------------------------------


def _row_view(payload: dict, row_index: int | None) -> dict:
    if row_index is None:
        return payload
    rows = payload.get("per_question_params") or []
    base = {
        key: value
        for key, value in payload.items()
        if key not in {"subject", "count", "per_question_params", "redraws"}
    }
    row = rows[row_index] if row_index < len(rows) else {}
    merged = dict(base)
    merged.update(row)
    return merged


def _parse_error_field(field: str, count: int) -> tuple[int | None, str]:
    """Split a resolver error field into its batch row index (``None`` when

    the payload is not a batch) and its local (per-row) field name.
    """
    if not field.startswith("per_question_params["):
        return None, field
    idx_text, _, rest = field[len("per_question_params[") :].partition("]")
    assert idx_text.isdigit() and rest.startswith("."), field
    row_index = int(idx_text)
    assert 0 <= row_index < count, field
    return row_index, rest[1:]


def _assert_well_formed_error(error: dict, payload: dict, count: int) -> None:
    assert {"field", "code", "parent"} <= set(error.keys()), error
    assert error["code"] in _KNOWN_ERROR_CODES, error
    assert isinstance(error["parent"], str) and error["parent"], error

    field = error["field"]
    row_index, local_field = _parse_error_field(field, count)
    view = _row_view(payload, row_index)
    subq_match = _SUBQ_FIELD_RE.match(local_field)
    if subq_match:
        slot_index, subfield = int(subq_match.group(1)), subq_match.group(2)
        configs = view.get("subquestion_configs")
        assert isinstance(configs, list) and slot_index < len(configs), (field, configs)
        row = configs[slot_index]
        value = row.get(subfield) if isinstance(row, dict) else None
    elif local_field in ("learning_content", "learning_performance", "sub_context"):
        value = view.get(local_field)
    else:
        raise AssertionError(f"unexpected resolver error field shape: {field!r}")

    assert not _blank(value), (field, value, payload)


# ---------------------------------------------------------------------------
# #838 necessity check: every social-studies conflict must be unavoidable.
#
# ``_assert_well_formed_error`` only checks the error's *shape*. This section
# independently re-derives, from raw admission data via ``src.common.admission``
# (never by trusting the resolver's own bookkeeping), that no candidate parent
# value could have satisfied every pinned code -- i.e. the resolver did not
# over-reject.
# ---------------------------------------------------------------------------


def _row_seed(payload: dict, row_index: int | None) -> int | str | None:
    """The seed the resolver actually used to resolve this row's 小題數.

    Mirrors ``resolve()``'s own batch worker-seed derivation (``seed +
    index`` unless the row pins its own seed) so the 小題數 draw below lines
    up with what the resolver itself drew.
    """
    base_seed = payload.get("seed")
    if row_index is None:
        return base_seed
    rows = payload.get("per_question_params") or []
    row = rows[row_index] if row_index < len(rows) else {}
    row_seed = row.get("seed")
    if not _blank(row_seed):
        return row_seed
    if base_seed is None:
        return None
    return base_seed + row_index


def _resolved_curriculum_pins(
    payload: dict, row_index: int | None
) -> tuple[list[str], list[str]]:
    """Every 學習內容/學習表現 code pinned for this merged row.

    Request-level (or batch-row) top-level pins, plus each
    ``subquestion_configs`` row's own pins -- limited to the resolver's own
    resolved 小題數 for this row (recomputed with the same pure
    ``_resolved_subquestion_count`` helper the resolver itself calls,
    independent of the admission checks under test here), since rows beyond
    that count are never inspected by the sampler and are not real
    constraints.
    """
    view = _row_view(payload, row_index)
    lc = list(view.get("learning_content") or [])
    lp = list(view.get("learning_performance") or [])
    configs = view.get("subquestion_configs")
    if isinstance(configs, list) and configs:
        count = _resolved_subquestion_count(
            {**view, "seed": _row_seed(payload, row_index)}, None
        )
        for row in configs[:count]:
            if isinstance(row, dict):
                lc.extend(row.get("learning_content") or [])
                lp.extend(row.get("learning_performance") or [])
    return lc, lp


def _parent_kind(parent: str) -> str:
    """Classify an error's ``parent`` value as the ``科目`` or ``內容領域`` check."""
    if parent in ("科目", "內容領域"):
        return parent
    if parent in _SOCIAL_SUBJECTS:
        return "科目"
    if parent in _SOCIAL_DOMAINS:
        return "內容領域"
    raise AssertionError(f"unrecognized 科目/內容領域 parent value: {parent!r}")


def _assert_social_conflict_necessary(error: dict, payload: dict, count: int) -> None:
    """The reported conflict must be unavoidable, verified independently.

    科目-parent error: no candidate 科目 -- the supplied ``subject_filter``
    list, or all four values when blank -- admits every pinned 學習內容/
    學習表現 code of the merged row.

    內容領域-parent error: no candidate 內容領域 -- the pinned
    ``content_domain``, or all four domains when blank -- admits every
    pinned 學習內容 code that carries a 內容領域 tag (untagged codes, e.g.
    歷/地, never constrain 內容領域 and are excluded, per #833).
    """
    row_index, _local_field = _parse_error_field(error["field"], count)
    view = _row_view(payload, row_index)
    lc_codes, lp_codes = _resolved_curriculum_pins(payload, row_index)
    kind = _parent_kind(error["parent"])

    if kind == "科目":
        subject_filter = view.get("subject_filter")
        if _blank(subject_filter):
            candidates: list[str] = list(_SOCIAL_SUBJECTS)
        elif isinstance(subject_filter, list):
            candidates = subject_filter
        else:
            candidates = [subject_filter]
        for candidate in candidates:
            lc_ok = all(candidate in (_SS_LC_SUBJECT_ADMISSION.get(c) or []) for c in lc_codes)
            lp_ok = all(candidate in (_SS_LP_SUBJECT_ADMISSION.get(c) or []) for c in lp_codes)
            if lc_ok and lp_ok:
                raise AssertionError(
                    "resolver raised a 科目 conflict but candidate "
                    f"{candidate!r} admits every pinned code: "
                    f"lc={lc_codes} lp={lp_codes} error={error} payload={payload}"
                )
    else:
        tagged_lc = [c for c in lc_codes if c in _SS_LC_DOMAIN_ADMISSION]
        if not tagged_lc:
            return
        content_domain = view.get("content_domain")
        domain_candidates = (
            list(_SOCIAL_DOMAINS) if _blank(content_domain) else [content_domain]
        )
        for candidate in domain_candidates:
            if all(candidate in (_SS_LC_DOMAIN_ADMISSION.get(c) or []) for c in tagged_lc):
                raise AssertionError(
                    "resolver raised a 內容領域 conflict but candidate "
                    f"{candidate!r} admits every pinned tagged code: "
                    f"lc={tagged_lc} error={error} payload={payload}"
                )


# ---------------------------------------------------------------------------
# The property test itself.
# ---------------------------------------------------------------------------

_ITERATIONS = 300
_SEED = 20260917


def test_resolver_property_all_subjects() -> None:
    rng = random.Random(_SEED)
    for _ in range(_ITERATIONS):
        payload = _build_payload(rng)
        count = payload.get("count", 1)
        try:
            result = resolve(payload)
        except ResolveConflictError as exc:
            assert exc.errors, payload
            for error in exc.errors:
                _assert_well_formed_error(error, payload, count)
                if payload.get("subject") == "social_studies":
                    _assert_social_conflict_necessary(error, payload, count)
            continue

        second = resolve(result.payload)
        assert second.payload == result.payload, (payload, result.payload, second.payload)
        assert second.drawn == [], (payload, second.drawn)
        assert second.cleared == [], (payload, second.cleared)


# ---------------------------------------------------------------------------
# Fixed sanity reproductions (issue #838): these are the concrete production
# payloads that motivated the narrowing rule; they must resolve and be
# idempotent on this branch (they failed prior to #833-#837).
# ---------------------------------------------------------------------------


def test_resolve_production_reproduction_civic_domain_blank_is_idempotent() -> None:
    payload = {
        "subject": "social_studies",
        "seed": 101,
        "grade": 7,
        "set_type": "題組題",
        "target_surface": "紙本",
        "subject_filter": ["公民與社會"],
        "learning_content": ["公Bn-Ⅳ-3"],
    }

    result = resolve(payload)

    assert result.payload["content_domain"] == "Civic Institutions and Systems"
    second = resolve(result.payload)
    assert second.payload == result.payload
    assert second.drawn == []
    assert second.cleared == []


def test_resolve_production_reproduction_mixed_subject_civic_code_is_idempotent() -> None:
    payload = {
        "subject": "social_studies",
        "seed": 202,
        "grade": 7,
        "set_type": "題組題",
        "target_surface": "紙本",
        "subject_filter": ["公民與社會", "地理"],
        "learning_content": ["公Bj-Ⅳ-1"],
    }

    result = resolve(payload)

    second = resolve(result.payload)
    assert second.payload == result.payload
    assert second.drawn == []
    assert second.cleared == []

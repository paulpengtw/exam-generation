"""Anti-recurrence guard: every GenerateParams field × every subject must be classified.

For each (field, subject) pair one of the following must hold:

  (a) FORWARDED    — the field reaches the subject's sampler or generator entrypoint.
                     Verified structurally: the token appears in the source of the
                     named adapter function.

  (b) REJECTED     — the field is explicitly rejected by the subject's validate_params
                     hook when non-None.  Verified: validate_params is set and the
                     field name appears in its source.

  (c) INAPPLICABLE — the field is explicitly declared out-of-scope for that subject.
                     Each entry carries a mandatory one-line reason so that adding one
                     is a deliberate act rather than a silent exemption.

The test fails if a new GenerateParams field is added without classifying it for
all three subjects.

Kill-switch: reverting #196's core_competency forwarding into _ss_do_sample_params
makes this test fail — which is exactly what it would have caught originally.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

import pytest

from server.generate import service as _svc
from server.generate.models import GenerateParams
from server.generate.subjects import (
    SUBJECTS,
    _math_coerce_overrides,
    _math_do_sample_params,
    _ns_coerce_overrides,
    _ns_do_sample_params,
    _ss_coerce_overrides,
    _ss_do_sample_params,
)

# ── Classification sentinels ──────────────────────────────────────────────────

FORWARDED = "forwarded"
REJECTED = "rejected"
INAPPLICABLE = "inapplicable"

_MA = "math"
_SS = "social_studies"
_NS = "natural_sciences"

# ── Classification table ───────────────────────────────────────────────────────
#
# Each entry: (status, reason).
#   FORWARDED   → reason is empty string (proof lives in FORWARDING_PROOFS below).
#   REJECTED    → reason is empty string (proof is validate_params source scan).
#   INAPPLICABLE → reason is a required one-line explanation.
#
# The table must cover every GenerateParams.model_fields key × every subject.
# A new field added without a classification entry will make the coverage test fail.

CLASSIFICATION: dict[str, dict[str, tuple[str, str]]] = {
    # ── Request-level fields — consumed by the service before subject dispatch ──
    "subject": {
        _MA: (INAPPLICABLE, "routes to subject pipeline at service level; not a per-subject param"),
        _SS: (INAPPLICABLE, "routes to subject pipeline at service level; not a per-subject param"),
        _NS: (INAPPLICABLE, "routes to subject pipeline at service level; not a per-subject param"),
    },
    "count": {
        _MA: (INAPPLICABLE, "service-level worker count; not a per-subject param"),
        _SS: (INAPPLICABLE, "service-level worker count; not a per-subject param"),
        _NS: (INAPPLICABLE, "service-level worker count; not a per-subject param"),
    },
    "per_question_params": {
        _MA: (INAPPLICABLE, "expanded per-worker at service level; each override field classified"),
        _SS: (INAPPLICABLE, "expanded per-worker at service level; each override field classified"),
        _NS: (INAPPLICABLE, "expanded per-worker at service level; each override field classified"),
    },
    # ── Model / effort fields — forwarded via client_config for all subjects ──
    "model_plan": {
        _MA: (FORWARDED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    "model_execute": {
        _MA: (FORWARDED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    "effort_plan": {
        _MA: (FORWARDED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    "effort_execute": {
        _MA: (FORWARDED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    # ── max_retries — REQUEST_LEVEL but also forwarded to every generator ──
    "max_retries": {
        _MA: (FORWARDED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    # ── seed — forwarded to every sampler via _sample_worker_params ──
    "seed": {
        _MA: (FORWARDED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    # ── skip_verify — forwarded to every generator ──
    "skip_verify": {
        _MA: (FORWARDED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    # ── image_generation_mode — forwarded to every generator ──
    "image_generation_mode": {
        _MA: (FORWARDED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    # ── grade — forwarded to every sampler directly ──
    "grade": {
        _MA: (FORWARDED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    # ── context — forwarded to every sampler via context_override ──
    "context": {
        _MA: (FORWARDED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    # ── set_type — forwarded to every sampler via set_type_override ──
    "set_type": {
        _MA: (FORWARDED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    # ── q_type — forwarded to every sampler via q_type_override ──
    "q_type": {
        _MA: (FORWARDED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    # ── difficulty — forwarded to every sampler directly ──
    "difficulty": {
        _MA: (FORWARDED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    # ── content_type — forwarded to every sampler directly ──
    "content_type": {
        _MA: (FORWARDED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    # ── passage — forwarded to every generator as user_passage ──
    "passage": {
        _MA: (FORWARDED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    # ── options — forwarded to every generator as user_options ──
    "options": {
        _MA: (FORWARDED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    # ── topic — forwarded to every generator as user_topic ──
    "topic": {
        _MA: (FORWARDED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    # ── core_question — forwarded to every generator as user_core_question ──
    "core_question": {
        _MA: (FORWARDED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    # ── learning_performance — forwarded to every sampler directly ──
    "learning_performance": {
        _MA: (FORWARDED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    # ── learning_content — forwarded to every sampler directly ──
    "learning_content": {
        _MA: (FORWARDED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    # ── style — math-specific; inapplicable to SS and NS ──
    "style": {
        _MA: (FORWARDED, ""),
        _SS: (INAPPLICABLE, "SS has no question-style dimension; math-specific field"),
        _NS: (INAPPLICABLE, "NS has no question-style dimension; math-specific field"),
    },
    # ── core_competency — math/SS forward it; NS explicitly rejects it (#196 kill-switch) ──
    "core_competency": {
        _MA: (FORWARDED, ""),
        _SS: (FORWARDED, ""),   # ← #196 added core_competency=overrides["core_competency_override"]
                                #   to _ss_do_sample_params; reverting that makes this test fail
        _NS: (REJECTED, ""),
    },
    # ── science_competency — NS-specific ──
    "science_competency": {
        _MA: (INAPPLICABLE, "math uses core_competency; science_competency is NS-specific"),
        _SS: (INAPPLICABLE, "SS uses core_competency not science_competency; NS-specific"),
        _NS: (FORWARDED, ""),
    },
    # ── sub_context — NS-specific (PISA情境子類別) ──
    "sub_context": {
        _MA: (INAPPLICABLE, "math has no PISA情境子類別; sub_context is NS-specific"),
        _SS: (INAPPLICABLE, "social_studies has no情境子類別; sub_context is NS-specific"),
        _NS: (FORWARDED, ""),
    },
    # ── subject_filter — math and SS forward it; NS silently drops it (#182) ──
    "subject_filter": {
        _MA: (FORWARDED, ""),
        _SS: (FORWARDED, ""),
        _NS: (INAPPLICABLE, "NS has no 科目 bucketing; not read by NS path — #182"),
    },
    # ── disable_reference_fewshot — math uses style-keyed few-shot (SS/NS-only feature) ──
    "disable_reference_fewshot": {
        _MA: (INAPPLICABLE, "math uses style-keyed few-shot (data/few_shot/); SS/NS-only feature"),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    # ── reporting_scale — NS-specific (models.py §279: other subjects accept and ignore) ──
    "reporting_scale": {
        _MA: (INAPPLICABLE, "math uses difficulty not Reporting Scale; others ignore (§279)"),
        _SS: (INAPPLICABLE, "SS uses difficulty not Reporting Scale; §279: other subjects ignore"),
        _NS: (FORWARDED, ""),
    },
    # ── coverage_mode — SS uses balanced_batch; math/NS do not ──
    "coverage_mode": {
        _MA: (INAPPLICABLE, "math has no 文本生成器 stage; balanced-batch hint is SS-only"),
        _SS: (FORWARDED, ""),
        _NS: (INAPPLICABLE, "not forwarded to _ns_generate_with_corrections — TODO(#208)"),
    },
    # ── sub-question / word-limit fields — math rejects; SS and NS forward ──
    "sub_question_count": {
        _MA: (REJECTED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    "question_word_limit": {
        _MA: (REJECTED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    "option_word_limit": {
        _MA: (REJECTED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    "text_word_limit": {
        _MA: (REJECTED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    "subquestion_configs": {
        _MA: (REJECTED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
}

# ── Structural forwarding proofs ───────────────────────────────────────────────
#
# For each FORWARDED (field, subject) pair: (fn_to_inspect, token_that_must_appear).
# The token is a distinctive substring of the adapter source that proves the field
# value is passed on.  If the code is restructured and the token vanishes, the proof
# fails — prompting a table update.
#
# The core_competency/social_studies row is the kill-switch: reverting #196
# (which added "core_competency=overrides["core_competency_override"]" to
# _ss_do_sample_params) removes "core_competency" from that source and breaks this.

FORWARDING_PROOFS: dict[tuple[str, str], tuple[Callable[..., Any], str]] = {
    # model / effort — forwarded via client_config in _build_run_context
    ("model_plan",    _MA): (_svc._build_run_context, "params.model_plan"),
    ("model_plan",    _SS): (_svc._build_run_context, "params.model_plan"),
    ("model_plan",    _NS): (_svc._build_run_context, "params.model_plan"),
    ("model_execute", _MA): (_svc._build_run_context, "params.model_execute"),
    ("model_execute", _SS): (_svc._build_run_context, "params.model_execute"),
    ("model_execute", _NS): (_svc._build_run_context, "params.model_execute"),
    ("effort_plan",   _MA): (_svc._build_run_context, "params.effort_plan"),
    ("effort_plan",   _SS): (_svc._build_run_context, "params.effort_plan"),
    ("effort_plan",   _NS): (_svc._build_run_context, "params.effort_plan"),
    ("effort_execute",_MA): (_svc._build_run_context, "params.effort_execute"),
    ("effort_execute",_SS): (_svc._build_run_context, "params.effort_execute"),
    ("effort_execute",_NS): (_svc._build_run_context, "params.effort_execute"),
    # max_retries — stored in _RunContext from params.max_retries
    ("max_retries",   _MA): (_svc._build_run_context, "params.max_retries"),
    ("max_retries",   _SS): (_svc._build_run_context, "params.max_retries"),
    ("max_retries",   _NS): (_svc._build_run_context, "params.max_retries"),
    # seed — accessed as worker_params.seed in _sample_worker_params
    ("seed",          _MA): (_svc._sample_worker_params, "worker_params.seed"),
    ("seed",          _SS): (_svc._sample_worker_params, "worker_params.seed"),
    ("seed",          _NS): (_svc._sample_worker_params, "worker_params.seed"),
    # skip_verify — forwarded in _worker_one from ctx.params
    ("skip_verify",       _MA): (_svc._worker_one, "ctx.params.skip_verify"),
    ("skip_verify",       _SS): (_svc._worker_one, "ctx.params.skip_verify"),
    ("skip_verify",       _NS): (_svc._worker_one, "ctx.params.skip_verify"),
    # image_generation_mode — forwarded in _worker_one from ctx.params
    ("image_generation_mode", _MA): (_svc._worker_one, "ctx.params.image_generation_mode"),
    ("image_generation_mode", _SS): (_svc._worker_one, "ctx.params.image_generation_mode"),
    ("image_generation_mode", _NS): (_svc._worker_one, "ctx.params.image_generation_mode"),
    # passage — forwarded in _worker_one as user_passage
    ("passage", _MA): (_svc._worker_one, "ctx.params.passage"),
    ("passage", _SS): (_svc._worker_one, "ctx.params.passage"),
    ("passage", _NS): (_svc._worker_one, "ctx.params.passage"),
    # options — forwarded in _worker_one as user_options
    ("options", _MA): (_svc._worker_one, "ctx.params.options"),
    ("options", _SS): (_svc._worker_one, "ctx.params.options"),
    ("options", _NS): (_svc._worker_one, "ctx.params.options"),
    # topic — forwarded in _worker_one as user_topic
    ("topic", _MA): (_svc._worker_one, "ctx.params.topic"),
    ("topic", _SS): (_svc._worker_one, "ctx.params.topic"),
    ("topic", _NS): (_svc._worker_one, "ctx.params.topic"),
    # core_question — forwarded in _worker_one as user_core_question
    ("core_question", _MA): (_svc._worker_one, "ctx.params.core_question"),
    ("core_question", _SS): (_svc._worker_one, "ctx.params.core_question"),
    ("core_question", _NS): (_svc._worker_one, "ctx.params.core_question"),
    # text_word_limit — forwarded in _worker_one (SS/NS); math rejects so no proof needed
    ("text_word_limit", _SS): (_svc._worker_one, "ctx.params.text_word_limit"),
    ("text_word_limit", _NS): (_svc._worker_one, "ctx.params.text_word_limit"),
    # disable_reference_fewshot — forwarded in _worker_one (SS/NS)
    ("disable_reference_fewshot", _SS): (_svc._worker_one, "ctx.params.disable_reference_fewshot"),
    ("disable_reference_fewshot", _NS): (_svc._worker_one, "ctx.params.disable_reference_fewshot"),
    # grade — forwarded directly in each sampler adapter
    ("grade", _MA): (_math_do_sample_params, "params.grade"),
    ("grade", _SS): (_ss_do_sample_params,   "params.grade"),
    ("grade", _NS): (_ns_do_sample_params,   "params.grade"),
    # context — forwarded via context_override in coerce_overrides
    ("context", _MA): (_math_coerce_overrides, "params.context"),
    ("context", _SS): (_ss_coerce_overrides,   "params.context"),
    ("context", _NS): (_ns_coerce_overrides,   "params.context"),
    # set_type — forwarded via set_type_override in coerce_overrides
    ("set_type", _MA): (_math_coerce_overrides, "params.set_type"),
    ("set_type", _SS): (_ss_coerce_overrides,   "params.set_type"),
    ("set_type", _NS): (_ns_coerce_overrides,   "params.set_type"),
    # q_type — forwarded via q_type_override in coerce_overrides
    ("q_type", _MA): (_math_coerce_overrides, "params.q_type"),
    ("q_type", _SS): (_ss_coerce_overrides,   "params.q_type"),
    ("q_type", _NS): (_ns_coerce_overrides,   "params.q_type"),
    # style — math-specific; forwarded via style_override in coerce_overrides
    ("style", _MA): (_math_coerce_overrides, "params.style"),
    # difficulty — forwarded directly in each sampler adapter
    ("difficulty", _MA): (_math_do_sample_params, "params.difficulty"),
    ("difficulty", _SS): (_ss_do_sample_params,   "params.difficulty"),
    ("difficulty", _NS): (_ns_do_sample_params,   "params.difficulty"),
    # content_type — forwarded directly in each sampler adapter
    ("content_type", _MA): (_math_do_sample_params, "params.content_type"),
    ("content_type", _SS): (_ss_do_sample_params,   "params.content_type"),
    ("content_type", _NS): (_ns_do_sample_params,   "params.content_type"),
    # learning_performance — forwarded directly in each sampler adapter
    ("learning_performance", _MA): (_math_do_sample_params, "params.learning_performance"),
    ("learning_performance", _SS): (_ss_do_sample_params,   "params.learning_performance"),
    ("learning_performance", _NS): (_ns_do_sample_params,   "params.learning_performance"),
    # learning_content — forwarded directly in each sampler adapter
    ("learning_content", _MA): (_math_do_sample_params, "params.learning_content"),
    ("learning_content", _SS): (_ss_do_sample_params,   "params.learning_content"),
    ("learning_content", _NS): (_ns_do_sample_params,   "params.learning_content"),
    # core_competency — ← KILL-SWITCH for #196
    # math: forwarded directly in _math_do_sample_params
    # SS:   forwarded in _ss_do_sample_params via core_competency_override (#196 fix)
    # NS:   rejected (no proof needed)
    ("core_competency", _MA): (_math_do_sample_params, "params.core_competency"),
    ("core_competency", _SS): (_ss_do_sample_params,   "core_competency"),   # ← #196 kill-switch
    # science_competency — NS-specific, forwarded via science_competency_override
    ("science_competency", _NS): (_ns_coerce_overrides, "params.science_competency"),
    # sub_context — NS-specific, forwarded via sub_context_override
    ("sub_context", _NS): (_ns_coerce_overrides, "params.sub_context"),
    # subject_filter — math: direct; SS: via subject_override; NS: inapplicable
    ("subject_filter", _MA): (_math_do_sample_params, "params.subject_filter"),
    ("subject_filter", _SS): (_ss_coerce_overrides,   "params.subject_filter"),
    # reporting_scale — NS-specific, forwarded directly in NS sampler adapter
    ("reporting_scale", _NS): (_ns_do_sample_params, "params.reporting_scale"),
    # sub_question_count — SS/NS; math rejects
    ("sub_question_count", _SS): (_ss_do_sample_params, "params.sub_question_count"),
    ("sub_question_count", _NS): (_ns_do_sample_params, "params.sub_question_count"),
    # question_word_limit — SS/NS; math rejects
    ("question_word_limit", _SS): (_ss_do_sample_params, "params.question_word_limit"),
    ("question_word_limit", _NS): (_ns_do_sample_params, "params.question_word_limit"),
    # option_word_limit — SS/NS; math rejects
    ("option_word_limit", _SS): (_ss_do_sample_params, "params.option_word_limit"),
    ("option_word_limit", _NS): (_ns_do_sample_params, "params.option_word_limit"),
    # subquestion_configs — forwarded via decoded configs in _build_run_context; math rejects
    ("subquestion_configs", _SS): (_svc._build_run_context, "params.subquestion_configs"),
    ("subquestion_configs", _NS): (_svc._build_run_context, "params.subquestion_configs"),
    # coverage_mode — SS: forwarded via balanced_batch in _build_run_context
    ("coverage_mode", _SS): (_svc._build_run_context, "params.coverage_mode"),
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_source(fn: Callable[..., Any]) -> str:
    return inspect.getsource(fn)


def _validate_params_source(subject: str) -> str | None:
    """Return the source of the subject's validate_params function, or None if unset."""
    spec = SUBJECTS[subject]
    if spec.validate_params is None:
        return None
    return inspect.getsource(spec.validate_params)


# ── Tests ─────────────────────────────────────────────────────────────────────

_ALL_SUBJECTS = [_MA, _SS, _NS]
_ALL_FIELDS = list(GenerateParams.model_fields)


def test_classification_covers_all_fields_and_subjects() -> None:
    """Every GenerateParams field × every subject must appear in CLASSIFICATION.

    This is the 'anti-recurrence' part: adding a new contract field without
    classifying it for all three subjects makes this test fail.
    """
    missing: list[str] = []
    for field in _ALL_FIELDS:
        if field not in CLASSIFICATION:
            missing.append(f"field {field!r} has no entry in CLASSIFICATION")
            continue
        for subject in _ALL_SUBJECTS:
            if subject not in CLASSIFICATION[field]:
                missing.append(
                    f"field {field!r} has no classification for subject {subject!r}"
                )
    assert not missing, (
        "Unclassified (field, subject) pairs — add each to CLASSIFICATION with "
        "a forwarding proof, a rejection proof, or an inapplicable reason:\n"
        + "\n".join(f"  {m}" for m in missing)
    )


def test_no_extra_classifications_beyond_known_fields() -> None:
    """CLASSIFICATION should not reference fields that no longer exist in GenerateParams.

    Catches stale entries left behind when a field is removed.
    """
    known = set(_ALL_FIELDS)
    extra = [f for f in CLASSIFICATION if f not in known]
    assert not extra, (
        "CLASSIFICATION contains entries for fields not in GenerateParams: "
        + ", ".join(sorted(extra))
    )


@pytest.mark.parametrize(
    "field,subject",
    [
        (field, subject)
        for field in _ALL_FIELDS
        for subject in _ALL_SUBJECTS
        if CLASSIFICATION.get(field, {}).get(subject, (None,))[0] == FORWARDED
    ],
)
def test_forwarded_field_has_structural_proof(field: str, subject: str) -> None:
    """Each FORWARDED (field, subject) pair must have a proof token in FORWARDING_PROOFS,
    and that token must appear in the named adapter's source.

    Reverting #196's core_competency forwarding (removing
    'core_competency=overrides["core_competency_override"]' from _ss_do_sample_params)
    removes 'core_competency' from that source and fails this test.
    """
    key = (field, subject)
    assert key in FORWARDING_PROOFS, (
        f"({field!r}, {subject!r}) is classified as FORWARDED but has no entry in "
        "FORWARDING_PROOFS.  Add (fn, token) where token is a distinctive substring "
        "of fn's source proving the field is forwarded."
    )
    fn, token = FORWARDING_PROOFS[key]
    source = _get_source(fn)
    assert token in source, (
        f"Forwarding proof FAILED for ({field!r}, {subject!r}):\n"
        f"  token   : {token!r}\n"
        f"  function: {fn.__qualname__}\n"
        f"The token was not found in the function source.  Either the forwarding was\n"
        f"removed (regression) or the proof token needs updating."
    )


@pytest.mark.parametrize(
    "field,subject",
    [
        (field, subject)
        for field in _ALL_FIELDS
        for subject in _ALL_SUBJECTS
        if CLASSIFICATION.get(field, {}).get(subject, (None,))[0] == REJECTED
    ],
)
def test_rejected_field_is_explicit_in_validate_params(field: str, subject: str) -> None:
    """Each REJECTED (field, subject) pair must be named in validate_params source.

    This proves the rejection is explicit (not silently ignored) and would surface
    when a caller tries to use the field.
    """
    source = _validate_params_source(subject)
    assert source is not None, (
        f"({field!r}, {subject!r}) is classified as REJECTED but {subject!r} has "
        "no validate_params hook.  Either add the hook or reclassify the entry."
    )
    assert field in source, (
        f"({field!r}, {subject!r}) is classified as REJECTED but the field name "
        f"does not appear in {subject!r}'s validate_params source.  Ensure the "
        "field is explicitly checked (not just incidentally mentioned)."
    )


@pytest.mark.parametrize(
    "field,subject",
    [
        (field, subject)
        for field in _ALL_FIELDS
        for subject in _ALL_SUBJECTS
        if CLASSIFICATION.get(field, {}).get(subject, (None,))[0] == INAPPLICABLE
    ],
)
def test_inapplicable_entry_has_reason(field: str, subject: str) -> None:
    """Every INAPPLICABLE entry must carry a non-empty one-line reason.

    This makes adding to the registry a deliberate act rather than a silent exemption.
    """
    _, reason = CLASSIFICATION[field][subject]
    assert reason.strip(), (
        f"({field!r}, {subject!r}) is INAPPLICABLE but has an empty reason.  "
        "Add a one-line explanation of why the field is inapplicable for this subject."
    )


def test_classification_counts() -> None:
    """Sanity-check the aggregate counts to prevent silent table corruption."""
    forwarded = rejected = inapplicable = 0
    for field in _ALL_FIELDS:
        for subject in _ALL_SUBJECTS:
            status, _ = CLASSIFICATION.get(field, {}).get(subject, ("", ""))
            if status == FORWARDED:
                forwarded += 1
            elif status == REJECTED:
                rejected += 1
            elif status == INAPPLICABLE:
                inapplicable += 1
    total = len(_ALL_FIELDS) * len(_ALL_SUBJECTS)
    classified = forwarded + rejected + inapplicable
    assert classified == total, (
        f"Classification coverage mismatch: {classified}/{total} pairs classified "
        f"({forwarded} forwarded, {rejected} rejected, {inapplicable} inapplicable)"
    )
    # Hard-coded expected counts — update when fields are added/reclassified
    assert forwarded    == 81, f"Expected 81 FORWARDED, got {forwarded}"
    assert rejected     == 6,  f"Expected 6 REJECTED, got {rejected}"
    assert inapplicable == 21, f"Expected 21 INAPPLICABLE, got {inapplicable}"

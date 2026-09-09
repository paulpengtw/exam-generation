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

Each FORWARDED pair has a second classification in FORWARDING_COMPLETENESS:
RESOLVED means the resolver owns its draw, while PIN-ONLY means it is a
non-draw control or user pin with an explicit reason.

The test fails if a new GenerateParams field is added without classifying it for
all three subjects.

Kill-switch: removing #196's core_competency forwarding from the resolved SS
adapter
makes this test fail — which is exactly what it would have caught originally.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

import pytest

pytest.importorskip("sqlalchemy", reason="requires [web] extras: uv sync --extra web")

from server.generate import service as _svc
from server.generate.models import GenerateParams
from server.generate.subjects import (
    SUBJECTS,
    _math_coerce_overrides,
    _ns_coerce_overrides,
    _ns_do_generate,
    _ss_coerce_overrides,
)
from src.cli import _math_params_from_resolved as _math_params_from_resolved_payload
from src.common.resolver import DRAWABLE_FIELDS
from src.natural_sciences.cli import (
    _ns_params_from_resolved as _ns_params_from_resolved_payload,
)
from src.social_studies.cli import (
    _ss_params_from_resolved as _ss_params_from_resolved_payload,
)

# ── Classification sentinels ──────────────────────────────────────────────────

FORWARDED = "forwarded"
REJECTED = "rejected"
INAPPLICABLE = "inapplicable"
RESOLVED = "resolved"
PIN_ONLY = "pin-only"

_MA = "math"
_SS = "social_studies"
_NS = "natural_sciences"


# ── Completeness classification ───────────────────────────────────────────────
#
# FORWARDED is deliberately a two-part contract: either the resolver owns the
# field's draw, or the field is a pin/control with no resolver default.  Keep
# this separate from CLASSIFICATION so the existing forwarding/rejection proof
# table remains readable and a new FORWARDED row cannot silently inherit a status.
FORWARDING_COMPLETENESS: dict[tuple[str, str], tuple[str, str]] = {
    # Resolver-drawn values (including the global seed and per-slot config draws).
    **{
        (field, _MA): (RESOLVED, "")
        for field in {
            "seed",
            "grade",
            "style",
            "context",
            "set_type",
            "q_type",
            "content_type",
            "learning_performance",
            "core_competency",
            "math_thinking",
            "learning_content",
            "sub_question_count",
        }
    },
    **{
        (field, _SS): (RESOLVED, "")
        for field in {
            "seed",
            "grade",
            "context",
            "set_type",
            "q_type",
            "content_type",
            "subject_filter",
            "content_domain",
            "core_competency",
            "learning_content",
            "learning_performance",
            "sub_question_count",
            "subquestion_configs",
        }
    },
    **{
        (field, _NS): (RESOLVED, "")
        for field in {
            "seed",
            "grade",
            "context",
            "sub_context",
            "set_type",
            "q_type",
            "science_competency",
            "content_type",
            "learning_content",
            "learning_performance",
            "sub_question_count",
            "subquestion_configs",
            "reporting_scale",
        }
    },
    # Forwarded controls and user pins do not have a resolver draw.
    **{
        (field, subject): (PIN_ONLY, reason)
        for subject, fields in {
            _MA: {
                "skip_verify",
                "max_retries",
                "image_generation_mode",
                "difficulty",
                "subject_filter",
                "passage",
                "options",
                "topic",
                "core_question",
                "text_word_limit",
                "model_plan",
                "model_execute",
                "model_verify",
                "model_correct",
                "effort_plan",
                "effort_execute",
                "effort_verify",
                "effort_correct",
            },
            _SS: {
                "skip_verify",
                "disable_reference_fewshot",
                "max_retries",
                "image_generation_mode",
                "difficulty",
                "coverage_mode",
                "core_question_callback",
                "target_surface",
                "passage",
                "options",
                "topic",
                "core_question",
                "text_instruction",
                "question_word_limit",
                "option_word_limit",
                "text_word_limit",
                "allow_duplicate_figure_kinds",
                "model_plan",
                "model_execute",
                "model_verify",
                "model_correct",
                "effort_plan",
                "effort_execute",
                "effort_verify",
                "effort_correct",
            },
            _NS: {
                "skip_verify",
                "disable_reference_fewshot",
                "max_retries",
                "image_generation_mode",
                "difficulty",
                "coverage_mode",
                "core_question_callback",
                "passage",
                "options",
                "topic",
                "core_question",
                "question_word_limit",
                "option_word_limit",
                "text_word_limit",
                "allow_duplicate_figure_kinds",
                "model_plan",
                "model_execute",
                "model_verify",
                "model_correct",
                "effort_plan",
                "effort_execute",
                "effort_verify",
                "effort_correct",
            },
        }.items()
        for field in fields
        for reason in [
            "forwarded control or user pin; this subject has no resolver draw for the field"
        ]
    },
}

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
    "drawn": {
        _MA: (
            INAPPLICABLE,
            "resolver provenance metadata is persisted at request level and ignored by generation",
        ),
        _SS: (
            INAPPLICABLE,
            "resolver provenance metadata is persisted at request level and ignored by generation",
        ),
        _NS: (
            INAPPLICABLE,
            "resolver provenance metadata is persisted at request level and ignored by generation",
        ),
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
    # #375: per-request tier model overrides — forwarded via client_config for all subjects
    "model_verify": {
        _MA: (FORWARDED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    "model_correct": {
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
    # #377: per-request tier effort overrides — forwarded via client_config for all subjects
    "effort_verify": {
        _MA: (FORWARDED, ""),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    "effort_correct": {
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
    "allow_duplicate_figure_kinds": {
        _MA: (INAPPLICABLE, "SS-only figure-kind diversity kill-switch"),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    # ── seed — forwarded to every subject through the resolved worker payload ──
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
    # ── ICCS content-domain and paper/digital-surface pins — SS-only ──
    "content_domain": {
        _MA: (REJECTED, ""),
        _SS: (FORWARDED, ""),
        _NS: (REJECTED, ""),
    },
    "target_surface": {
        _MA: (REJECTED, ""),
        _SS: (FORWARDED, ""),
        _NS: (REJECTED, ""),
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
    # ── text instruction — social text-generator request pin; unwired elsewhere ──
    "text_instruction": {
        _MA: (REJECTED, ""),
        _SS: (FORWARDED, ""),
        _NS: (REJECTED, ""),
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
                                #   to the resolved SS adapter; reverting that makes this test fail
        _NS: (REJECTED, ""),
    },
    # ── math_thinking — math-only request surface ──
    "math_thinking": {
        _MA: (FORWARDED, ""),
        _SS: (INAPPLICABLE, "math-thinking is a math-only parameter"),
        _NS: (INAPPLICABLE, "math-thinking is a math-only parameter"),
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
    # ── coverage_mode — SS and NS use balanced_batch; math does not ──
    "coverage_mode": {
        _MA: (INAPPLICABLE, "math has no 文本生成器 stage; balanced-batch hint is SS/NS-only"),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    # ── core_question_callback — SS/NS prompt suggestion ──
    "core_question_callback": {
        _MA: (INAPPLICABLE, "SS-only prompt suggestion; math has no callback prompt"),
        _SS: (FORWARDED, ""),
        _NS: (FORWARDED, ""),
    },
    # ── sub-question / word-limit fields — all subjects forward where supported ──
    "sub_question_count": {
        _MA: (FORWARDED, ""),
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
        _MA: (FORWARDED, ""),
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
# the resolved SS adapter) removes "core_competency" from that source and breaks this.

FORWARDING_PROOFS: dict[tuple[str, str], tuple[Callable[..., Any], str]] = {
    # model / effort — forwarded via client_config in _build_run_context
    ("model_plan",    _MA): (_svc._build_run_context, "params.model_plan"),
    ("model_plan",    _SS): (_svc._build_run_context, "params.model_plan"),
    ("model_plan",    _NS): (_svc._build_run_context, "params.model_plan"),
    ("model_execute", _MA): (_svc._build_run_context, "params.model_execute"),
    ("model_execute", _SS): (_svc._build_run_context, "params.model_execute"),
    ("model_execute", _NS): (_svc._build_run_context, "params.model_execute"),
    # #375: tier model overrides — forwarded via client_config in _build_run_context
    ("model_verify",  _MA): (_svc._build_run_context, "params.model_verify"),
    ("model_verify",  _SS): (_svc._build_run_context, "params.model_verify"),
    ("model_verify",  _NS): (_svc._build_run_context, "params.model_verify"),
    ("model_correct", _MA): (_svc._build_run_context, "params.model_correct"),
    ("model_correct", _SS): (_svc._build_run_context, "params.model_correct"),
    ("model_correct", _NS): (_svc._build_run_context, "params.model_correct"),
    ("effort_plan",   _MA): (_svc._build_run_context, "params.effort_plan"),
    ("effort_plan",   _SS): (_svc._build_run_context, "params.effort_plan"),
    ("effort_plan",   _NS): (_svc._build_run_context, "params.effort_plan"),
    ("effort_execute",_MA): (_svc._build_run_context, "params.effort_execute"),
    ("effort_execute",_SS): (_svc._build_run_context, "params.effort_execute"),
    ("effort_execute",_NS): (_svc._build_run_context, "params.effort_execute"),
    # #377: tier effort overrides — forwarded via client_config in _build_run_context
    ("effort_verify",  _MA): (_svc._build_run_context, "params.effort_verify"),
    ("effort_verify",  _SS): (_svc._build_run_context, "params.effort_verify"),
    ("effort_verify",  _NS): (_svc._build_run_context, "params.effort_verify"),
    ("effort_correct", _MA): (_svc._build_run_context, "params.effort_correct"),
    ("effort_correct", _SS): (_svc._build_run_context, "params.effort_correct"),
    ("effort_correct", _NS): (_svc._build_run_context, "params.effort_correct"),
    # max_retries — stored in _RunContext from params.max_retries
    ("max_retries",   _MA): (_svc._build_run_context, "params.max_retries"),
    ("max_retries",   _SS): (_svc._build_run_context, "params.max_retries"),
    ("max_retries",   _NS): (_svc._build_run_context, "params.max_retries"),
    # allow_duplicate_figure_kinds — forwarded directly to both visual subjects' samplers
    ("allow_duplicate_figure_kinds", _SS): (
        _ss_params_from_resolved_payload,
        'payload.get("allow_duplicate_figure_kinds", False)',
    ),
    ("allow_duplicate_figure_kinds", _NS): (
        _ns_params_from_resolved_payload,
        'payload.get("allow_duplicate_figure_kinds", False)',
    ),
    # seed — accessed from the resolver-completed worker payload
    ("seed",          _MA): (_svc.resolved_payload_for_index, "params.seed"),
    ("seed",          _SS): (_svc.resolved_payload_for_index, "params.seed"),
    ("seed",          _NS): (_svc.resolved_payload_for_index, "params.seed"),
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
    # text_instruction — social text-generator request pin (no resolver draw/default)
    ("text_instruction", _SS): (_svc._worker_one, "ctx.params.text_instruction"),
    # text_word_limit — forwarded in _worker_one (SS/NS) and into math's canonical sampler value
    ("text_word_limit", _MA): (
        _math_params_from_resolved_payload,
        'payload.get("text_word_limit")',
    ),
    ("text_word_limit", _SS): (_svc._worker_one, "ctx.params.text_word_limit"),
    ("text_word_limit", _NS): (_svc._worker_one, "ctx.params.text_word_limit"),
    # disable_reference_fewshot — forwarded in _worker_one (SS/NS)
    ("disable_reference_fewshot", _SS): (_svc._worker_one, "ctx.params.disable_reference_fewshot"),
    ("disable_reference_fewshot", _NS): (_svc._worker_one, "ctx.params.disable_reference_fewshot"),
    # grade — forwarded directly in each sampler adapter
    ("grade", _MA): (_math_params_from_resolved_payload, 'payload["grade"]'),
    ("grade", _SS): (_ss_params_from_resolved_payload,   'payload["grade"]'),
    ("grade", _NS): (_ns_params_from_resolved_payload,   'payload["grade"]'),
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
    ("difficulty", _MA): (_math_params_from_resolved_payload, 'payload.get("difficulty")'),
    ("difficulty", _SS): (_ss_params_from_resolved_payload,   'payload.get("difficulty")'),
    ("difficulty", _NS): (_ns_params_from_resolved_payload,   'payload.get("difficulty")'),
    # content_type — forwarded directly in each sampler adapter
    ("content_type", _MA): (_math_params_from_resolved_payload, 'payload["content_type"]'),
    ("content_type", _SS): (_ss_params_from_resolved_payload,   'payload["content_type"]'),
    ("content_type", _NS): (_ns_params_from_resolved_payload,   'payload["content_type"]'),
    ("content_domain", _SS): (_ss_params_from_resolved_payload, 'payload.get("content_domain")'),
    ("target_surface", _SS): (_ss_params_from_resolved_payload, 'payload.get("target_surface")'),
    # learning_performance — forwarded directly in each sampler adapter
    ("learning_performance", _MA): (
        _math_params_from_resolved_payload,
        'payload["learning_performance"]',
    ),
    ("learning_performance", _SS): (
        _ss_params_from_resolved_payload,
        'payload["learning_performance"]',
    ),
    ("learning_performance", _NS): (
        _ns_params_from_resolved_payload,
        'payload["learning_performance"]',
    ),
    # learning_content — forwarded directly in each sampler adapter
    ("learning_content", _MA): (_math_params_from_resolved_payload, 'payload["learning_content"]'),
    ("learning_content", _SS): (_ss_params_from_resolved_payload,   'payload["learning_content"]'),
    ("learning_content", _NS): (_ns_params_from_resolved_payload,   'payload["learning_content"]'),
    # core_competency — ← KILL-SWITCH for #196
    # math and SS consume the completed core-competency payload directly.
    # NS rejects it (no proof needed).
    ("core_competency", _MA): (_math_params_from_resolved_payload, 'payload["core_competency"]'),
    ("core_competency", _SS): (_ss_params_from_resolved_payload,   'payload["core_competency"]'),
    ("math_thinking", _MA): (_math_params_from_resolved_payload, 'payload["math_thinking"]'),
    # science_competency — NS-specific, forwarded via science_competency_override
    ("science_competency", _NS): (_ns_coerce_overrides, "params.science_competency"),
    # sub_context — NS-specific, forwarded via sub_context_override
    ("sub_context", _NS): (_ns_coerce_overrides, "params.sub_context"),
    # subject_filter — math: direct; SS: via subject_override; NS: inapplicable
    ("subject_filter", _MA): (_math_params_from_resolved_payload, 'payload.get("subject_filter")'),
    ("subject_filter", _SS): (_ss_coerce_overrides,   "params.subject_filter"),
    # reporting_scale — NS-specific, forwarded directly in NS sampler adapter
    ("reporting_scale", _NS): (_ns_params_from_resolved_payload, 'payload.get("reporting_scale")'),
    # sub_question_count — forwarded directly by every subject sampler adapter
    ("sub_question_count", _MA): (
        _math_params_from_resolved_payload,
        'payload.get("sub_question_count")',
    ),
    ("sub_question_count", _SS): (
        _ss_params_from_resolved_payload,
        'payload.get("sub_question_count")',
    ),
    ("sub_question_count", _NS): (
        _ns_params_from_resolved_payload,
        'payload.get("sub_question_count")',
    ),
    # question_word_limit — SS/NS; math rejects
    ("question_word_limit", _SS): (
        _ss_params_from_resolved_payload,
        'payload.get("question_word_limit")',
    ),
    ("question_word_limit", _NS): (
        _ns_params_from_resolved_payload,
        'payload.get("question_word_limit")',
    ),
    # option_word_limit — SS/NS; math rejects
    ("option_word_limit", _SS): (
        _ss_params_from_resolved_payload,
        'payload.get("option_word_limit")',
    ),
    ("option_word_limit", _NS): (
        _ns_params_from_resolved_payload,
        'payload.get("option_word_limit")',
    ),
    # subquestion_configs — forwarded via decoded configs in _build_run_context; math rejects
    ("subquestion_configs", _SS): (_svc._build_run_context, "params.subquestion_configs"),
    ("subquestion_configs", _NS): (_svc._build_run_context, "params.subquestion_configs"),
    # coverage_mode — SS and NS: forwarded via balanced_batch in _build_run_context
    ("coverage_mode", _SS): (_svc._build_run_context, "params.coverage_mode"),
    ("coverage_mode", _NS): (_svc._build_run_context, "params.coverage_mode"),
    # core_question_callback — forwarded to the SS/NS generator adapters
    ("core_question_callback", _SS): (
        _svc._worker_one,
        "ctx.params.core_question_callback",
    ),
    ("core_question_callback", _NS): (_ns_do_generate, "core_question_callback"),
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


def _drawable_request_field(path: str) -> str:
    """Return the GenerateParams field owning a resolver drawable path."""
    head = path.split(".", 1)[0]
    return head.replace("[]", "")


def _forwarding_completeness_errors(
    fields: set[str],
    subjects: list[str],
    classification: dict[str, dict[str, tuple[str, str]]],
    forwarding_completeness: dict[tuple[str, str], tuple[str, str]],
    drawable_fields: dict[str, set[str] | frozenset[str]],
) -> list[str]:
    """Check the RESOLVED/PIN-ONLY contract against caller-supplied metadata."""
    errors: list[str] = []
    drawable_roots = {
        subject: {_drawable_request_field(path) for path in paths}
        for subject, paths in drawable_fields.items()
    }

    for subject in subjects:
        for path in drawable_fields.get(subject, set()):
            field = _drawable_request_field(path)
            if field not in fields:
                errors.append(
                    f"drawable field {path!r} for subject {subject!r} has no "
                    f"GenerateParams request field {field!r}"
                )

    for field in fields:
        for subject in subjects:
            status = classification.get(field, {}).get(subject, (None, ""))[0]
            key = (field, subject)
            entry = forwarding_completeness.get(key)
            if status != FORWARDED:
                if entry is not None:
                    errors.append(
                        f"{key!r} has RESOLVED/PIN-ONLY metadata but is not FORWARDED"
                    )
                continue
            if entry is None:
                errors.append(
                    f"({field!r}, {subject!r}) is FORWARDED but is neither "
                    "RESOLVED nor PIN-ONLY"
                )
                continue
            resolution, reason = entry
            if resolution not in {RESOLVED, PIN_ONLY}:
                errors.append(
                    f"({field!r}, {subject!r}) has invalid completeness status "
                    f"{resolution!r}; expected RESOLVED or PIN-ONLY"
                )
            elif resolution == RESOLVED and field not in drawable_roots.get(subject, set()):
                errors.append(
                    f"({field!r}, {subject!r}) is RESOLVED but {field!r} is not "
                    "in that subject's resolver drawable set"
                )
            elif resolution == PIN_ONLY and (not reason.strip() or "\n" in reason):
                errors.append(
                    f"({field!r}, {subject!r}) is PIN-ONLY but has no one-line reason"
                )

    for key in forwarding_completeness:
        field, subject = key
        if field not in fields or subject not in subjects:
            errors.append(f"stale RESOLVED/PIN-ONLY metadata for {key!r}")
    return errors


def _assert_forwarding_completeness(
    fields: set[str],
    subjects: list[str],
    classification: dict[str, dict[str, tuple[str, str]]],
    forwarding_completeness: dict[tuple[str, str], tuple[str, str]],
    drawable_fields: dict[str, set[str] | frozenset[str]],
) -> None:
    errors = _forwarding_completeness_errors(
        fields,
        subjects,
        classification,
        forwarding_completeness,
        drawable_fields,
    )
    assert not errors, "Incomplete forwarded-field classification:\n" + "\n".join(
        f"  {error}" for error in errors
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

_ALL_SUBJECTS = list(SUBJECTS)
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


def test_forwarded_fields_are_resolved_or_pin_only() -> None:
    """Every forwarded contract field must have an explicit completeness status."""
    _assert_forwarding_completeness(
        set(_ALL_FIELDS),
        _ALL_SUBJECTS,
        CLASSIFICATION,
        FORWARDING_COMPLETENESS,
        DRAWABLE_FIELDS,
    )


def test_synthetic_forwarded_field_requires_resolved_or_pin_only_metadata() -> None:
    fields = {"new_field"}
    classification = {"new_field": {_MA: (FORWARDED, "")}}

    with pytest.raises(AssertionError) as exc_info:
        _assert_forwarding_completeness(
            fields,
            [_MA],
            classification,
            {},
            {_MA: set()},
        )

    assert "new_field" in str(exc_info.value)
    assert "RESOLVED nor PIN-ONLY" in str(exc_info.value)


def test_synthetic_drawable_without_request_field_is_reported() -> None:
    with pytest.raises(AssertionError) as exc_info:
        _assert_forwarding_completeness(
            {"grade"},
            [_MA],
            {"grade": {_MA: (FORWARDED, "")}},
            {("grade", _MA): (RESOLVED, "")},
            {_MA: {"grade", "new_drawn_value"}},
        )

    assert "new_drawn_value" in str(exc_info.value)
    assert "GenerateParams" in str(exc_info.value)


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


def test_no_extra_subject_classifications_beyond_registry() -> None:
    """A removed subject must not leave stale field classifications behind."""
    extra = sorted(
        {
            subject
            for classifications in CLASSIFICATION.values()
            for subject in classifications
            if subject not in _ALL_SUBJECTS
        }
    )
    assert not extra, "CLASSIFICATION contains unknown subjects: " + ", ".join(extra)


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
    'core_competency=overrides["core_competency_override"]' from the resolved SS adapter)
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
    # +2 ICCS pins + NS figure policy + social text instruction
    assert forwarded == 104, f"Expected 104 FORWARDED, got {forwarded}"
    assert rejected     == 10,  f"Expected 10 REJECTED, got {rejected}"  # +4 SS-only fields + text instruction
    assert inapplicable == 27, f"Expected 27 INAPPLICABLE, got {inapplicable}"

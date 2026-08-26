"""Resolve partial generation payloads into pinned sampler values.

The resolver is deliberately independent of HTTP and returns the same shape
for every subject.  A field is a pin when it is present and non-empty; only
blank fields are passed to a subject sampler.  Draw paths use the sampler's
serialized field names (for example ``題目內容類型``).  A single payload uses
the top-level path; batch entries are prefixed with
``per_question_params[i].``; a slot path adds
``subquestion_configs[j].`` after that prefix.  Request aliases such as
``content_type`` are accepted, but the reported paths remain the sampler
paths so ``redraws`` can be replayed through the same keyed streams.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from src.natural_sciences.sampler import (
    _SUB_CONTEXT_ADMITTED_BY,
    _matching_subcontexts,
)
from src.natural_sciences.sampler import (
    sample_params as sample_natural_params,
)
from src.natural_sciences.schemas import (
    QuestionContext as NaturalQuestionContext,
)
from src.natural_sciences.schemas import (
    QuestionSetType as NaturalQuestionSetType,
)
from src.natural_sciences.schemas import (
    QuestionSubContext,
    ScienceCompetency,
)
from src.natural_sciences.schemas import (
    QuestionType as NaturalQuestionType,
)
from src.sampler import sample_params as sample_math_params
from src.schemas import (
    MathThinking,
)
from src.schemas import (
    QuestionContext as MathQuestionContext,
)
from src.schemas import (
    QuestionSetType as MathQuestionSetType,
)
from src.schemas import (
    QuestionStyle as MathQuestionStyle,
)
from src.schemas import (
    QuestionType as MathQuestionType,
)
from src.social_studies.sampler import sample_params as sample_social_params
from src.social_studies.schemas import (
    CoreCompetency as SocialCoreCompetency,
)
from src.social_studies.schemas import (
    QuestionContext as SocialQuestionContext,
)
from src.social_studies.schemas import (
    QuestionSetType as SocialQuestionSetType,
)
from src.social_studies.schemas import (
    QuestionSubject as SocialQuestionSubject,
)
from src.social_studies.schemas import (
    QuestionType as SocialQuestionType,
)


@dataclass(frozen=True)
class ResolveResult:
    """Completed payload plus the canonical paths filled by the resolver."""

    payload: dict[str, Any]
    drawn: list[str]


class ResolveConflictError(ValueError):
    """A pinned parent/child pair that cannot be resolved safely."""

    def __init__(self, errors: list[dict[str, str]]) -> None:
        self.errors = errors
        super().__init__(str(errors))


def _blank(value: Any) -> bool:
    if isinstance(value, str):
        return not value.strip()
    return value is None or value == []


def _value(item: Any) -> Any:
    return getattr(item, "value", item)


def _as_enum(value: Any, enum_cls: type) -> Any:
    if _blank(value):
        return None
    return value if isinstance(value, enum_cls) else enum_cls(value)


def _as_enum_list(values: Any, enum_cls: type) -> list | None:
    if _blank(values):
        return None
    if not isinstance(values, list):
        values = [values]
    values = [value for value in values if not _blank(value)]
    if not values:
        return None
    return [_as_enum(value, enum_cls) for value in values]


_TOP_LEVEL_ALIASES = {
    "context": "情境",
    "set_type": "題型種類",
    "q_type": "題型",
    "content_type": "題目內容類型",
    "math_thinking": "數學思考",
    "subject_filter": "科目",
    "sub_context": "情境子類別",
    "science_competency": "科學能力",
    "learning_content": "學習內容",
    "learning_performance": "學習表現",
    "core_competency": "核心素養",
}


def _canonical_local_path(path: str) -> str:
    if path.startswith("subquestion_configs["):
        if path.endswith(".cognitive_process"):
            return path[: -len("cognitive_process")] + "認知歷程"
        return path
    return _TOP_LEVEL_ALIASES.get(path, path)


def _local_redraws(
    redraws: dict[str, int] | None,
    *,
    index: int,
    batch: bool,
) -> dict[str, int]:
    """Strip a batch prefix and normalize request aliases for one sampler."""
    result: dict[str, int] = {}
    prefix = f"per_question_params[{index}]."
    first_prefix = "per_question_params[0]."
    for raw_path, counter in (redraws or {}).items():
        path = raw_path
        if path.startswith(prefix):
            path = path[len(prefix) :]
        elif path.startswith("per_question_params["):
            if not (not batch and path.startswith(first_prefix)):
                continue
            path = path[len(first_prefix) :]
        elif batch and index != 0:
            continue
        result[_canonical_local_path(path)] = counter
    return result


def _decode_rows(value: Any, field: str) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field} must be a JSON array") from exc
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{field} must be an array of objects")
    return [dict(item) for item in value]


def _top_drawn(payload: dict[str, Any], fields: list[tuple[str, str]]) -> list[str]:
    return [canonical for request_name, canonical in fields if _blank(payload.get(request_name))]


def _math_thinking_override(value: Any) -> list[MathThinking] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not 1 <= len(value) <= 3:
        raise ValueError("math_thinking must be a list with 1 to 3 values")
    try:
        return [
            item if isinstance(item, MathThinking) else MathThinking(item)
            for item in value
        ]
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "math_thinking contains an invalid value; allowed values are 形成, 運用, 詮釋評估"
        ) from exc


def _wire_social_config(config: Any, original: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(original)
    question_type = _value(getattr(config, "question_type", None))
    if question_type is not None:
        result["question_type"] = question_type
    cognitive_process = getattr(config, "認知歷程", None)
    if cognitive_process is not None:
        key = "認知歷程" if "認知歷程" in original else "cognitive_process"
        result[key] = cognitive_process
    return result


def _wire_natural_config(config: Any, original: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(original)
    question_type = _value(getattr(config, "question_type", None))
    if question_type is not None:
        result["question_type"] = question_type
    reporting_scale = getattr(config, "reporting_scale", None)
    if reporting_scale is not None:
        result["reporting_scale"] = reporting_scale
    return result


def _resolve_math(
    payload: dict[str, Any], redraws: dict[str, int] | None
) -> ResolveResult:
    subject_filter = payload.get("subject_filter")
    if isinstance(subject_filter, list):
        subject_filter = subject_filter[0] if subject_filter else None

    sampled = sample_math_params(
        grade=payload.get("grade"),
        style=_as_enum_list(payload.get("style"), MathQuestionStyle),
        context=_as_enum_list(payload.get("context"), MathQuestionContext),
        set_type=(
            _as_enum(payload["set_type"], MathQuestionSetType)
            if payload.get("set_type") is not None
            else None
        ),
        q_type=_as_enum_list(payload.get("q_type"), MathQuestionType),
        seed=payload.get("seed"),
        math_thinking=_math_thinking_override(payload.get("math_thinking")),
        core_competency=(
            None
            if _blank(payload.get("core_competency"))
            else payload["core_competency"]
        ),
        learning_content=(
            None
            if _blank(payload.get("learning_content"))
            else payload["learning_content"]
        ),
        learning_performance=(
            None
            if _blank(payload.get("learning_performance"))
            else payload["learning_performance"]
        ),
        content_type=(
            None if _blank(payload.get("content_type")) else payload["content_type"]
        ),
        subject_filter=subject_filter,
        sub_question_count=payload.get("sub_question_count"),
        text_word_limit=payload.get("text_word_limit"),
        difficulty=payload.get("difficulty"),
        redraws=redraws,
    )

    completed = deepcopy(payload)
    completed.update(
        {
            "grade": sampled.grade,
            "context": [_value(item) for item in sampled.情境],
            "set_type": _value(sampled.題型種類),
            "q_type": [_value(sampled.題型)],
            "style": [_value(sampled.style)],
            "math_thinking": [_value(item) for item in sampled.數學思考],
            "learning_content": [item.編碼 for item in sampled.學習內容],
            "learning_performance": [item.編碼 for item in sampled.學習表現],
            "core_competency": list(sampled.核心素養),
            "content_type": sampled.題目內容類型,
        }
    )
    if sampled.sub_question_count is not None:
        completed["sub_question_count"] = sampled.sub_question_count
    fields = [
        ("grade", "grade"),
        ("context", "情境"),
        ("set_type", "題型種類"),
        ("q_type", "題型"),
        ("math_thinking", "數學思考"),
        ("learning_content", "學習內容"),
        ("learning_performance", "學習表現"),
        ("core_competency", "核心素養"),
        ("content_type", "題目內容類型"),
        ("style", "style"),
    ]
    drawn = _top_drawn(payload, fields)
    if sampled.sub_question_count is not None and _blank(payload.get("sub_question_count")):
        drawn.append("sub_question_count")
    if not drawn:
        return ResolveResult(payload=deepcopy(payload), drawn=[])
    return ResolveResult(payload=completed, drawn=drawn)


def _resolve_social(
    payload: dict[str, Any], redraws: dict[str, int] | None
) -> ResolveResult:
    configs = None
    if "subquestion_configs" in payload and not _blank(payload["subquestion_configs"]):
        configs = _decode_rows(payload["subquestion_configs"], "subquestion_configs")
    elif "subquestion_configs" in payload:
        configs = []

    subject_filter = payload.get("subject_filter")
    subject_values = _as_enum_list(subject_filter, SocialQuestionSubject)
    sampled = sample_social_params(
        grade=payload.get("grade"),
        context=_as_enum_list(payload.get("context"), SocialQuestionContext),
        set_type=_as_enum(payload.get("set_type"), SocialQuestionSetType),
        q_type=_as_enum_list(payload.get("q_type"), SocialQuestionType),
        subject=subject_values,
        core_competency=_as_enum_list(payload.get("core_competency"), SocialCoreCompetency),
        learning_content=(
            None if _blank(payload.get("learning_content")) else payload["learning_content"]
        ),
        learning_performance=(
            None
            if _blank(payload.get("learning_performance"))
            else payload["learning_performance"]
        ),
        content_type=(
            None if _blank(payload.get("content_type")) else payload["content_type"]
        ),
        content_domain=payload.get("content_domain"),
        target_surface=payload.get("target_surface"),
        seed=payload.get("seed"),
        sub_question_count=payload.get("sub_question_count"),
        question_word_limit=payload.get("question_word_limit"),
        option_word_limit=payload.get("option_word_limit"),
        subquestion_configs=configs,
        difficulty=payload.get("difficulty"),
        allow_duplicate_figure_kinds=payload.get("allow_duplicate_figure_kinds", False),
        redraws=redraws,
    )

    completed = deepcopy(payload)
    completed.update(
        {
            "grade": sampled.grade,
            "context": [_value(item) for item in sampled.情境],
            "set_type": _value(sampled.題型種類),
            "content_type": sampled.題目內容類型,
            "subject_filter": [_value(sampled.科目)],
            "content_domain": _value(sampled.內容領域),
            "core_competency": [_value(item) for item in sampled.核心素養],
            "learning_content": list(sampled.學習內容_pool),
            "learning_performance": list(sampled.學習表現_pool),
        }
    )
    if payload.get("sub_question_count") is None or not _blank(payload.get("q_type")):
        completed["q_type"] = [_value(item) for item in sampled.題型]
    if "target_surface" in payload:
        completed["target_surface"] = sampled.target_surface
    if sampled.sub_question_count is not None:
        completed["sub_question_count"] = sampled.sub_question_count
    sampled_configs = list(sampled.subquestion_configs)
    if "subquestion_configs" in payload or sampled_configs:
        completed["subquestion_configs"] = [
            _wire_social_config(
                config,
                configs[index] if configs is not None and index < len(configs) else {},
            )
            for index, config in enumerate(sampled_configs)
        ]

    fields = [
        ("grade", "grade"),
        ("context", "情境"),
        ("set_type", "題型種類"),
        ("content_type", "題目內容類型"),
        ("subject_filter", "科目"),
        ("content_domain", "內容領域"),
        ("core_competency", "核心素養"),
        ("learning_content", "學習內容"),
        ("learning_performance", "學習表現"),
    ]
    drawn = _top_drawn(payload, fields)
    if payload.get("sub_question_count") is None and _blank(payload.get("q_type")):
        drawn.append("題型")
    original_configs = configs or []
    for index, config in enumerate(sampled_configs):
        original = original_configs[index] if index < len(original_configs) else {}
        if _blank(original.get("question_type")) and getattr(config, "question_type", None):
            drawn.append(f"subquestion_configs[{index}].question_type")
        if _blank(original.get("cognitive_process", original.get("認知歷程"))) and getattr(
            config, "認知歷程", None
        ):
            drawn.append(f"subquestion_configs[{index}].認知歷程")
    if not drawn:
        return ResolveResult(payload=deepcopy(payload), drawn=[])
    return ResolveResult(payload=completed, drawn=drawn)


def _validate_natural_parent(payload: dict[str, Any]) -> None:
    context = payload.get("context")
    sub_context = _value(payload.get("sub_context"))
    if _blank(context) or _blank(sub_context):
        return
    contexts = context if isinstance(context, list) else [context]
    contexts = [_value(item) for item in contexts if not _blank(item)]
    if not contexts:
        return
    admitted_parents = _SUB_CONTEXT_ADMITTED_BY.get(sub_context, [])
    matching_subcontexts = _matching_subcontexts(set(contexts))
    if admitted_parents and not any(
        candidate.value == sub_context for candidate in matching_subcontexts
    ):
        raise ResolveConflictError(
            [
                {
                    "field": "sub_context",
                    "code": "incompatible_parent",
                    "parent": admitted_parents[0],
                }
            ]
        )


def _resolve_natural(
    payload: dict[str, Any], redraws: dict[str, int] | None
) -> ResolveResult:
    _validate_natural_parent(payload)
    configs = None
    if "subquestion_configs" in payload and not _blank(payload["subquestion_configs"]):
        configs = _decode_rows(payload["subquestion_configs"], "subquestion_configs")
    elif "subquestion_configs" in payload:
        configs = []

    sampled = sample_natural_params(
        grade=payload.get("grade"),
        context=_as_enum_list(payload.get("context"), NaturalQuestionContext),
        sub_context=_as_enum(payload.get("sub_context"), QuestionSubContext),
        set_type=_as_enum(payload.get("set_type"), NaturalQuestionSetType),
        q_type=_as_enum_list(payload.get("q_type"), NaturalQuestionType),
        science_competency=_as_enum_list(payload.get("science_competency"), ScienceCompetency),
        learning_content=(
            None if _blank(payload.get("learning_content")) else payload["learning_content"]
        ),
        learning_performance=(
            None
            if _blank(payload.get("learning_performance"))
            else payload["learning_performance"]
        ),
        content_type=(
            None if _blank(payload.get("content_type")) else payload["content_type"]
        ),
        seed=payload.get("seed"),
        sub_question_count=payload.get("sub_question_count"),
        question_word_limit=payload.get("question_word_limit"),
        option_word_limit=payload.get("option_word_limit"),
        subquestion_configs=configs,
        difficulty=payload.get("difficulty"),
        reporting_scale=payload.get("reporting_scale"),
        redraws=redraws,
    )

    completed = deepcopy(payload)
    completed.update(
        {
            "grade": sampled.grade,
            "context": [_value(item) for item in sampled.情境],
            "sub_context": _value(sampled.情境子類別),
            "set_type": _value(sampled.題型種類),
            "science_competency": [_value(item) for item in sampled.科學能力],
            "content_type": sampled.題目內容類型,
            "learning_content": list(sampled.學習內容_pool),
            "learning_performance": list(sampled.學習表現_pool),
        }
    )
    if payload.get("sub_question_count") is None or not _blank(payload.get("q_type")):
        completed["q_type"] = [_value(sampled.題型)]
    if sampled.sub_question_count is not None:
        completed["sub_question_count"] = sampled.sub_question_count

    sampled_configs = list(sampled.subquestion_configs)
    if "subquestion_configs" in payload or sampled_configs:
        completed["subquestion_configs"] = [
            _wire_natural_config(
                config,
                configs[index] if configs is not None and index < len(configs) else {},
            )
            for index, config in enumerate(sampled_configs)
        ]

    fields = [
        ("grade", "grade"),
        ("context", "情境"),
        ("sub_context", "情境子類別"),
        ("set_type", "題型種類"),
        ("science_competency", "科學能力"),
        ("content_type", "題目內容類型"),
        ("learning_performance", "學習表現"),
        ("learning_content", "學習內容"),
    ]
    if payload.get("sub_question_count") is None:
        fields.insert(4, ("q_type", "題型"))
    drawn = _top_drawn(payload, fields)
    original_configs = configs or []
    for index, config in enumerate(sampled_configs):
        original = original_configs[index] if index < len(original_configs) else {}
        if _blank(original.get("question_type")) and getattr(config, "question_type", None):
            drawn.append(f"subquestion_configs[{index}].question_type")
        if _blank(original.get("reporting_scale")) and getattr(config, "reporting_scale", None):
            drawn.append(f"subquestion_configs[{index}].reporting_scale")
    if not drawn:
        return ResolveResult(payload=deepcopy(payload), drawn=[])
    return ResolveResult(payload=completed, drawn=drawn)


def _resolve_one(
    payload: dict[str, Any], redraws: dict[str, int] | None
) -> ResolveResult:
    subject = payload.get("subject", "math")
    if subject == "math":
        return _resolve_math(payload, redraws)
    if subject == "social_studies":
        return _resolve_social(payload, redraws)
    if subject == "natural_sciences":
        return _resolve_natural(payload, redraws)
    raise ValueError(f"unsupported subject: {subject}")


def resolve(
    payload: dict[str, Any], *, redraws: dict[str, int] | None = None
) -> ResolveResult:
    """Resolve one whole payload; supplied values are pins and blanks are drawn.

    ``payload`` is copied before sampling.  For ``count == 1`` without a
    ``per_question_params`` array, field paths are top-level sampler paths.
    Otherwise each row is resolved with seed ``seed + index`` unless that row
    supplies its own seed, and paths are prefixed with
    ``per_question_params[index].``.  Slot paths then use
    ``subquestion_configs[index].field``.  ``redraws`` uses those same paths;
    request aliases are accepted as input but canonical sampler names are
    returned in ``drawn``.
    """
    if not isinstance(payload, dict):
        raise TypeError("payload must be an object")

    raw_rows = payload.get("per_question_params")
    has_rows = raw_rows is not None
    if has_rows:
        rows = _decode_rows(raw_rows, "per_question_params")
        count = payload.get("count", len(rows))
    else:
        count = payload.get("count", 1)

    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 10:
        raise ValueError("count must be between 1 and 10")

    if has_rows:
        if count != len(rows):
            raise ValueError(
                f"per_question_params array length {len(rows)} must equal count {count}"
            )
    else:
        rows = [{} for _ in range(count)]

    batch = has_rows or count > 1
    if not batch:
        result = _resolve_one(deepcopy(payload), _local_redraws(redraws, index=0, batch=False))
        return result

    base = {
        key: value
        for key, value in payload.items()
        if key not in {"subject", "count", "per_question_params", "redraws"}
    }
    resolved_rows: list[dict[str, Any]] = []
    drawn: list[str] = []
    for index, row in enumerate(rows):
        worker_payload = deepcopy(base)
        worker_payload.update(deepcopy(row))
        worker_payload["subject"] = payload.get("subject", "math")
        explicit_seed = row.get("seed") if not _blank(row.get("seed")) else None
        base_seed = payload.get("seed")
        worker_seed = explicit_seed
        if worker_seed is None and base_seed is not None:
            worker_seed = base_seed + index
        if worker_seed is not None:
            worker_payload["seed"] = worker_seed
        try:
            result = _resolve_one(
                worker_payload,
                _local_redraws(redraws, index=index, batch=True),
            )
        except ResolveConflictError as exc:
            prefix = f"per_question_params[{index}]."
            errors = [
                {
                    **error,
                    "field": (
                        error["field"]
                        if error["field"].startswith(prefix)
                        else prefix + error["field"]
                    ),
                }
                for error in exc.errors
            ]
            raise ResolveConflictError(errors) from exc
        resolved_row = deepcopy(result.payload)
        resolved_row.pop("subject", None)
        resolved_rows.append(resolved_row)
        drawn.extend(
            f"per_question_params[{index}].{path}" for path in result.drawn
        )

    completed = deepcopy(payload)
    completed["per_question_params"] = resolved_rows
    return ResolveResult(payload=completed, drawn=drawn)

import { MESSAGES, type Lang } from "../i18n/messages";

/**
 * A single field-addressed resolver error, matching the server's `/resolve`
 * (and preview/generation) 422 detail shape `{field, code, parent}`.
 *
 * Deliberately looser than the generated `ResolveFieldError` in
 * `../api/generated/contract.ts` — that type's `code` union may lag behind
 * the server (see #835/#834: `no_admitting_parent` was added server-side
 * before the generated contract picked it up). Callers that only have the
 * generated type may pass it here; it structurally satisfies this interface.
 */
export interface ResolverFieldErrorLike {
  field: string;
  code: string;
  parent?: string;
}

/**
 * Type-guard for one field-addressed resolver error `{field, code, parent?}`.
 * Shared by `client.ts` (parsing an array-valued HTTP `detail`) and any
 * caller that needs to duck-type an unknown value (e.g. `ParamForm.tsx`
 * inspecting a caught error without importing the `ApiError` class) —
 * see task-7-report.md for why the latter avoids a runtime `client.ts`
 * import.
 */
export function isResolverFieldErrorLike(value: unknown): value is ResolverFieldErrorLike {
  return (
    value !== null
    && typeof value === "object"
    && typeof (value as Record<string, unknown>).field === "string"
    && typeof (value as Record<string, unknown>).code === "string"
    && (
      (value as Record<string, unknown>).parent === undefined
      || typeof (value as Record<string, unknown>).parent === "string"
    )
  );
}

/** The two 釘選-narrowing error codes this module knows how to render as a sentence. */
type ReadableResolverErrorCode = "incompatible_parent" | "no_admitting_parent";

const READABLE_CODES: ReadonlySet<string> = new Set<ReadableResolverErrorCode>([
  "incompatible_parent",
  "no_admitting_parent",
]);

/**
 * The four 社會 科目 values (ADR: docs/superpowers/plans/2026-09-17-833-841-
 * dependent-parameter-narrowing.md, Global Constraints / task-7-brief.md
 * parent-kind ruling). Fixed, closed enum from the curriculum domain — not a
 * prefix heuristic like the retired `isPublicSocialStudiesCode`.
 */
const SOCIAL_STUDIES_SUBJECT_VALUES: ReadonlySet<string> = new Set([
  "歷史",
  "地理",
  "公民與社會",
  "跨科",
]);

type ParentKind = "科目" | "內容領域" | "情境";

export interface ParsedResolverFieldPath {
  /** 1-based 題組 position from a `per_question_params[i].` prefix, if present. */
  questionNumber?: number;
  /** 1-based 小題 position from a `subquestion_configs[j].` prefix, if present. */
  subquestionNumber?: number;
  /** The field name with any `per_question_params[i].` / `subquestion_configs[j].` prefixes stripped. */
  baseField: string;
}

const PER_QUESTION_PREFIX = /^per_question_params\[(\d+)\]\.(.*)$/;
const SUBQUESTION_PREFIX = /^subquestion_configs\[(\d+)\]\.(.*)$/;

/**
 * Parse the resolver's field-path addressing into 1-based question/小題
 * positions plus the bare field name.
 *
 * `per_question_params[i]` → question i+1; `subquestion_configs[j]` → 小題
 * j+1 (task-7-brief.md "Position" ruling). Either, both, or neither prefix
 * may be present.
 */
export function parseResolverFieldPath(field: string): ParsedResolverFieldPath {
  let rest = field;
  let questionNumber: number | undefined;
  let subquestionNumber: number | undefined;

  const questionMatch = rest.match(PER_QUESTION_PREFIX);
  if (questionMatch) {
    questionNumber = Number(questionMatch[1]) + 1;
    rest = questionMatch[2];
  }

  const subquestionMatch = rest.match(SUBQUESTION_PREFIX);
  if (subquestionMatch) {
    subquestionNumber = Number(subquestionMatch[1]) + 1;
    rest = subquestionMatch[2];
  }

  return { questionNumber, subquestionNumber, baseField: rest };
}

function msg(lang: Lang, key: string): string {
  return MESSAGES[lang][key] ?? key;
}

function childFieldLabel(baseField: string, lang: Lang): string {
  switch (baseField) {
    case "learning_content":
      return msg(lang, "resolver_error.child_learning_content");
    case "learning_performance":
      return msg(lang, "resolver_error.child_learning_performance");
    case "sub_context":
      return msg(lang, "resolver_error.child_sub_context");
    default:
      return baseField;
  }
}

function parentKindLabel(kind: ParentKind, lang: Lang): string {
  switch (kind) {
    case "科目":
      return msg(lang, "resolver_error.parent_subject");
    case "內容領域":
      return msg(lang, "resolver_error.parent_content_domain");
    case "情境":
      return msg(lang, "resolver_error.parent_context");
  }
}

/**
 * Resolve which parent kind (科目 / 內容領域 / 情境) an error is about.
 *
 * Parent-kind ruling (task-7-brief.md):
 * - `no_admitting_parent`: the parent field IS the kind — its value is the
 *   literal string "科目" or "內容領域".
 * - `incompatible_parent`: infer from the field — `sub_context` → 情境;
 *   otherwise 科目 when the parent value is one of the four 社會 科目
 *   values; else 內容領域.
 *
 * Returns null when the error's code isn't one this module formats, or the
 * shape is unexpectedly missing what the ruling needs (defensive; should not
 * happen for well-formed server output).
 */
export function resolveParentKind(error: ResolverFieldErrorLike): ParentKind | null {
  if (error.code === "no_admitting_parent") {
    return error.parent === "科目" || error.parent === "內容領域" ? error.parent : null;
  }
  if (error.code === "incompatible_parent") {
    const { baseField } = parseResolverFieldPath(error.field);
    if (baseField === "sub_context") return "情境";
    if (error.parent !== undefined && SOCIAL_STUDIES_SUBJECT_VALUES.has(error.parent)) return "科目";
    return "內容領域";
  }
  return null;
}

function formatPosition(parsed: ParsedResolverFieldPath, lang: Lang): string {
  const { questionNumber: q, subquestionNumber: s } = parsed;
  if (q !== undefined && s !== undefined) {
    return msg(lang, "resolver_error.position_question_subquestion")
      .replace("{q}", String(q))
      .replace("{s}", String(s));
  }
  if (q !== undefined) {
    return msg(lang, "resolver_error.position_question").replace("{q}", String(q));
  }
  if (s !== undefined) {
    return msg(lang, "resolver_error.position_subquestion").replace("{s}", String(s));
  }
  return "";
}

/**
 * Format one field-addressed resolver error as a readable sentence.
 *
 * Only `incompatible_parent` and `no_admitting_parent` are formatted this
 * way; `unresolved` (and any other/unknown code) returns null so callers
 * fall back to their existing text for it (that text is unchanged by #835).
 *
 * Exported (in addition to {@link formatResolverFieldErrors}) so a single
 * error can be rendered inline — e.g. per-field hint text in later tickets.
 */
export function formatResolverFieldError(error: ResolverFieldErrorLike, lang: Lang): string | null {
  if (!READABLE_CODES.has(error.code)) return null;

  const parentKind = resolveParentKind(error);
  if (parentKind === null) return null;

  const parsed = parseResolverFieldPath(error.field);
  const position = formatPosition(parsed, lang);
  const child = childFieldLabel(parsed.baseField, lang);
  const parentKindText = parentKindLabel(parentKind, lang);

  const sentence = error.code === "incompatible_parent"
    ? msg(lang, "resolver_error.incompatible_parent")
      .replace("{position}", position)
      .replace("{child}", child)
      .replace("{parentKind}", parentKindText)
      .replace("{parent}", error.parent ?? "")
    : msg(lang, "resolver_error.no_admitting_parent")
      .replace("{position}", position)
      .replace("{child}", child)
      .replace("{parentKind}", parentKindText);

  // en-US templates use a lowercase "the selected …" so the sentence reads
  // naturally whether or not a capitalised position clause precedes it;
  // capitalise the leading letter here when nothing did (zh-TW has no case).
  return lang === "en-US" ? sentence.charAt(0).toUpperCase() + sentence.slice(1) : sentence;
}

/**
 * Format a field-addressed resolver error array as one readable message.
 *
 * The public entry point for all three web surfaces (發送前確認 resolver
 * banner, prompt-preview errors, and the SSE generation error) — see
 * `client.ts` / `useGenerate.ts` / `ParamForm.tsx`.
 *
 * Returns null (rather than a partial message) when the array is empty or
 * any entry isn't a readable code (`unresolved`, or anything unrecognised):
 * callers should treat null as "use your existing/legacy text for this
 * error" — `unresolved` and request-validation errors keep their current
 * text (task-7-brief.md), so a batch mixing them with the new codes is left
 * entirely to the caller's fallback rather than half-translated.
 */
export function formatResolverFieldErrors(
  errors: readonly ResolverFieldErrorLike[],
  lang: Lang,
): string | null {
  if (errors.length === 0) return null;
  const sentences: string[] = [];
  for (const error of errors) {
    const sentence = formatResolverFieldError(error, lang);
    if (sentence === null) return null;
    sentences.push(sentence);
  }
  return sentences.join(" ");
}

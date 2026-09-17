import { MESSAGES, type Lang } from "../i18n/messages";
import type { AdmittedParentEntry } from "./admittedBy";

/**
 * A group of 釘選 codes that share one narrowing "source": either the
 * 題組/request-level 學習內容+學習表現 selections (no `subquestionNumber`), or
 * one 各小題配置 row's own `learning_content`/`learning_performance` pins
 * (`subquestionNumber` is that row's 1-based position).
 */
export interface PinnedCodeGroup {
  codes: readonly string[];
  /** 1-based 小題 position, present only when `codes` came from a 各小題配置 row. */
  subquestionNumber?: number;
}

/** One 釘選 code that narrows a parent control, with its optional 小題 position. */
export interface ConstrainingCode {
  code: string;
  subquestionNumber?: number;
}

export interface ParentNarrowingResult {
  /** Values (from the caller's `allValues`) that should be shown disabled. */
  disabledValues: Set<string>;
  /**
   * The 釘選 codes that actually narrow the range (each excludes at least
   * one value of `allValues`), in the order encountered. A code lacking
   * admission data for `parentKey` — or one whose admission set covers every
   * value — never appears here and never contributes to `disabledValues`.
   */
  constrainingCodes: ConstrainingCode[];
}

/**
 * Compute which of a parent control's `allValues` should be disabled because
 * at least one 釘選 code does not admit them, and which pinned codes are
 * responsible (for a hint).
 *
 * Admission comes only from `lookupEntry(code)?.admitted_by?.[parentKey]`
 * (ADR 0020) — never a prefix table. A code with no admission data for
 * `parentKey` (e.g. a 學習表現 code when `parentKey` is "內容領域") is
 * silently skipped rather than disabling everything or nothing incorrectly:
 * this is how "學習表現 never disables 內容領域" and "歷/地 codes never
 * disable 內容領域" fall out for free — those rows simply carry no
 * `admitted_by["內容領域"]` tag.
 *
 * `allValues` should be the parent's full, unnarrowed candidate list — the
 * blank/"全部"/"隨機" option is never part of it, so it is never disabled by
 * this function (callers render it separately and unconditionally enabled).
 *
 * Reused by Tasks 9–10 for their own dependent-parameter controls: pass the
 * new parent's `allValues`, its `admitted_by` key, and the relevant pinned
 * code groups.
 */
export function computeParentNarrowing<T extends AdmittedParentEntry>(
  allValues: readonly string[],
  parentKey: string,
  pinnedGroups: readonly PinnedCodeGroup[],
  lookupEntry: (code: string) => T | undefined,
): ParentNarrowingResult {
  const disabledValues = new Set<string>();
  const constrainingCodes: ConstrainingCode[] = [];

  for (const group of pinnedGroups) {
    for (const code of group.codes) {
      const admitted = lookupEntry(code)?.admitted_by?.[parentKey];
      if (!Array.isArray(admitted)) continue;
      const excluded = allValues.filter((value) => !admitted.includes(value));
      if (excluded.length === 0) continue;
      excluded.forEach((value) => disabledValues.add(value));
      constrainingCodes.push({ code, subquestionNumber: group.subquestionNumber });
    }
  }

  return { disabledValues, constrainingCodes };
}

function msg(lang: Lang, key: string): string {
  return MESSAGES[lang][key] ?? key;
}

function formatConstrainingCode(entry: ConstrainingCode, lang: Lang): string {
  if (entry.subquestionNumber === undefined) return entry.code;
  return msg(lang, "form.narrow_hint_subquestion_code")
    .replace("{n}", String(entry.subquestionNumber))
    .replace("{code}", entry.code);
}

/**
 * Format the one hint line naming the codes narrowing a control, or `null`
 * when nothing narrows it (callers render no hint element in that case).
 *
 * `templateKey` supplies the control-specific sentence (its `{codes}`
 * placeholder is replaced with the joined, positioned code list); Tasks 9–10
 * can reuse {@link computeParentNarrowing}'s output with their own template
 * key rather than duplicating the join/positioning logic here.
 */
export function formatNarrowingHint(
  constrainingCodes: readonly ConstrainingCode[],
  lang: Lang,
  templateKey: string,
): string | null {
  if (constrainingCodes.length === 0) return null;
  const separator = lang === "en-US" ? ", " : "、";
  const codesText = constrainingCodes
    .map((entry) => formatConstrainingCode(entry, lang))
    .join(separator);
  return msg(lang, templateKey).replace("{codes}", codesText);
}

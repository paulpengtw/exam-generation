/**
 * Issue #750 — C1 × S0 legacy stream adapter.
 *
 * Stores received items by opaque id (stable_id / question_id / question.id /
 * or a generated key). Only consistent explicit index↔id evidence resolves an
 * original position; arrival order never substitutes for an explicit index.
 * Items without a resolved index are labeled 原題序未知 in the UI.
 *
 * Documented C0/S0 defects (NOT fixed here — unfixed old clients remain C0):
 *  – C0 assigns index by arrival order of result events (nextFinalIndexRef.current++)
 *  – C0 does not deduplicate duplicate result events
 *  – C0 does not track consistent index↔id mappings
 *  – C0 may let a later result overwrite an earlier draft at the same position
 *
 * Rules enforced by this adapter:
 *  – A draft with resolvedIndex is NOT overwritten content-wise by a final from
 *    a different id.  (B's final never replaces A's draft for a different id.)
 *  – A duplicate final (same id, already isFinal) is silently ignored.
 *  – done sets done=true; it does NOT constitute per-question terminal evidence.
 *  – An inconsistent mapping (same id → different index, or same index → different id)
 *    silently discards the candidate mapping; the item stays at 原題序未知.
 *  – No placeholder cards are built without an explicit index↔id mapping.
 *  – Arrival after done is silently discarded (stream is sealed).
 */

import type {
  DraftPhase,
  ExamQuestion,
  FigurePolicyTrailEntry,
  ReferenceExampleRecordShape,
  VerificationTrailEntry,
} from "../hooks/useGenerate";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type LegacyItem = {
  /** Opaque id used as the primary key in this state. */
  id: string;
  question: ExamQuestion;
  phase: DraftPhase;
  isFinal: boolean;
  /**
   * The confirmed original 0-based batch index, or null (原題序未知).
   * Set only when consistent explicit index↔id evidence arrives; never
   * inferred from arrival order.
   */
  resolvedIndex: number | null;
  contentRevision: number | null;
  trail: readonly VerificationTrailEntry[];
  figurePolicyTrail: readonly FigurePolicyTrailEntry[];
  referenceExampleRecord: ReferenceExampleRecordShape | undefined;
};

export type LegacyAdapterState = {
  /** Content keyed by opaque id. Insertion order is preserved. */
  readonly items: ReadonlyMap<string, LegacyItem>;
  /** Number of unique finals received (not total items). */
  readonly finalCount: number;
  /**
   * From the generate request params (count field), NOT from a server manifest.
   * Displayed as "請求總數 N" in the UI — never as a confirmed manifest count.
   */
  readonly requestTotal: number | null;
  /** Set when a done event is received. Does NOT imply per-question terminal. */
  readonly done: boolean;
  // --- internal ---
  /** Auto-increment counter for generating synthetic ids. */
  readonly _idCounter: number;
  /** Confirmed id → index mappings. */
  readonly _idToIndex: ReadonlyMap<string, number>;
  /** Confirmed index → id mappings (reverse, for conflict detection). */
  readonly _indexToId: ReadonlyMap<number, string>;
};

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

export function createLegacyAdapter(requestTotal: number | null): LegacyAdapterState {
  return {
    items: new Map(),
    finalCount: 0,
    requestTotal,
    done: false,
    _idCounter: 0,
    _idToIndex: new Map(),
    _indexToId: new Map(),
  };
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Extract an opaque id from a parsed legacy event payload.
 * Checks: stable_id → question_id (outer) → question.id
 */
function extractId(
  payload: Record<string, unknown>,
  question: ExamQuestion | null,
): string | null {
  const sid = payload.stable_id;
  if (typeof sid === "string" && sid.length > 0) return sid;
  const qid = payload.question_id;
  if (typeof qid === "string" && qid.length > 0) return qid;
  if (question !== null) {
    const qIdInQ = (question as unknown as Record<string, unknown>).id;
    if (typeof qIdInQ === "string" && qIdInQ.length > 0) return qIdInQ;
  }
  return null;
}

/**
 * Attempt to record a consistent index↔id mapping.
 * Returns updated maps and whether the mapping was consistent.
 * On inconsistency, returns the original maps unchanged.
 */
function tryRecordMapping(
  idToIndex: ReadonlyMap<string, number>,
  indexToId: ReadonlyMap<number, string>,
  id: string,
  index: number,
): {
  idToIndex: ReadonlyMap<string, number>;
  indexToId: ReadonlyMap<number, string>;
  consistent: boolean;
} {
  const existingIndex = idToIndex.get(id);
  const existingId = indexToId.get(index);

  // Check for inconsistency in either direction
  if (existingIndex !== undefined && existingIndex !== index) {
    return { idToIndex, indexToId, consistent: false };
  }
  if (existingId !== undefined && existingId !== id) {
    return { idToIndex, indexToId, consistent: false };
  }

  // Already recorded (identical entry) — nothing to change
  if (existingIndex === index && existingId === id) {
    return { idToIndex, indexToId, consistent: true };
  }

  const newIdToIndex = new Map(idToIndex);
  newIdToIndex.set(id, index);
  const newIndexToId = new Map(indexToId);
  newIndexToId.set(index, id);
  return { idToIndex: newIdToIndex, indexToId: newIndexToId, consistent: true };
}

/**
 * Parse the question from a legacy event payload.
 * Handles both {question: {...}} wrapper and direct question objects.
 */
function parseQuestion(raw: Record<string, unknown>): ExamQuestion | null {
  const q = raw.question;
  if (q !== null && q !== undefined && typeof q === "object" && !Array.isArray(q)) {
    return q as ExamQuestion;
  }
  // Check if the raw payload itself is a question (old server direct result format)
  if (typeof raw.題型 === "string" || raw.題目 !== undefined) {
    return raw as unknown as ExamQuestion;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Reducer
// ---------------------------------------------------------------------------

export function applyLegacyEvent(
  state: LegacyAdapterState,
  eventName: string,
  data: string,
): LegacyAdapterState {
  // No mutations after done
  if (state.done) return state;

  if (eventName === "done") {
    return { ...state, done: true };
  }

  // Only process content-bearing events
  if (eventName !== "question_update" && eventName !== "result") {
    return state;
  }

  let parsed: Record<string, unknown>;
  try {
    const p = JSON.parse(data) as unknown;
    if (p === null || typeof p !== "object" || Array.isArray(p)) return state;
    parsed = p as Record<string, unknown>;
  } catch {
    return state;
  }

  const question = parseQuestion(parsed);
  if (question === null) return state;

  const explicitId = extractId(parsed, question);
  const explicitIndex =
    typeof parsed.index === "number" &&
    Number.isInteger(parsed.index) &&
    parsed.index >= 0
      ? parsed.index
      : null;
  const phase: DraftPhase =
    typeof parsed.phase === "string" ? (parsed.phase as DraftPhase) : "verified";
  const contentRevision =
    typeof parsed.content_revision === "number" && parsed.content_revision > 0
      ? parsed.content_revision
      : null;

  // -------------------------------------------------------------------------
  // result event — final content
  // -------------------------------------------------------------------------
  if (eventName === "result") {
    const idKey =
      explicitId !== null ? explicitId : `legacy-result-${state._idCounter}`;
    const isNewSyntheticId = explicitId === null;

    const existing = state.items.get(idKey);
    // Duplicate final: ignore (same id, already final)
    if (existing?.isFinal) return state;

    let newIdToIndex = state._idToIndex;
    let newIndexToId = state._indexToId;
    // Inherit resolvedIndex from existing mapping (if any) as baseline
    let resolvedIndex: number | null = existing?.resolvedIndex ?? null;

    if (explicitId !== null && explicitIndex !== null) {
      const mapped = tryRecordMapping(newIdToIndex, newIndexToId, explicitId, explicitIndex);
      if (mapped.consistent) {
        newIdToIndex = mapped.idToIndex;
        newIndexToId = mapped.indexToId;
        resolvedIndex = explicitIndex;
      }
      // inconsistent → keep existing resolvedIndex
    } else if (explicitId !== null) {
      // id but no explicit index — use existing confirmed mapping if present
      const mapped = newIdToIndex.get(explicitId);
      if (mapped !== undefined) resolvedIndex = mapped;
    }
    // no id → resolvedIndex stays null (原題序未知)

    const newItem: LegacyItem = {
      id: idKey,
      question,
      phase: "verified",
      isFinal: true,
      resolvedIndex,
      contentRevision,
      trail: existing?.trail ?? [],
      figurePolicyTrail: existing?.figurePolicyTrail ?? [],
      referenceExampleRecord: existing?.referenceExampleRecord,
    };

    const newItems = new Map(state.items);
    newItems.set(idKey, newItem);

    return {
      ...state,
      items: newItems,
      // finalCount always increments here: either new item, or upgrading a draft to final
      finalCount: state.finalCount + 1,
      _idCounter: isNewSyntheticId ? state._idCounter + 1 : state._idCounter,
      _idToIndex: newIdToIndex,
      _indexToId: newIndexToId,
    };
  }

  // -------------------------------------------------------------------------
  // question_update event — draft content
  // -------------------------------------------------------------------------
  let idKey: string;
  let isNewSyntheticId: boolean;

  if (explicitId !== null) {
    idKey = explicitId;
    isNewSyntheticId = false;
  } else if (explicitIndex !== null) {
    // Synthesize a stable id from the explicit index (same index reuses same id)
    idKey = `legacy-draft-${explicitIndex}`;
    isNewSyntheticId = false;
  } else {
    idKey = `legacy-draft-gen-${state._idCounter}`;
    isNewSyntheticId = true;
  }

  let newIdToIndex = state._idToIndex;
  let newIndexToId = state._indexToId;
  let resolvedIndex: number | null = null;

  const existingForMapping = state.items.get(idKey);

  if (explicitIndex !== null) {
    const mapped = tryRecordMapping(newIdToIndex, newIndexToId, idKey, explicitIndex);
    if (mapped.consistent) {
      newIdToIndex = mapped.idToIndex;
      newIndexToId = mapped.indexToId;
      resolvedIndex = explicitIndex;
    } else {
      // Inconsistent → preserve the existing confirmed resolvedIndex, if any
      resolvedIndex = existingForMapping?.resolvedIndex ?? null;
    }
  } else if (explicitId !== null) {
    // id but no explicit index — look up existing confirmed mapping
    const mapped = newIdToIndex.get(explicitId);
    resolvedIndex = mapped !== undefined ? mapped : null;
  }

  const existing = state.items.get(idKey);

  // If this item is already final, do NOT overwrite its content.
  // However, if the resolvedIndex changed (late consistent mapping), update it.
  if (existing?.isFinal) {
    const indexChanged = resolvedIndex !== existing.resolvedIndex;
    const mappingChanged = newIdToIndex !== state._idToIndex || newIndexToId !== state._indexToId;

    if (indexChanged || mappingChanged) {
      const updatedItem = indexChanged ? { ...existing, resolvedIndex } : existing;
      const newItems = new Map(state.items);
      newItems.set(idKey, updatedItem);
      return {
        ...state,
        items: newItems,
        _idToIndex: newIdToIndex,
        _indexToId: newIndexToId,
      };
    }
    return state;
  }

  const newItem: LegacyItem = {
    id: idKey,
    question,
    phase,
    isFinal: false,
    resolvedIndex,
    contentRevision,
    trail: existing?.trail ?? [],
    figurePolicyTrail: existing?.figurePolicyTrail ?? [],
    referenceExampleRecord: existing?.referenceExampleRecord,
  };

  const newItems = new Map(state.items);
  newItems.set(idKey, newItem);

  return {
    ...state,
    items: newItems,
    _idCounter: isNewSyntheticId ? state._idCounter + 1 : state._idCounter,
    _idToIndex: newIdToIndex,
    _indexToId: newIndexToId,
  };
}

// ---------------------------------------------------------------------------
// Selectors
// ---------------------------------------------------------------------------

/**
 * Return items sorted for display:
 *  1. Items with a confirmed resolvedIndex, ascending.
 *  2. Items without a resolvedIndex (原題序未知), in insertion order.
 */
export function selectLegacyItems(state: LegacyAdapterState): readonly LegacyItem[] {
  const all = Array.from(state.items.values());
  const known = all
    .filter((i): i is LegacyItem & { resolvedIndex: number } => i.resolvedIndex !== null)
    .sort((a, b) => a.resolvedIndex - b.resolvedIndex);
  const unknown = all.filter((i) => i.resolvedIndex === null);
  return [...known, ...unknown];
}

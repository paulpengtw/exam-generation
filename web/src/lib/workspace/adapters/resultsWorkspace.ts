import type { ExamQuestion, GeneratedQuestion, GenerateStatus, SubQuestion } from "../../../hooks/useGenerate";
import { isFiniteNumber, isNullableNumber, isRecord, isStringArray } from "./guards";
import type {
  DurableImageSnapshot,
  ResultsEvidenceSnapshot,
  ResultsProcessing,
  ResultsReceipt,
  ResultsReview,
  ResultsWorkspaceSnapshot,
} from "./types";

export interface ResultsWorkspaceLive extends Omit<ResultsWorkspaceSnapshot, "kind" | "version" | "completion"> {
  status: GenerateStatus;
}

const EXCLUDED_KEYS = new Set([
  "llmCalls",
  "llm_calls",
  "provider_payload",
  "providerPayload",
  "provider_request",
  "providerRequest",
  "provider_response",
  "providerResponse",
  "raw_request",
  "rawRequest",
  "raw_response",
  "rawResponse",
  "credentials",
  "credential",
  "api_key",
  "apiKey",
  "authorization",
  "diagnostic",
  "diagnostics",
]);

const BASE64_PATTERN = /^[A-Za-z0-9+/]+={0,2}$/;

function normalizeImageBase64(value: string): string {
  if (value.startsWith("blob:")) {
    throw new Error("Recovery results cannot contain object URLs");
  }
  const dataPrefix = /^data:image\/png;base64,(.*)$/i.exec(value);
  const base64 = dataPrefix?.[1] ?? value;
  if (!BASE64_PATTERN.test(base64)) {
    throw new Error("Recovery results contain invalid image bytes");
  }
  return base64;
}

function cloneForRecovery(value: unknown, key?: string): unknown {
  if (key !== undefined && EXCLUDED_KEYS.has(key)) return undefined;
  if (typeof value === "string") {
    if (value.startsWith("blob:")) {
      throw new Error("Recovery results cannot contain object URLs");
    }
    return key === "image_base64" ? normalizeImageBase64(value) : value;
  }
  if (value === null || typeof value === "number" || typeof value === "boolean") {
    if (typeof value === "number" && !Number.isFinite(value)) {
      throw new Error("Recovery results contain a non-finite number");
    }
    return value;
  }
  if (Array.isArray(value)) return value.map((item) => cloneForRecovery(item));
  if (isRecord(value)) {
    const output: Record<string, unknown> = {};
    for (const [entryKey, entryValue] of Object.entries(value)) {
      const cloned = cloneForRecovery(entryValue, entryKey);
      if (cloned !== undefined) output[entryKey] = cloned;
    }
    return output;
  }
  if (value === undefined) return undefined;
  throw new Error("Recovery results contain an unsupported value");
}

function questionStableId(question: ExamQuestion, index: number): string {
  return typeof question.id === "string" && question.id.length > 0 ? question.id : `index-${index}`;
}

function displayStableId(item: GeneratedQuestion): string {
  const explicit = item.stableId;
  return explicit && explicit.length > 0
    ? explicit
    : questionStableId(item.question, item.index);
}

function subQuestionImageKey(stableId: string, subQuestion: SubQuestion, index: number): string {
  const identity = typeof subQuestion.id === "string" && subQuestion.id.length > 0
    ? subQuestion.id
    : String(subQuestion.序號 || index + 1);
  return `${stableId}::subquestion::${identity}`;
}

function addQuestionImages(
  images: Record<string, DurableImageSnapshot>,
  question: ExamQuestion,
  stableId: string,
): void {
  if (typeof question.image_base64 === "string") {
    images[stableId] = {
      base64: normalizeImageBase64(question.image_base64),
      mimeType: "image/png",
      location: "question",
    };
  }
  if (!Array.isArray(question.subquestions)) return;
  question.subquestions.forEach((subQuestion, index) => {
    if (!isRecord(subQuestion) || typeof subQuestion.image_base64 !== "string") return;
    images[subQuestionImageKey(stableId, subQuestion as SubQuestion, index)] = {
      base64: normalizeImageBase64(subQuestion.image_base64),
      mimeType: "image/png",
      location: "subquestion",
    };
  });
}

function collectImages(
  results: ExamQuestion[],
  displayResults: GeneratedQuestion[],
): Record<string, DurableImageSnapshot> | undefined {
  const images: Record<string, DurableImageSnapshot> = {};
  // Final content wins when a draft and final receipt use different image bytes.
  results.forEach((question, index) => addQuestionImages(images, question, questionStableId(question, index)));
  displayResults.forEach((item) => {
    const stableId = displayStableId(item);
    const displayImages: Record<string, DurableImageSnapshot> = {};
    addQuestionImages(displayImages, item.question, stableId);
    for (const [key, image] of Object.entries(displayImages)) {
      if (!(key in images)) images[key] = image;
    }
  });
  return Object.keys(images).length > 0 ? images : undefined;
}

function resultProcessing(
  status: GenerateStatus,
  finishedAt: number | null,
  terminalEvidence: boolean | undefined,
): ResultsProcessing {
  if (status === "error") return "interrupted";
  if (finishedAt === null || status !== "idle" || terminalEvidence === false) return "unknown";
  return "settled";
}

function resultCompletion(
  status: GenerateStatus,
  finishedAt: number | null,
  terminalEvidence: boolean | undefined,
): ResultsWorkspaceSnapshot["completion"] {
  if (status === "error") return "error";
  if (terminalEvidence === false) return "unknown";
  return finishedAt !== null && status === "idle" ? "settled" : "unknown";
}

function resultReview(item: GeneratedQuestion): ResultsReview {
  const entries = item.trail ?? [];
  const verification = [...entries].reverse().find((entry) => entry.kind === "verification");
  if (verification?.kind === "verification") return verification.passed ? "passed" : "failed";
  const questionVerification = item.question.verification;
  if (isRecord(questionVerification) && typeof questionVerification.passed === "boolean") {
    return questionVerification.passed ? "passed" : "failed";
  }
  return "unknown";
}

function buildEvidence(
  results: ExamQuestion[],
  displayResults: GeneratedQuestion[],
  status: GenerateStatus,
  finishedAt: number | null,
  terminalEvidence: boolean | undefined,
): ResultsEvidenceSnapshot[] {
  const processing = resultProcessing(status, finishedAt, terminalEvidence);
  const evidence: ResultsEvidenceSnapshot[] = displayResults.map((item) => ({
    stableId: displayStableId(item),
    index: item.index,
    receipt: item.isFinal ? "final" : "draft",
    processing,
    contentRevision: item.contentRevision ?? null,
    terminal: terminalEvidence === true ? (status === "error" ? "failed" : "normal") : "unknown",
    review: {
      status: resultReview(item),
      contentRevision: item.contentRevision ?? null,
    },
  }));
  const displayedIds = new Set(evidence.map((item) => item.stableId));
  results.forEach((question, index) => {
    const stableId = questionStableId(question, index);
    if (displayedIds.has(stableId)) return;
    evidence.push({
      stableId,
      index,
      receipt: "final",
      processing,
      contentRevision: null,
      terminal: terminalEvidence === true ? (status === "error" ? "failed" : "normal") : "unknown",
      review: { status: "unknown", contentRevision: null },
    });
  });
  return evidence;
}

function resultFields(live: Omit<ResultsWorkspaceSnapshot, "kind" | "version" | "completion">) {
  const results = cloneForRecovery(live.results) as ExamQuestion[];
  const displayResults = cloneForRecovery(live.displayResults) as GeneratedQuestion[];
  const images = collectImages(results, displayResults);
  return {
    results,
    displayResults,
    progressLines: cloneForRecovery(live.progressLines) as string[],
    errorMessage: live.errorMessage,
    startedAt: live.startedAt,
    finishedAt: live.finishedAt,
    subQuestionTotal: live.subQuestionTotal,
    requestedTotal: live.requestedTotal,
    submittedSubQuestionCount: live.submittedSubQuestionCount,
    images,
  };
}

export function exportResultsWorkspace(live: ResultsWorkspaceLive): ResultsWorkspaceSnapshot {
  const fields = resultFields(live);
  const { images, ...fieldsWithoutImages } = fields;
  const hasEvidenceExtension = live.terminalEvidence !== undefined || live.runId !== undefined ||
    live.displayResults.some((item) => item.stableId !== undefined || item.contentRevision !== undefined);
  return {
    kind: "results",
    version: 1,
    ...fieldsWithoutImages,
    completion: resultCompletion(live.status, live.finishedAt, live.terminalEvidence),
    ...(hasEvidenceExtension ? {
      processing: resultProcessing(live.status, live.finishedAt, live.terminalEvidence),
      ...(live.terminalEvidence !== undefined ? { terminalEvidence: live.terminalEvidence } : {}),
      ...(live.runId !== undefined ? { runId: live.runId } : {}),
      evidence: buildEvidence(live.results, live.displayResults, live.status, live.finishedAt, live.terminalEvidence),
    } : {}),
    ...(images ? { images } : {}),
  };
}

function isResultsProcessing(value: unknown): value is ResultsProcessing {
  return value === "settled" || value === "interrupted" || value === "unknown";
}

function isResultsReceipt(value: unknown): value is ResultsReceipt {
  return value === "none" || value === "draft" || value === "final";
}

function isResultsReview(value: unknown): value is ResultsReview {
  return value === "passed" || value === "failed" || value === "skipped" || value === "unknown";
}

function isRevision(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isInteger(value) && value > 0);
}

function isTerminal(value: unknown): value is "normal" | "failed" | "cancelled" | "unknown" {
  return value === "normal" || value === "failed" || value === "cancelled" || value === "unknown";
}

function parseImages(raw: unknown): Record<string, DurableImageSnapshot> | undefined | null {
  if (raw === undefined) return undefined;
  if (!isRecord(raw)) return null;
  const images: Record<string, DurableImageSnapshot> = {};
  for (const [key, value] of Object.entries(raw)) {
    if (!key || !isRecord(value) || typeof value.base64 !== "string" || value.mimeType !== "image/png" ||
      (value.location !== "question" && value.location !== "subquestion")) return null;
    try {
      images[key] = { base64: normalizeImageBase64(value.base64), mimeType: "image/png", location: value.location };
    } catch {
      return null;
    }
  }
  return images;
}

function parseEvidence(raw: unknown): ResultsEvidenceSnapshot[] | undefined | null {
  if (raw === undefined) return undefined;
  if (!Array.isArray(raw)) return null;
  const evidence: ResultsEvidenceSnapshot[] = [];
  for (const value of raw) {
    const review = isRecord(value) && isRecord(value.review) ? value.review : null;
    if (!isRecord(value) || typeof value.stableId !== "string" ||
      !(typeof value.index === "number" && Number.isInteger(value.index)) ||
      !isResultsReceipt(value.receipt) || !isResultsProcessing(value.processing) ||
      !isRevision(value.contentRevision) || !isTerminal(value.terminal) ||
      review === null || !isResultsReview(review.status) || !isRevision(review.contentRevision)) return null;
    evidence.push({
      stableId: value.stableId,
      index: value.index,
      receipt: value.receipt,
      processing: value.processing,
      contentRevision: value.contentRevision,
      terminal: value.terminal,
      review: { status: review.status, contentRevision: review.contentRevision },
    });
  }
  return evidence;
}

function hydrateQuestion(
  question: ExamQuestion,
  stableId: string,
  images: Record<string, DurableImageSnapshot> | undefined,
): ExamQuestion {
  if (!images) return question;
  const hydrated: ExamQuestion = { ...question };
  const questionImage = images[stableId];
  if (hydrated.image_base64 === undefined && questionImage?.location === "question") {
    hydrated.image_base64 = questionImage.base64;
  }
  if (Array.isArray(hydrated.subquestions)) {
    hydrated.subquestions = hydrated.subquestions.map((subQuestion, index) => {
      const sub = { ...subQuestion };
      const image = images[subQuestionImageKey(stableId, sub, index)];
      if (sub.image_base64 === undefined && image?.location === "subquestion") sub.image_base64 = image.base64;
      return sub;
    });
  }
  return hydrated;
}

function hydrateResults(
  results: ExamQuestion[],
  displayResults: GeneratedQuestion[],
  images: Record<string, DurableImageSnapshot> | undefined,
): { results: ExamQuestion[]; displayResults: GeneratedQuestion[] } {
  return {
    results: results.map((question, index) => hydrateQuestion(question, questionStableId(question, index), images)),
    displayResults: displayResults.map((item) => ({
      ...item,
      question: hydrateQuestion(item.question, displayStableId(item), images),
    })),
  };
}

export function importResultsWorkspace(raw: unknown): ResultsWorkspaceSnapshot | null {
  if (
    !isRecord(raw) || raw.kind !== "results" || raw.version !== 1 ||
    !Array.isArray(raw.results) || !raw.results.every(isRecord) ||
    !Array.isArray(raw.displayResults) || !raw.displayResults.every((item) =>
      isRecord(item) && typeof item.index === "number" && Number.isInteger(item.index) && isRecord(item.question) && typeof item.isFinal === "boolean" &&
      (item.stableId === undefined || typeof item.stableId === "string") &&
      (item.contentRevision === undefined || isRevision(item.contentRevision))) ||
    !isStringArray(raw.progressLines) ||
    !(raw.errorMessage === null || typeof raw.errorMessage === "string") ||
    !isNullableNumber(raw.startedAt) || !isNullableNumber(raw.finishedAt) ||
    !isNullableNumber(raw.subQuestionTotal) || !isFiniteNumber(raw.requestedTotal) ||
    !isNullableNumber(raw.submittedSubQuestionCount) ||
    !(raw.completion === "settled" || raw.completion === "error" || raw.completion === "unknown") ||
    (raw.processing !== undefined && !isResultsProcessing(raw.processing)) ||
    (raw.terminalEvidence !== undefined && typeof raw.terminalEvidence !== "boolean") ||
    (raw.runId !== undefined && raw.runId !== null && typeof raw.runId !== "string")
  ) return null;

  const images = parseImages(raw.images);
  const evidence = parseEvidence(raw.evidence);
  if (images === null || evidence === null) return null;

  let results: ExamQuestion[];
  let displayResults: GeneratedQuestion[];
  try {
    results = cloneForRecovery(raw.results) as ExamQuestion[];
    displayResults = cloneForRecovery(raw.displayResults) as GeneratedQuestion[];
  } catch {
    return null;
  }
  const hydrated = hydrateResults(results, displayResults, images);

  return {
    kind: "results",
    version: 1,
    results: hydrated.results,
    displayResults: hydrated.displayResults,
    progressLines: raw.progressLines,
    errorMessage: raw.errorMessage,
    startedAt: raw.startedAt,
    finishedAt: raw.finishedAt,
    subQuestionTotal: raw.subQuestionTotal,
    requestedTotal: raw.requestedTotal,
    submittedSubQuestionCount: raw.submittedSubQuestionCount,
    completion: raw.completion,
    ...(raw.processing !== undefined ? { processing: raw.processing } : {}),
    ...(raw.terminalEvidence !== undefined ? { terminalEvidence: raw.terminalEvidence } : {}),
    ...(raw.runId !== undefined ? { runId: raw.runId } : {}),
    ...(evidence !== undefined ? { evidence } : {}),
    ...(images !== undefined ? { images } : {}),
  };
}

import type { FormFields, SubQuestionConfig } from "../components/ParamForm";

const MAX_DRAFT_AGE_MS = 7 * 24 * 60 * 60 * 1000;

export interface FormDraft {
  savedAt: string;
  fields: FormFields;
}

function draftKey(userId: string): string {
  return `exam_form_draft_${userId}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isOptionalString(value: unknown): value is string | undefined {
  return value === undefined || typeof value === "string";
}

function isOptionalNumber(value: unknown): value is number | undefined {
  return value === undefined || (typeof value === "number" && Number.isFinite(value));
}

function isSubQuestionConfig(value: unknown): value is SubQuestionConfig {
  if (!isRecord(value)) return false;
  return (
    isOptionalString(value.question_type) &&
    isOptionalString(value.instruction) &&
    isOptionalString(value.content_type) &&
    (
      value.image_generation_mode === undefined ||
      value.image_generation_mode === "html" ||
      value.image_generation_mode === "gpt_image"
    ) &&
    isOptionalNumber(value.question_word_limit) &&
    isOptionalNumber(value.option_word_limit) &&
    isOptionalNumber(value.text_word_limit) &&
    isOptionalString(value.reporting_scale) &&
    (
      value.learning_content === undefined ||
      isStringArray(value.learning_content)
    ) &&
    (
      value.learning_performance === undefined ||
      isStringArray(value.learning_performance)
    )
  );
}

function isFormFields(value: unknown): value is FormFields {
  if (!isRecord(value)) return false;
  return (
    (value.grade === "" ||
      (typeof value.grade === "number" && Number.isFinite(value.grade))) &&
    typeof value.style === "string" &&
    typeof value.contentType === "string" &&
    typeof value.customContentType === "string" &&
    isStringArray(value.context) &&
    typeof value.setType === "string" &&
    isStringArray(value.qType) &&
    typeof value.count === "number" &&
    Number.isFinite(value.count) &&
    (value.coverageMode === "balanced" || value.coverageMode === "random") &&
    typeof value.skipVerify === "boolean" &&
    typeof value.disableReferenceFewshot === "boolean" &&
    (
      value.imageGenerationMode === "html" ||
      value.imageGenerationMode === "gpt_image"
    ) &&
    (
      value.difficulty === "" ||
      value.difficulty === "easy" ||
      value.difficulty === "medium" ||
      value.difficulty === "hard"
    ) &&
    (value.reportingScale === undefined || typeof value.reportingScale === "string") &&
    typeof value.subjectFilter === "string" &&
    typeof value.passage === "string" &&
    (
      value.textWordLimit === null ||
      (typeof value.textWordLimit === "number" &&
        Number.isFinite(value.textWordLimit))
    ) &&
    isStringArray(value.options) &&
    typeof value.topic === "string" &&
    (value.coreQuestion === null || typeof value.coreQuestion === "string") &&
    typeof value.subContext === "string" &&
    isStringArray(value.scienceCompetency) &&
    isStringArray(value.learningPerformance) &&
    isStringArray(value.learningContent) &&
    (
      value.subQuestionCount === "" ||
      (typeof value.subQuestionCount === "number" &&
        Number.isFinite(value.subQuestionCount))
    ) &&
    Array.isArray(value.subquestionConfigs) &&
    value.subquestionConfigs.every(isSubQuestionConfig) &&
    typeof value.modelPlan === "string" &&
    typeof value.modelExecute === "string" &&
    typeof value.effortPlan === "string" &&
    typeof value.effortExecute === "string"
  );
}

export function saveDraft(userId: string, fields: FormFields): void {
  try {
    localStorage.setItem(
      draftKey(userId),
      JSON.stringify({
        savedAt: new Date().toISOString(),
        fields,
      } satisfies FormDraft),
    );
  } catch {
    // Draft persistence is best-effort.
  }
}

export function loadDraft(userId: string): FormDraft | null {
  try {
    const raw = localStorage.getItem(draftKey(userId));
    if (raw === null) return null;

    const parsed = JSON.parse(raw) as unknown;
    const savedAt =
      isRecord(parsed) && typeof parsed.savedAt === "string"
        ? Date.parse(parsed.savedAt)
        : Number.NaN;
    if (
      !isRecord(parsed) ||
      !Number.isFinite(savedAt) ||
      !isFormFields(parsed.fields) ||
      Date.now() - savedAt > MAX_DRAFT_AGE_MS
    ) {
      clearDraft(userId);
      return null;
    }

    return {
      savedAt: parsed.savedAt as string,
      fields: {
        ...parsed.fields,
        reportingScale:
          typeof parsed.fields.reportingScale === "string"
            ? parsed.fields.reportingScale
            : "",
      },
    };
  } catch {
    clearDraft(userId);
    return null;
  }
}

export function clearDraft(userId: string): void {
  try {
    localStorage.removeItem(draftKey(userId));
  } catch {
    // Draft persistence is best-effort.
  }
}

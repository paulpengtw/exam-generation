import { useId, useState } from "react";
import type { SchemaEntry } from "../api/client";
import { useT } from "../i18n/useT";
import type { SubQuestionConfig } from "./ParamForm";

const PISA_SCIENCE_QUESTION_TYPE_VALUES = [
  "Simple multiple-choice",
  "Complex multiple-choice",
  "Constructed response",
] as const;

export interface SubQuestionConfigEditorProps {
  config: SubQuestionConfig;
  subject: string;
  questionTypes: SchemaEntry[];
  cognitiveProcesses?: SchemaEntry[];
  contentTypes: SchemaEntry[];
  onChange: (patch: Partial<SubQuestionConfig>) => void;
}

export interface SubQuestionInstructionFieldProps {
  config: SubQuestionConfig;
  onChange: (patch: Partial<SubQuestionConfig>) => void;
  badge?: {
    label: string;
    className: string;
  };
}

export function SubQuestionInstructionField({
  config,
  onChange,
  badge,
}: SubQuestionInstructionFieldProps) {
  const instructionId = useId();
  const t = useT();

  return (
    <div className="mt-3">
      <div className="flex items-center gap-2">
        <label htmlFor={instructionId} className="block text-xs text-gray-500">
          {t("form.confirm_subq_instruction_input")}
        </label>
        {badge && <span className={badge.className}>{badge.label}</span>}
      </div>
      <textarea
        id={instructionId}
        value={config.instruction ?? ""}
        onChange={(e) => onChange({ instruction: e.target.value || undefined })}
        placeholder={t("form.confirm_subq_instruction_placeholder")}
        rows={2}
        className="mt-0.5 block w-full border rounded px-1.5 py-1 text-sm"
      />
    </div>
  );
}

export interface SubQuestionReportingScaleFieldProps {
  config: SubQuestionConfig;
  onChange: (patch: Partial<SubQuestionConfig>) => void;
  options?: SchemaEntry[];
  hideLabel?: boolean;
  emptyOptionLabel?: string;
  badge?: {
    label: string;
    className: string;
  };
}

export function SubQuestionReportingScaleField({
  config,
  onChange,
  options,
  hideLabel = false,
  emptyOptionLabel,
  badge,
}: SubQuestionReportingScaleFieldProps) {
  const reportingScaleId = useId();
  const t = useT();
  const reportingScaleOptions = options ?? [
    "1c", "1b", "1a", "2", "3", "4", "5", "6",
  ].map((value) => ({ value, instruction: `等級 ${value}` }));

  return (
    <div>
      {!hideLabel && (
        <div className="flex items-center gap-2">
          <label htmlFor={reportingScaleId} className="block text-xs text-gray-500">
            {t("form.reporting_scale")}
          </label>
          {badge && <span className={badge.className}>{badge.label}</span>}
        </div>
      )}
      <select
        id={reportingScaleId}
        aria-label={hideLabel ? t("form.reporting_scale") : undefined}
        value={config.reporting_scale ?? ""}
        onChange={(e) => onChange({ reporting_scale: e.target.value || undefined })}
        className="mt-0.5 block w-full border rounded px-1.5 py-1 text-sm"
      >
        <option value="">{emptyOptionLabel ?? "（隨機）"}</option>
        {reportingScaleOptions.map((entry) => (
          <option key={entry.value} value={entry.value}>{entry.instruction || entry.value}</option>
        ))}
      </select>
    </div>
  );
}

export interface SubQuestionQuestionTypeFieldProps {
  config: SubQuestionConfig;
  subject: string;
  questionTypes: SchemaEntry[];
  onChange: (patch: Partial<SubQuestionConfig>) => void;
  emptyOptionLabel?: string;
  badge?: {
    label: string;
    className: string;
  };
}

export function SubQuestionQuestionTypeField({
  config,
  subject,
  questionTypes,
  onChange,
  emptyOptionLabel,
  badge,
}: SubQuestionQuestionTypeFieldProps) {
  const questionTypeId = useId();
  const t = useT();
  const availableQuestionTypes = questionTypeOptions(subject, questionTypes);

  return (
    <div>
      <div className="flex items-center gap-2">
        <label htmlFor={questionTypeId} className="block text-xs text-gray-500">
          {t("form.confirm_subq_q_type_input")}
        </label>
        {badge && <span className={badge.className}>{badge.label}</span>}
      </div>
      <select
        id={questionTypeId}
        value={config.question_type ?? ""}
        onChange={(e) => onChange({ question_type: e.target.value || undefined })}
        className="mt-0.5 block w-full border rounded px-1.5 py-1 text-sm"
      >
        <option value="">{emptyOptionLabel ?? t("form.confirm_random")}</option>
        {availableQuestionTypes.map((entry) => (
          <option key={entry.value} value={entry.value}>{entry.value}</option>
        ))}
      </select>
    </div>
  );
}

export interface SubQuestionContentTypeFieldProps {
  config: SubQuestionConfig;
  contentTypes: SchemaEntry[];
  onChange: (patch: Partial<SubQuestionConfig>) => void;
  badge?: {
    label: string;
    className: string;
  };
}

export function SubQuestionContentTypeField({
  config,
  contentTypes,
  onChange,
  badge,
}: SubQuestionContentTypeFieldProps) {
  const contentTypeId = useId();
  const t = useT();

  return (
    <div>
      <div className="flex items-center gap-2">
        <label htmlFor={contentTypeId} className="block text-xs text-gray-500">
          {t("form.confirm_subq_content_type_input")}
        </label>
        {badge && <span className={badge.className}>{badge.label}</span>}
      </div>
      <select
        id={contentTypeId}
        value={config.content_type ?? ""}
        onChange={(e) => onChange({ content_type: e.target.value || undefined })}
        className="mt-0.5 block w-full border rounded px-1.5 py-1 text-sm"
      >
        <option value="">{t("form.confirm_inherit_text")}</option>
        {contentTypes.map((entry) => (
          <option key={entry.value} value={entry.value}>{entry.value}</option>
        ))}
      </select>
    </div>
  );
}

export interface SubQuestionImageGenerationModeFieldProps {
  config: SubQuestionConfig;
  onChange: (patch: Partial<SubQuestionConfig>) => void;
  badge?: {
    label: string;
    className: string;
  };
}

export function SubQuestionImageGenerationModeField({
  config,
  onChange,
  badge,
}: SubQuestionImageGenerationModeFieldProps) {
  const imageGenerationModeId = useId();
  const t = useT();

  return (
    <div>
      <div className="flex items-center gap-2">
        <label htmlFor={imageGenerationModeId} className="block text-xs text-gray-500">
          {t("form.confirm_subq_image_mode_input")}
        </label>
        {badge && <span className={badge.className}>{badge.label}</span>}
      </div>
      <select
        id={imageGenerationModeId}
        value={config.image_generation_mode ?? ""}
        onChange={(e) => onChange({ image_generation_mode: (e.target.value as "html" | "gpt_image") || undefined })}
        className="mt-0.5 block w-full border rounded px-1.5 py-1 text-sm"
      >
        <option value="">{t("form.confirm_inherit_text")}</option>
        <option value="html">HTML 渲染</option>
        <option value="gpt_image">GPT 生圖</option>
      </select>
    </div>
  );
}

function optionalNumber(raw: string): number | undefined {
  if (raw.trim() === "") return undefined;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function isValidWordLimit(raw: string): boolean {
  if (raw.trim() === "") return true;
  const n = Number(raw);
  return Number.isInteger(n) && n >= 1;
}

export interface SubQuestionWordLimitFieldProps {
  config: SubQuestionConfig;
  field: "question_word_limit" | "option_word_limit";
  labelKey: string;
  placeholder?: string;
  onChange: (patch: Partial<SubQuestionConfig>) => void;
  /** When provided, enables validation mode: invalid inputs show an error and are not saved to config. */
  onValidityChange?: (isValid: boolean) => void;
  badge?: { label: string; className: string };
}

export function SubQuestionWordLimitField({
  config,
  field,
  labelKey,
  placeholder,
  onChange,
  onValidityChange,
  badge,
}: SubQuestionWordLimitFieldProps) {
  const id = useId();
  const t = useT();
  // Use local state so an invalid input (e.g. "0") stays visible without updating config.
  // The initializer reads config[field] once; subsequent updates go through handleChange.
  const [rawValue, setRawValue] = useState<string>(() => config[field]?.toString() ?? "");

  const hasError = onValidityChange != null && rawValue !== "" && !isValidWordLimit(rawValue);

  function handleChange(raw: string) {
    setRawValue(raw);
    const valid = isValidWordLimit(raw);
    if (onValidityChange) {
      // Validation mode (confirmation card): only update config when valid.
      onValidityChange(valid);
      if (valid) {
        onChange({ [field]: optionalNumber(raw) } as Partial<SubQuestionConfig>);
      }
    } else {
      // No-validation mode (form editor): always update config, matching prior behaviour.
      onChange({ [field]: optionalNumber(raw) } as Partial<SubQuestionConfig>);
    }
  }

  return (
    <div>
      <div className="flex items-center gap-2">
        <label htmlFor={id} className="block text-xs text-gray-500">
          {t(labelKey as Parameters<typeof t>[0])}
        </label>
        {badge && <span className={badge.className}>{badge.label}</span>}
      </div>
      <input
        id={id}
        type="number"
        min={1}
        value={rawValue}
        onChange={(e) => handleChange(e.target.value)}
        placeholder={placeholder ?? t("form.confirm_unlimited")}
        className={`mt-0.5 block w-full border rounded px-1.5 py-1 text-sm${hasError ? " border-red-500" : ""}`}
      />
      {hasError && <p className="mt-0.5 text-xs text-red-600">{t("form.confirm_word_limit_error")}</p>}
    </div>
  );
}

function questionTypeOptions(
  subject: string,
  questionTypes: SchemaEntry[],
): SchemaEntry[] {
  if (subject !== "natural_sciences") return questionTypes;

  return PISA_SCIENCE_QUESTION_TYPE_VALUES.map(
    (value) => questionTypes.find((entry) => entry.value === value) ?? { value, instruction: "" },
  );
}

export default function SubQuestionConfigEditor({
  config,
  subject,
  questionTypes,
  cognitiveProcesses = [],
  contentTypes,
  onChange,
}: SubQuestionConfigEditorProps) {
  const t = useT();

  return (
    <>
      <div className="mt-2 grid grid-cols-1 gap-3 md:grid-cols-6">
        <SubQuestionQuestionTypeField
          config={config}
          subject={subject}
          questionTypes={questionTypes}
          onChange={onChange}
        />
        {subject === "social_studies" && cognitiveProcesses.length > 0 && (
          <div>
            <label className="block text-xs text-gray-500">{t("form.cognitive_process")}</label>
            <select
              aria-label={t("form.cognitive_process")}
              value={config.cognitive_process ?? ""}
              onChange={(e) => onChange({ cognitive_process: e.target.value || undefined })}
              className="mt-0.5 block w-full border rounded px-1.5 py-1 text-sm"
            >
              <option value="">{t("form.confirm_random")}</option>
              {cognitiveProcesses.map((entry) => (
                <option key={entry.value} value={entry.value}>
                  {entry.value}
                </option>
              ))}
            </select>
          </div>
        )}
        <SubQuestionWordLimitField
          config={config}
          field="question_word_limit"
          labelKey="form.confirm_subq_q_word_limit_input"
          placeholder="不限"
          onChange={onChange}
        />
        <SubQuestionWordLimitField
          config={config}
          field="option_word_limit"
          labelKey="form.confirm_subq_o_word_limit_input"
          placeholder="選擇題適用"
          onChange={onChange}
        />
        <SubQuestionContentTypeField
          config={config}
          contentTypes={contentTypes}
          onChange={onChange}
        />
        <SubQuestionImageGenerationModeField config={config} onChange={onChange} />
        {subject === "natural_sciences" && (
          <SubQuestionReportingScaleField config={config} onChange={onChange} />
        )}
      </div>
      <SubQuestionInstructionField config={config} onChange={onChange} />
    </>
  );
}

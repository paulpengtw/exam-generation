import { useId } from "react";
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

export interface SubQuestionQuestionTypeFieldProps {
  config: SubQuestionConfig;
  subject: string;
  questionTypes: SchemaEntry[];
  onChange: (patch: Partial<SubQuestionConfig>) => void;
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
        <option value="">{t("form.confirm_random")}</option>
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
        <div>
          <label className="block text-xs text-gray-500">文本字數限制</label>
          <input
            type="number"
            min={1}
            value={config.text_word_limit ?? ""}
            onChange={(e) => onChange({ text_word_limit: optionalNumber(e.target.value) })}
            placeholder="不限"
            className="mt-0.5 block w-full border rounded px-1.5 py-1 text-sm"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-500">題目字數限制</label>
          <input
            type="number"
            min={1}
            value={config.question_word_limit ?? ""}
            onChange={(e) => onChange({ question_word_limit: optionalNumber(e.target.value) })}
            placeholder="不限"
            className="mt-0.5 block w-full border rounded px-1.5 py-1 text-sm"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-500">選項字數限制</label>
          <input
            type="number"
            min={1}
            value={config.option_word_limit ?? ""}
            onChange={(e) => onChange({ option_word_limit: optionalNumber(e.target.value) })}
            placeholder="選擇題適用"
            className="mt-0.5 block w-full border rounded px-1.5 py-1 text-sm"
          />
        </div>
        <SubQuestionContentTypeField
          config={config}
          contentTypes={contentTypes}
          onChange={onChange}
        />
        <SubQuestionImageGenerationModeField config={config} onChange={onChange} />
        {subject === "natural_sciences" && (
          <div>
            <label className="block text-xs text-gray-500">{t("form.reporting_scale")}</label>
            <select
              value={config.reporting_scale || ""}
              onChange={(e) => onChange({ reporting_scale: e.target.value || undefined })}
              className="mt-0.5 block w-full border rounded px-1.5 py-1 text-sm"
            >
              <option value="">（隨機）</option>
              <option value="1c">等級 1c</option>
              <option value="1b">等級 1b</option>
              <option value="1a">等級 1a</option>
              <option value="2">等級 2</option>
              <option value="3">等級 3</option>
              <option value="4">等級 4</option>
              <option value="5">等級 5</option>
              <option value="6">等級 6</option>
            </select>
          </div>
        )}
      </div>
      <SubQuestionInstructionField config={config} onChange={onChange} />
    </>
  );
}

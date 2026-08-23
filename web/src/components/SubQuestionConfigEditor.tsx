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
  contentTypes: SchemaEntry[];
  onChange: (patch: Partial<SubQuestionConfig>) => void;
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
  contentTypes,
  onChange,
}: SubQuestionConfigEditorProps) {
  const t = useT();
  const availableQuestionTypes = questionTypeOptions(subject, questionTypes);

  return (
    <>
      <div className="mt-2 grid grid-cols-1 gap-3 md:grid-cols-6">
        <div>
          <label className="block text-xs text-gray-500">題型</label>
          <select
            value={config.question_type ?? ""}
            onChange={(e) => onChange({ question_type: e.target.value || undefined })}
            className="mt-0.5 block w-full border rounded px-1.5 py-1 text-sm"
          >
            <option value="">（隨機）</option>
            {availableQuestionTypes.map((entry) => (
              <option key={entry.value} value={entry.value}>{entry.value}</option>
            ))}
          </select>
        </div>
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
        <div>
          <label className="block text-xs text-gray-500">題目內容類型</label>
          <select
            value={config.content_type ?? ""}
            onChange={(e) => onChange({ content_type: e.target.value || undefined })}
            className="mt-0.5 block w-full border rounded px-1.5 py-1 text-sm"
          >
            <option value="">（沿用文本設定）</option>
            {contentTypes.map((entry) => (
              <option key={entry.value} value={entry.value}>{entry.value}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-500">圖片生成模式</label>
          <select
            value={config.image_generation_mode ?? ""}
            onChange={(e) => onChange({ image_generation_mode: (e.target.value as "html" | "gpt_image") || undefined })}
            className="mt-0.5 block w-full border rounded px-1.5 py-1 text-sm"
          >
            <option value="">（沿用文本設定）</option>
            <option value="html">HTML 渲染</option>
            <option value="gpt_image">GPT 生圖</option>
          </select>
        </div>
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
      <div className="mt-3">
        <label className="block text-xs text-gray-500">出題指示</label>
        <textarea
          value={config.instruction ?? ""}
          onChange={(e) => onChange({ instruction: e.target.value || undefined })}
          placeholder="例如：請聚焦在資料判讀與因果推論"
          rows={2}
          className="mt-0.5 block w-full border rounded px-1.5 py-1 text-sm"
        />
      </div>
    </>
  );
}

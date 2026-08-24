import type { SchemaEntry } from "../api/client";
import type { SubQuestionConfig } from "../components/ParamForm";
import { useT } from "../i18n/useT";
import {
  SubQuestionContentTypeField,
  SubQuestionImageGenerationModeField,
  SubQuestionInstructionField,
  SubQuestionQuestionTypeField,
  SubQuestionReportingScaleField,
} from "./SubQuestionConfigEditor";

export type ResolvedSubQuestionConfig = SubQuestionConfig & {
  _lcWasAutoDrawn?: boolean;
  _lpWasAutoDrawn?: boolean;
};

export default function SubquestionConfigCards({
  configs,
  subject,
  questionTypes,
  contentTypes,
  lcEntryByCode,
  lpEntryByCode,
  onInstructionChange,
  onQuestionTypeChange,
  onContentTypeChange,
  onImageModeChange,
  onReportingScaleChange,
}: {
  configs: ResolvedSubQuestionConfig[];
  subject: string;
  questionTypes: SchemaEntry[];
  contentTypes: SchemaEntry[];
  lcEntryByCode: Map<string, SchemaEntry>;
  lpEntryByCode: Map<string, SchemaEntry>;
  onInstructionChange?: (subquestionIndex: number, instruction: string) => void;
  onQuestionTypeChange?: (subquestionIndex: number, questionType: string) => void;
  onContentTypeChange?: (subquestionIndex: number, contentType: string) => void;
  onImageModeChange?: (subquestionIndex: number, imageMode: string) => void;
  onReportingScaleChange?: (subquestionIndex: number, reportingScale: string) => void;
}) {
  const t = useT();

  return (
    <ol className="space-y-3">
      {configs.map((row, subquestionIndex) => (
        <li key={subquestionIndex} className="rounded-lg border border-gray-200 bg-gray-50 p-3">
          <h5 className="mb-2 text-xs font-semibold text-gray-600">
            {t("form.confirm_subquestion_row_title").replace("{n}", String(subquestionIndex + 1))}
          </h5>
          {onQuestionTypeChange ? (
            <SubQuestionQuestionTypeField
              config={row}
              subject={subject}
              questionTypes={questionTypes}
              badge={{
                label: t(row.question_type?.trim() ? "form.confirm_badge_user" : "form.confirm_badge_random"),
                className: `text-xs font-medium ${row.question_type?.trim() ? "text-green-700" : "text-amber-700"}`,
              }}
              onChange={(patch) => onQuestionTypeChange(subquestionIndex, patch.question_type ?? "")}
            />
          ) : (
            <div className="text-sm text-gray-700">{t("form.confirm_subq_q_type")} {row.question_type ?? t("form.confirm_random")}</div>
          )}
          {subject === "social_studies" && <div className="text-sm text-gray-700">{t("form.confirm_subq_cognitive_process")} {row.cognitive_process ?? t("form.confirm_random")}</div>}
          {onInstructionChange ? (
            <SubQuestionInstructionField
              config={row}
              badge={{
                label: t(row.instruction?.trim() ? "form.confirm_badge_user" : "form.confirm_badge_random"),
                className: `text-xs font-medium ${row.instruction?.trim() ? "text-green-700" : "text-amber-700"}`,
              }}
              onChange={(patch) => onInstructionChange(subquestionIndex, patch.instruction ?? "")}
            />
          ) : (
            <div className="text-sm text-gray-700">{t("form.confirm_subq_instruction")} {row.instruction ?? t("form.confirm_not_filled")}</div>
          )}
          {onContentTypeChange ? (
            <SubQuestionContentTypeField
              config={row}
              contentTypes={contentTypes}
              badge={{
                label: t(row.content_type?.trim() ? "form.confirm_badge_user" : "form.confirm_badge_inherit"),
                className: `text-xs font-medium ${row.content_type?.trim() ? "text-green-700" : "text-gray-600"}`,
              }}
              onChange={(patch) => onContentTypeChange(subquestionIndex, patch.content_type ?? "")}
            />
          ) : (
            <div className="text-sm text-gray-700">{t("form.confirm_subq_content_type")} {row.content_type ?? t("form.confirm_inherit_text")}</div>
          )}
          {onImageModeChange ? (
            <SubQuestionImageGenerationModeField
              config={row}
              badge={{
                label: t(row.image_generation_mode?.trim() ? "form.confirm_badge_user" : "form.confirm_badge_inherit"),
                className: `text-xs font-medium ${row.image_generation_mode?.trim() ? "text-green-700" : "text-gray-600"}`,
              }}
              onChange={(patch) => onImageModeChange(subquestionIndex, patch.image_generation_mode ?? "")}
            />
          ) : (
            <div className="text-sm text-gray-700">{t("form.confirm_subq_image_mode")} {row.image_generation_mode ?? t("form.confirm_inherit_text")}</div>
          )}
          <div className="text-sm text-gray-700">{t("form.confirm_subq_q_word_limit")} {row.question_word_limit ?? t("form.confirm_unlimited")}</div>
          <div className="text-sm text-gray-700">{t("form.confirm_subq_o_word_limit")} {row.option_word_limit ?? t("form.confirm_unlimited")}</div>
          <div className="text-sm text-gray-700">{t("form.confirm_subq_text_word_limit")} {row.text_word_limit ?? t("form.confirm_unlimited")}</div>
          {subject === "natural_sciences" && (
            onReportingScaleChange ? (
              <SubQuestionReportingScaleField
                config={row}
                badge={{
                  label: t(row.reporting_scale?.trim() ? "form.confirm_badge_user" : "form.confirm_badge_random"),
                  className: `text-xs font-medium ${row.reporting_scale?.trim() ? "text-green-700" : "text-amber-700"}`,
                }}
                onChange={(patch) => onReportingScaleChange(subquestionIndex, patch.reporting_scale ?? "")}
              />
            ) : (
              <div className="text-sm text-gray-700">{t("form.confirm_subq_reporting_scale")} {row.reporting_scale ?? t("form.confirm_random")}</div>
            )
          )}
          <div>
            {row.learning_content && row.learning_content.length > 0 ? (
              <>
                <div className="mt-2 text-xs font-medium text-gray-600">
                  {t(
                    row._lcWasAutoDrawn
                      ? "form.confirm_subq_lc_random_pool"
                      : "form.confirm_subq_lc_selected",
                  ).replace("{n}", String(row.learning_content.length))}
                </div>
                <ul className="space-y-1">
                  {row.learning_content.map((code) => {
                    const entry = lcEntryByCode.get(code);
                    return (
                      <li key={code} className="flex gap-2 text-sm">
                        <span className="shrink-0 font-mono font-semibold text-gray-800">{code}</span>
                        {entry?.instruction && <span className="text-gray-600">— {entry.instruction}</span>}
                      </li>
                    );
                  })}
                </ul>
              </>
            ) : (
              <div className="text-sm text-gray-700">{t("form.confirm_subq_lc_empty")}</div>
            )}
          </div>
          <div>
            {row.learning_performance && row.learning_performance.length > 0 ? (
              <>
                <div className="mt-2 text-xs font-medium text-gray-600">
                  {t(
                    row._lpWasAutoDrawn
                      ? "form.confirm_subq_lp_random_pool"
                      : "form.confirm_subq_lp_selected",
                  ).replace("{n}", String(row.learning_performance.length))}
                </div>
                <ul className="space-y-1">
                  {row.learning_performance.map((code) => {
                    const entry = lpEntryByCode.get(code);
                    return (
                      <li key={code} className="flex gap-2 text-sm">
                        <span className="shrink-0 font-mono font-semibold text-gray-800">{code}</span>
                        {entry?.instruction && <span className="text-gray-600">— {entry.instruction}</span>}
                      </li>
                    );
                  })}
                </ul>
              </>
            ) : (
              <div className="text-sm text-gray-700">{t("form.confirm_subq_lp_empty")}</div>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

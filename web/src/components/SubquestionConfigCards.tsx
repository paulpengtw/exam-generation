import type { SchemaEntry } from "../api/client";
import type { SubQuestionConfig } from "../components/ParamForm";
import { useT } from "../i18n/useT";
import { SubQuestionInstructionField } from "./SubQuestionConfigEditor";

export type ResolvedSubQuestionConfig = SubQuestionConfig & {
  _lcWasAutoDrawn?: boolean;
  _lpWasAutoDrawn?: boolean;
};

export default function SubquestionConfigCards({
  configs,
  subject,
  lcEntryByCode,
  lpEntryByCode,
  onInstructionChange,
}: {
  configs: ResolvedSubQuestionConfig[];
  subject: string;
  lcEntryByCode: Map<string, SchemaEntry>;
  lpEntryByCode: Map<string, SchemaEntry>;
  onInstructionChange?: (subquestionIndex: number, instruction: string) => void;
}) {
  const t = useT();

  return (
    <ol className="space-y-3">
      {configs.map((row, subquestionIndex) => (
        <li key={subquestionIndex} className="rounded-lg border border-gray-200 bg-gray-50 p-3">
          <h5 className="mb-2 text-xs font-semibold text-gray-600">
            {t("form.confirm_subquestion_row_title").replace("{n}", String(subquestionIndex + 1))}
          </h5>
          <div className="text-sm text-gray-700">{t("form.confirm_subq_q_type")} {row.question_type ?? t("form.confirm_random")}</div>
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
          <div className="text-sm text-gray-700">{t("form.confirm_subq_content_type")} {row.content_type ?? t("form.confirm_inherit_text")}</div>
          <div className="text-sm text-gray-700">{t("form.confirm_subq_image_mode")} {row.image_generation_mode ?? t("form.confirm_inherit_text")}</div>
          <div className="text-sm text-gray-700">{t("form.confirm_subq_q_word_limit")} {row.question_word_limit ?? t("form.confirm_unlimited")}</div>
          <div className="text-sm text-gray-700">{t("form.confirm_subq_o_word_limit")} {row.option_word_limit ?? t("form.confirm_unlimited")}</div>
          <div className="text-sm text-gray-700">{t("form.confirm_subq_text_word_limit")} {row.text_word_limit ?? t("form.confirm_unlimited")}</div>
          {subject === "natural_sciences" && <div className="text-sm text-gray-700">{t("form.confirm_subq_reporting_scale")} {row.reporting_scale ?? t("form.confirm_random")}</div>}
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

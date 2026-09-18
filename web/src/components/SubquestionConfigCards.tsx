import { useId } from "react";
import type { SchemaEntry } from "../api/client";
import { useT } from "../i18n/useT";
import { SearchPicker, type SearchPickerEntry } from "./SubQuestionCurriculumPickers";
import type { SubQuestionConfig } from "../components/ParamForm";
import DrawnValueRows, { type DrawnValueLabelMap } from "./DrawnValueRows";
import {
  SubQuestionContentTypeField,
  SubQuestionFigureKindField,
  SubQuestionImageGenerationModeField,
  SubQuestionInstructionField,
  SubQuestionQuestionTypeField,
  SubQuestionReportingScaleField,
  SubQuestionWordLimitField,
} from "./SubQuestionConfigEditor";

export type ResolvedSubQuestionConfig = SubQuestionConfig;

function entriesWithCurrentValue(
  entries: readonly SchemaEntry[],
  value: string | undefined,
): SchemaEntry[] {
  if (!value || entries.some((entry) => entry.value === value)) return [...entries];
  return [...entries, { value, instruction: "" }];
}

export default function SubquestionConfigCards({
  configs,
  subject,
  questionIndex = 0,
  drawnPaths,
  drawnValueLabels,
  cognitiveProcesses,
  reportingScales,
  clearedPaths,
  contentDomain,
  showContentDomain = true,
  questionTypes,
  contentTypes,
  figureKinds,
  lcEntryByCode,
  lpEntryByCode,
  availableLc,
  availableLp,
  filteredLpPool,
  onInstructionChange,
  onQuestionTypeChange,
  onContentTypeChange,
  onImageModeChange,
  onFigureKindChange,
  onReportingScaleChange,
  onQuestionWordLimitChange,
  onOptionWordLimitChange,
  onFieldValidityChange,
  onLcChange,
  onLpChange,
  onCognitiveProcessChange,
  onFieldRedraw,
}: {
  configs: ResolvedSubQuestionConfig[];
  subject: string;
  /** Canonical resolver paths used to derive random badges for this question. */
  questionIndex?: number;
  drawnPaths?: readonly string[];
  /** Labels shared with the question-level generic confirmation rows. */
  drawnValueLabels?: DrawnValueLabelMap;
  cognitiveProcesses?: SchemaEntry[];
  reportingScales?: SchemaEntry[];
  clearedPaths?: readonly string[];
  /** Topic-set ICCS content domain shown in non-confirmation summaries. */
  contentDomain?: string;
  /** Confirmation renders the domain through ParamForm's generic row. */
  showContentDomain?: boolean;
  questionTypes: SchemaEntry[];
  contentTypes: SchemaEntry[];
  /** Canonical 圖像種類 vocabulary from the schemas endpoint. Issue #450. */
  figureKinds?: string[];
  lcEntryByCode: Map<string, SchemaEntry>;
  lpEntryByCode: Map<string, SchemaEntry>;
  /** Full subject-filtered LC pool for the SearchPicker. Required when onLcChange is provided. */
  availableLc?: SearchPickerEntry[];
  /** Full subject-filtered LP pool for the SearchPicker. Required when onLpChange is provided. */
  availableLp?: SearchPickerEntry[];
  /** Optional ICCS domain-filtered LP codes for 公民/跨科 confirmation pickers. */
  filteredLpPool?: string[];
  onInstructionChange?: (subquestionIndex: number, instruction: string) => void;
  onQuestionTypeChange?: (subquestionIndex: number, questionType: string) => void;
  onContentTypeChange?: (subquestionIndex: number, contentType: string) => void;
  onImageModeChange?: (subquestionIndex: number, imageMode: string) => void;
  onFigureKindChange?: (subquestionIndex: number, figureKind: string) => void;
  onReportingScaleChange?: (subquestionIndex: number, reportingScale: string) => void;
  onQuestionWordLimitChange?: (subquestionIndex: number, value: number | undefined) => void;
  onOptionWordLimitChange?: (subquestionIndex: number, value: number | undefined) => void;
  /** Generic gate: called whenever a field's validity changes. fieldKey is a stable opaque string. */
  onFieldValidityChange?: (subquestionIndex: number, fieldKey: string, isValid: boolean) => void;
  /** Called when the user explicitly changes LC codes for a 小題. */
  onLcChange?: (subquestionIndex: number, lc: string[]) => void;
  /** Called when the user explicitly changes LP codes for a 小題. */
  onLpChange?: (subquestionIndex: number, lp: string[]) => void;
  onCognitiveProcessChange?: (subquestionIndex: number, cognitiveProcess: string) => void;
  /** Called when the user requests a resolver redraw for a 小題 field. */
  onFieldRedraw?: (subquestionIndex: number, field: string) => void;
}) {
  const t = useT();
  const resolverDrew = (subquestionIndex: number, field: string): boolean => {
    if (drawnPaths === undefined) return false;
    const prefix = `per_question_params[${questionIndex}].subquestion_configs[${subquestionIndex}].`;
    const canonical = field === "cognitive_process" ? "認知歷程" : field;
    return drawnPaths.includes(`${prefix}${field}`) || drawnPaths.includes(`${prefix}${canonical}`);
  };
  // Base ID for associating labels with SearchPicker inputs — forward-compat hook
  // for #506 which will add a domain-scoped pool filter on top of this picker.
  const baseId = useId();
  const visibleAvailableLc = availableLc ?? [];
  const visibleAvailableLp = filteredLpPool === undefined
    ? availableLp ?? []
    : (availableLp ?? []).filter((entry) => filteredLpPool.includes(entry.value));
  const defaultDrawnValueLabels: DrawnValueLabelMap = {
    "認知歷程": t("form.confirm_subq_cognitive_process").replace(/[：:]\s*$/, ""),
    reporting_scale: t("form.confirm_reporting_scale"),
  };
  const readDrawnValue = (path: string, row: ResolvedSubQuestionConfig): unknown => {
    const field = path.match(/(?:^|\.)([^.[\]]+)$/)?.[1];
    if (!field) return undefined;
    const key = field === "認知歷程" ? "cognitive_process" : field;
    const values = row as unknown as Record<string, unknown>;
    return values[key] ?? values[field === "cognitive_process" ? "認知歷程" : field];
  };

  return (
    <>
      {subject === "social_studies" && showContentDomain && (
        <div className="mb-3 text-sm font-medium text-gray-700">
          {t("form.confirm_content_domain")}: {contentDomain ?? t("form.confirm_backend_sampled")}
        </div>
      )}
      <ol className="space-y-3">
        {configs.map((row, subquestionIndex) => {
        const lcPickerId = `${baseId}-${subquestionIndex}-lc`;
        const lpPickerId = `${baseId}-${subquestionIndex}-lp`;
        const cognitivePath = `per_question_params[${questionIndex}].subquestion_configs[${subquestionIndex}].認知歷程`;
        const reportingScalePath = `per_question_params[${questionIndex}].subquestion_configs[${subquestionIndex}].reporting_scale`;
        const slotPathPrefix = `per_question_params[${questionIndex}].subquestion_configs[${subquestionIndex}].`;
        // Keep captured codes visible even when the current schema/domain pool
        // no longer admits them. The parent confirmation gate marks them
        // invalid; filtering here would silently hide the value to correct.
        const visibleLearningContent = row.learning_content ?? [];
        const visibleLearningPerformance = row.learning_performance ?? [];

        return (
          <li key={subquestionIndex} className="rounded-lg border border-gray-200 bg-gray-50 p-3">
            <h5 className="mb-2 text-xs font-semibold text-gray-600">
              {t("form.confirm_subquestion_row_title").replace("{n}", String(subquestionIndex + 1))}
            </h5>
            {drawnPaths !== undefined && (subject === "social_studies" || subject === "natural_sciences") && (
              <DrawnValueRows
                drawnPaths={drawnPaths}
                fieldLabels={drawnValueLabels ?? defaultDrawnValueLabels}
                pathPrefix={slotPathPrefix}
                alwaysPaths={[subject === "social_studies" ? cognitivePath : reportingScalePath]}
                valueForPath={(path) => readDrawnValue(path, row)}
                renderEditor={subject === "social_studies" ? (path, value) => path.endsWith(".認知歷程") ? (
                  <select
                    aria-label={t("form.confirm_subq_cognitive_process")}
                    value={typeof value === "string" ? value : ""}
                    onChange={(event) => onCognitiveProcessChange?.(
                      subquestionIndex,
                      event.currentTarget.value,
                    )}
                    className="rounded border border-gray-300 bg-white px-2 py-1 text-sm"
                  >
                    <option value="">{t("form.confirm_not_filled")}</option>
                    {entriesWithCurrentValue(
                      cognitiveProcesses ?? [],
                      typeof value === "string" ? value : undefined,
                    ).map((entry) => (
                      <option key={entry.value} value={entry.value}>{entry.value}</option>
                    ))}
                  </select>
                ) : undefined : subject === "natural_sciences" && onReportingScaleChange ? (path) => path.endsWith(".reporting_scale") ? (
                  <SubQuestionReportingScaleField
                    config={row}
                    options={reportingScales}
                    hideLabel
                    emptyOptionLabel={t("form.confirm_not_filled")}
                    onChange={(patch) => onReportingScaleChange(subquestionIndex, patch.reporting_scale ?? "")}
                  />
                ) : undefined : undefined}
                renderValue={subject === "natural_sciences" && onReportingScaleChange
                  ? (path) => path.endsWith(".reporting_scale")
                    ? (
                        <SubQuestionReportingScaleField
                          config={row}
                          options={reportingScales}
                          hideLabel
                          emptyOptionLabel={t("form.confirm_not_filled")}
                          onChange={(patch) => onReportingScaleChange(subquestionIndex, patch.reporting_scale ?? "")}
                        />
                      )
                    : undefined
                  : undefined}
                emptyValue={t("form.confirm_not_filled")}
                drawnBadge={t("form.confirm_badge_random")}
                pinnedBadge={t("form.confirm_badge_user")}
                onRedraw={(path) => {
                  if (path.endsWith(".認知歷程")) onFieldRedraw?.(subquestionIndex, "cognitive_process");
                  if (path.endsWith(".reporting_scale")) onFieldRedraw?.(subquestionIndex, "reporting_scale");
                }}
                canEdit={(path) => path.endsWith(".認知歷程") || path.endsWith(".reporting_scale")}
                canRedraw={(path) => path.endsWith(".認知歷程") || path.endsWith(".reporting_scale")}
                editLabel={t("form.confirm_edit")}
                redrawLabel={t("form.confirm_redraw")}
                clearedPaths={clearedPaths}
                clearedNotice={t("form.confirm_cleared_notice")}
                compact
              />
            )}
            {onQuestionTypeChange ? (
              <div>
                <SubQuestionQuestionTypeField
                  config={row}
                  subject={subject}
                  questionTypes={questionTypes}
                  emptyOptionLabel={t("form.confirm_not_filled")}
                  badge={{
                    label: t(resolverDrew(subquestionIndex, "question_type") || !row.question_type?.trim() ? "form.confirm_badge_random" : "form.confirm_badge_user"),
                    className: `text-xs font-medium ${resolverDrew(subquestionIndex, "question_type") || !row.question_type?.trim() ? "text-amber-700" : "text-green-700"}`,
                  }}
                  onChange={(patch) => onQuestionTypeChange(subquestionIndex, patch.question_type ?? "")}
                />
                {resolverDrew(subquestionIndex, "question_type") && onFieldRedraw && (
                  <button
                    type="button"
                    onClick={() => onFieldRedraw(subquestionIndex, "question_type")}
                    className="mt-1 rounded border border-amber-300 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800 hover:bg-amber-100"
                  >
                    {t("form.confirm_redraw")}
                  </button>
                )}
              </div>
            ) : (
              <div className="text-sm text-gray-700">{t("form.confirm_subq_q_type")} {row.question_type ?? t("form.confirm_random")}</div>
            )}
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
            {onQuestionWordLimitChange ? (
              <SubQuestionWordLimitField
                config={row}
                field="question_word_limit"
                labelKey="form.confirm_subq_q_word_limit_input"
                placeholder={t("form.confirm_unlimited")}
                badge={{
                  label: t(row.question_word_limit != null ? "form.confirm_badge_user" : "form.confirm_badge_unlimited"),
                  className: `text-xs font-medium ${row.question_word_limit != null ? "text-green-700" : "text-gray-600"}`,
                }}
                onChange={(patch) => {
                  const v = (patch as Partial<SubQuestionConfig>).question_word_limit;
                  onQuestionWordLimitChange(subquestionIndex, v);
                }}
                onValidityChange={(isValid) => onFieldValidityChange?.(subquestionIndex, "question_word_limit", isValid)}
              />
            ) : (
              <div className="text-sm text-gray-700">{t("form.confirm_subq_q_word_limit")} {row.question_word_limit ?? t("form.confirm_unlimited")}</div>
            )}
            {onOptionWordLimitChange ? (
              <SubQuestionWordLimitField
                config={row}
                field="option_word_limit"
                labelKey="form.confirm_subq_o_word_limit_input"
                placeholder={t("form.confirm_unlimited")}
                badge={{
                  label: t(row.option_word_limit != null ? "form.confirm_badge_user" : "form.confirm_badge_unlimited"),
                  className: `text-xs font-medium ${row.option_word_limit != null ? "text-green-700" : "text-gray-600"}`,
                }}
                onChange={(patch) => {
                  const v = (patch as Partial<SubQuestionConfig>).option_word_limit;
                  onOptionWordLimitChange(subquestionIndex, v);
                }}
                onValidityChange={(isValid) => onFieldValidityChange?.(subquestionIndex, "option_word_limit", isValid)}
              />
            ) : (
              <div className="text-sm text-gray-700">{t("form.confirm_subq_o_word_limit")} {row.option_word_limit ?? t("form.confirm_unlimited")}</div>
            )}
            {/* 圖像種類 — editable when callback provided, read-only otherwise (issue #450) */}
            {(subject === "social_studies" || subject === "natural_sciences") && (
              onFigureKindChange && figureKinds !== undefined ? (
                <SubQuestionFigureKindField
                  config={row}
                  figureKinds={figureKinds}
                  badge={{
                    label: t(row.figure_kind?.trim() ? "form.confirm_badge_user" : "form.confirm_badge_inherit"),
                    className: `text-xs font-medium ${row.figure_kind?.trim() ? "text-green-700" : "text-gray-600"}`,
                  }}
                  onChange={(patch) => onFigureKindChange(subquestionIndex, patch.figure_kind ?? "")}
                />
              ) : (
                row.figure_kind?.trim()
                  ? <div className="text-sm text-gray-700">{t("form.confirm_subq_figure_kind")} <span>{row.figure_kind}</span></div>
                  : null
              )
            )}
            {/* 學習內容 — editable picker when callback provided, read-only otherwise */}
            <div>
              {onLcChange ? (
                <div className="mt-2">
                  <div className="flex items-center gap-2">
                    <label
                      htmlFor={lcPickerId}
                      className="text-xs font-medium text-gray-600"
                    >
                      {t("form.confirm_subq_lc_label")}
                    </label>
                    <span
                      className={`text-xs font-medium ${
                        resolverDrew(subquestionIndex, "learning_content") ? "text-amber-700" : "text-green-700"
                      }`}
                    >
                      {t(
                        resolverDrew(subquestionIndex, "learning_content")
                          ? "form.confirm_badge_random"
                          : "form.confirm_badge_user",
                      )}
                    </span>
                  </div>
                  <SearchPicker
                    id={lcPickerId}
                    available={visibleAvailableLc}
                    selected={visibleLearningContent}
                    onChange={(values) => onLcChange(subquestionIndex, values)}
                    maxSelected={3}
                    placeholder={t("form.confirm_subq_lc_picker_placeholder")}
                  />
                  {clearedPaths?.includes(`${slotPathPrefix}learning_content`) && (
                    <span className="text-xs font-medium text-amber-700">
                      {t("form.confirm_cleared_notice")}
                    </span>
                  )}
                  {resolverDrew(subquestionIndex, "learning_content") && onFieldRedraw && (
                    <button
                      type="button"
                      onClick={() => onFieldRedraw(subquestionIndex, "learning_content")}
                      className="mt-1 rounded border border-amber-300 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800 hover:bg-amber-100"
                    >
                      {t("form.confirm_redraw")}
                    </button>
                  )}
                </div>
              ) : (
                <>
                  {visibleLearningContent.length > 0 ? (
                    <>
                      <div className="mt-2 text-xs font-medium text-gray-600">
                        {t(
                          resolverDrew(subquestionIndex, "learning_content")
                            ? "form.confirm_subq_lc_random_pool"
                            : "form.confirm_subq_lc_selected",
                        ).replace("{n}", String(visibleLearningContent.length))}
                      </div>
                      <ul className="space-y-1">
                        {visibleLearningContent.map((code) => {
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
                </>
              )}
            </div>

            {/* 學習表現 — editable picker when callback provided, read-only otherwise */}
            <div>
              {onLpChange ? (
                <div className="mt-2">
                  <div className="flex items-center gap-2">
                    <label
                      htmlFor={lpPickerId}
                      className="text-xs font-medium text-gray-600"
                    >
                      {t("form.confirm_subq_lp_label")}
                    </label>
                    <span
                      className={`text-xs font-medium ${
                        resolverDrew(subquestionIndex, "learning_performance") ? "text-amber-700" : "text-green-700"
                      }`}
                    >
                      {t(
                        resolverDrew(subquestionIndex, "learning_performance")
                          ? "form.confirm_badge_random"
                          : "form.confirm_badge_user",
                      )}
                    </span>
                  </div>
                  <SearchPicker
                    id={lpPickerId}
                    available={visibleAvailableLp}
                    selected={visibleLearningPerformance}
                    onChange={(values) => onLpChange(subquestionIndex, values)}
                    maxSelected={2}
                    placeholder={t("form.confirm_subq_lp_picker_placeholder")}
                  />
                  {clearedPaths?.includes(`${slotPathPrefix}learning_performance`) && (
                    <span className="text-xs font-medium text-amber-700">
                      {t("form.confirm_cleared_notice")}
                    </span>
                  )}
                  {resolverDrew(subquestionIndex, "learning_performance") && onFieldRedraw && (
                    <button
                      type="button"
                      onClick={() => onFieldRedraw(subquestionIndex, "learning_performance")}
                      className="mt-1 rounded border border-amber-300 bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800 hover:bg-amber-100"
                    >
                      {t("form.confirm_redraw")}
                    </button>
                  )}
                </div>
              ) : (
                <>
                  {visibleLearningPerformance.length > 0 ? (
                    <>
                      <div className="mt-2 text-xs font-medium text-gray-600">
                        {t(
                          resolverDrew(subquestionIndex, "learning_performance")
                            ? "form.confirm_subq_lp_random_pool"
                            : "form.confirm_subq_lp_selected",
                        ).replace("{n}", String(visibleLearningPerformance.length))}
                      </div>
                      <ul className="space-y-1">
                        {visibleLearningPerformance.map((code) => {
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
                </>
              )}
            </div>
          </li>
        );
        })}
      </ol>
    </>
  );
}

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "../api/client";
import type { DraftPhase, ExamQuestion, SubQuestion, RubricEntry } from "../hooks/useGenerate";
import { useModificationRun } from "../hooks/useModificationRun";
import { useT } from "../i18n/useT";
import { recordFigureFallback } from "../utils/figureFallbackMetric";
import { buildExamOdt, formatTimestamp } from "../utils/odt";
import FigureRenderer, {
  classifySpec,
  isFrontendTsEnabled,
  type ChartSpecInput,
} from "./FigureRenderer";
import GenerationStatusBar from "./GenerationStatusBar";
import InteractiveItemViewer, { type InteractionSubmission } from "./InteractiveItemViewer";

export interface QuestionCardProps {
  question: ExamQuestion;
  recordId?: string;
  phase?: DraftPhase;
  isFinal?: boolean;
  onInteractionSubmit?: (submission: InteractionSubmission) => void;
}

interface VerificationShape {
  passed?: boolean;
}

interface SelectionSegment {
  field_path: string;
  start: number;
  end: number;
  quoted_text: string;
}

interface ModificationAnnotation {
  id: number;
  segments: SelectionSegment[];
  instruction: string;
}

interface ModificationSubmitError {
  code?: string;
  message: string;
}

const MODIFICATION_ERROR_TITLE_KEYS: Record<string, string> = {
  stale_base: "card.modificationError.stale_base",
  frozen_field: "card.modificationError.frozen_field",
  empty_annotation: "card.modificationError.empty_annotation",
  missing_instruction: "card.modificationError.missing_instruction",
  not_latest: "card.modificationError.not_latest",
  not_latest_version: "card.modificationError.not_latest_version",
  run_in_progress: "card.modificationError.run_in_progress",
};

function getModificationSubmitError(error: unknown, fallback: string): ModificationSubmitError {
  if (error instanceof ApiError) {
    return { code: error.code, message: error.detail };
  }
  return {
    message: error instanceof Error ? error.message : fallback,
  };
}

function getQuestionId(question: ExamQuestion): string {
  return question.id && question.id.length > 0 ? question.id : "question";
}

function comparePoints(
  leftContainer: Node,
  leftOffset: number,
  rightContainer: Node,
  rightOffset: number,
): number {
  const left = document.createRange();
  left.setStart(leftContainer, leftOffset);
  left.collapse(true);
  const right = document.createRange();
  right.setStart(rightContainer, rightOffset);
  right.collapse(true);
  return left.compareBoundaryPoints(Range.START_TO_START, right);
}

function isWithinField(field: HTMLElement, container: Node): boolean {
  return container === field || field.contains(container);
}

function offsetWithinField(field: HTMLElement, container: Node, offset: number): number {
  const prefix = document.createRange();
  prefix.selectNodeContents(field);
  prefix.setEnd(container, offset);
  return prefix.toString().length;
}

function serializeSelection(root: HTMLElement, range: Range): SelectionSegment[] {
  if (!root.contains(range.commonAncestorContainer)) return [];

  const fields = Array.from(
    root.querySelectorAll<HTMLElement>("[data-selection-field]"),
  );
  const segments: SelectionSegment[] = [];

  for (const field of fields) {
    const fieldPath = field.dataset.selectionField;
    if (!fieldPath) continue;

    const fieldRange = document.createRange();
    fieldRange.selectNodeContents(field);
    const startsAfterField = comparePoints(
      range.startContainer,
      range.startOffset,
      fieldRange.endContainer,
      fieldRange.endOffset,
    ) >= 0;
    const endsBeforeField = comparePoints(
      range.endContainer,
      range.endOffset,
      fieldRange.startContainer,
      fieldRange.startOffset,
    ) <= 0;
    if (startsAfterField || endsBeforeField) continue;

    const fieldText = field.textContent ?? "";
    const start = isWithinField(field, range.startContainer)
      ? offsetWithinField(field, range.startContainer, range.startOffset)
      : 0;
    const end = isWithinField(field, range.endContainer)
      ? offsetWithinField(field, range.endContainer, range.endOffset)
      : fieldText.length;
    if (start >= end) continue;

    segments.push({
      field_path: fieldPath,
      start,
      end,
      quoted_text: fieldText.slice(start, end),
    });
  }

  return segments;
}

function selectionFieldProps(fieldPath: string, enabled: boolean): { "data-selection-field"?: string } {
  return enabled ? { "data-selection-field": fieldPath } : {};
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function base64ToBlob(base64: string, mimeType: string): Blob {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new Blob([bytes], { type: mimeType });
}

function pickFigure(
  chartSpec: unknown,
  imageBase64: string | undefined,
  alt: string,
): { kind: "ts"; spec: ChartSpecInput } | { kind: "png"; src: string } | null {
  if (isFrontendTsEnabled() && chartSpec && typeof chartSpec === "object") {
    const spec = chartSpec as ChartSpecInput;
    if (classifySpec(spec) !== "unsupported") {
      return { kind: "ts", spec };
    }
    recordFigureFallback(spec);
  }
  if (imageBase64) {
    return { kind: "png", src: `data:image/png;base64,${imageBase64}` };
  }
  // Silence unused-var lint when neither branch fires.
  void alt;
  return null;
}

function getLearningContentCodes(question: ExamQuestion): string[] {
  return (question.學習內容 ?? []).map((item) => item.編碼).filter(Boolean);
}

function aggregateUnique<T>(subs: SubQuestion[], picker: (s: SubQuestion) => T[]): T[] {
  const seen = new Set<string>();
  const result: T[] = [];
  for (const sub of subs) {
    for (const val of picker(sub)) {
      const key = String(val);
      if (!seen.has(key)) {
        seen.add(key);
        result.push(val);
      }
    }
  }
  return result;
}

const RUBRIC_TONE: Record<string, string> = {
  "2": "bg-green-100 text-green-800",
  "1": "bg-yellow-100 text-yellow-800",
  "0": "bg-red-100 text-red-800",
  "0X": "bg-gray-100 text-gray-500",
};

function DistractorPanel({
  analysis,
  selectionEnabled = false,
  fieldPathPrefix = "誘答分析",
}: {
  analysis: Record<string, string>;
  selectionEnabled?: boolean;
  fieldPathPrefix?: string;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const entries = Object.entries(analysis);
  if (entries.length === 0) return null;
  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="text-sm font-medium text-amber-700 hover:text-amber-800"
      >
        {open ? t("card.hideDistractor") : t("card.showDistractor")}
      </button>
      {open && (
        <div className="mt-2 rounded border border-amber-200 bg-amber-50 p-3 space-y-1 text-sm">
          <div className="font-medium text-amber-800 mb-1">{t("card.distractorAnalysis")}</div>
          {entries.map(([label, note]) => (
            <div key={label} className="flex gap-2 items-start">
              <span className="inline-flex shrink-0 items-center rounded bg-amber-200 px-1.5 py-0.5 text-xs font-bold text-amber-900">
                {label}
              </span>
              <span
                className="whitespace-pre-wrap text-amber-900"
                {...selectionFieldProps(`${fieldPathPrefix}.${label}`, selectionEnabled)}
              >
                {note}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SubQuestionBlock({
  sub,
  index,
  showAnswersByDefault = false,
  selectionEnabled,
  onInteractionSubmit,
}: {
  sub: SubQuestion;
  index: number;
  showAnswersByDefault?: boolean;
  selectionEnabled: boolean;
  onInteractionSubmit?: (submission: InteractionSubmission) => void;
}) {
  const t = useT();
  const [showAnswer, setShowAnswer] = useState(showAnswersByDefault);

  return (
    <div className="rounded border border-gray-100 bg-gray-50 p-3 space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-xs font-semibold text-gray-500">
          {t("card.subquestion")}{sub.序號}題
        </span>
        <Chip label={`${sub.年級}年級`} tone="blue" />
        <Chip label={sub.題型} tone="purple" />
        {sub.科目.map((s) => (
          <Chip key={`subj-${s}`} label={s} tone="purple" />
        ))}
        {(sub.科學能力 ?? []).map((c) => (
          <Chip key={`sci-${c}`} label={c} tone="amber" />
        ))}
        {sub.核心素養.map((c) => (
          <Chip key={`cc-${c}`} label={c} tone="amber" />
        ))}
        {sub.學習內容.map((lc) => (
          <Chip key={`lc-${lc.編碼}`} label={lc.編碼} tone="gray" title={lc.說明} />
        ))}
        {sub.學習表現.map((lp) => (
          <Chip key={`lp-${lp.編碼}`} label={lp.編碼} tone="teal" title={lp.說明} />
        ))}
      </div>

      {(() => {
        const figure = pickFigure(sub.chart_spec, sub.image_base64, `第${sub.序號}題素材圖片`);
        if (!figure) return null;
        if (figure.kind === "ts") {
          return (
            <div className="rounded border border-gray-200 bg-white p-2">
              <FigureRenderer spec={figure.spec} alt={`第${sub.序號}題素材圖片`} />
            </div>
          );
        }
        return (
          <img
            src={figure.src}
            alt={`第${sub.序號}題素材圖片`}
            className="max-w-full rounded border border-gray-200 bg-white"
          />
        );
      })()}

      <div
        className="text-sm leading-relaxed whitespace-pre-wrap"
        {...selectionFieldProps(`subquestions[${index}].題目`, selectionEnabled)}
      >
        {sub.題目}
      </div>

      {sub.interaction && (
        <InteractiveItemViewer
          itemId={sub.id || `subquestion-${index + 1}`}
          題型={sub.題型}
          interaction={sub.interaction}
          distractorAnalysis={sub.誘答分析}
          onSubmit={onInteractionSubmit}
        />
      )}

      <div>
        <button
          type="button"
          onClick={() => setShowAnswer((v) => !v)}
          className="text-sm font-medium text-blue-600 hover:text-blue-700"
        >
          {showAnswer ? t("card.hide_answer") : t("card.show_answer")}
        </button>
        {showAnswer && (
          <div className="mt-2 rounded bg-white border border-gray-200 p-3 space-y-2 text-sm">
            {sub.答案 && (
              <div>
                <span className="font-medium text-gray-700">{t("card.answer")}：</span>
                <span
                  className="whitespace-pre-wrap"
                  {...selectionFieldProps(`subquestions[${index}].答案`, selectionEnabled)}
                >
                  {sub.答案}
                </span>
              </div>
            )}
            {sub.答案解析 && (
              <div>
                <span className="font-medium text-gray-700">{t("card.answerExplanation")}：</span>
                <span
                  className="whitespace-pre-wrap"
                  {...selectionFieldProps(`subquestions[${index}].答案解析`, selectionEnabled)}
                >
                  {sub.答案解析}
                </span>
              </div>
            )}
            {sub.評分規準 && sub.評分規準.length > 0 && (
              <div>
                <div className="font-medium text-gray-700 mb-1">{t("card.rubric")}</div>
                <div className="space-y-1">
                  {sub.評分規準.map((r: RubricEntry, rubricIndex) => (
                    <div key={r.code} className="flex gap-2 items-start">
                      <span className={`inline-flex shrink-0 items-center rounded px-1.5 py-0.5 text-xs font-bold ${RUBRIC_TONE[r.code] ?? "bg-gray-100 text-gray-600"}`}>
                        {r.code}
                      </span>
                      <span
                        className="text-xs leading-relaxed text-gray-700"
                        {...selectionFieldProps(
                          `subquestions[${index}].評分規準[${rubricIndex}].規準說明`,
                          selectionEnabled,
                        )}
                      >
                        {r.規準說明}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {sub.誘答分析 && Object.keys(sub.誘答分析).length > 0 && (
              <DistractorPanel
                analysis={sub.誘答分析}
                selectionEnabled={selectionEnabled}
                fieldPathPrefix={`subquestions[${index}].誘答分析`}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default function QuestionCard({
  question: initialQuestion,
  recordId,
  phase = "verified",
  isFinal = true,
  onInteractionSubmit,
}: QuestionCardProps) {
  const t = useT();
  const [showSolution, setShowSolution] = useState(!isFinal);
  const cardRef = useRef<HTMLDivElement>(null);
  const nextAnnotationId = useRef(0);
  const [annotations, setAnnotations] = useState<ModificationAnnotation[]>([]);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<ModificationSubmitError | null>(null);
  const modificationRun = useModificationRun(recordId);
  const modificationResult = modificationRun.result;
  const isRunInFlight = modificationRun.status === "running";

  useEffect(() => {
    if (modificationRun.result === null) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- clear the prior review round when the SSE stream publishes a replacement question
    setAnnotations([]);
    setSelectionError(null);
    setSubmitError(null);
  }, [modificationRun.result]);

  const question = modificationResult?.question ?? initialQuestion;
  const verification = question.verification as VerificationShape | undefined;
  const passed = Boolean(verification?.passed);
  const selectionEnabled = isFinal && (passed || modificationResult !== null);
  const questionId = getQuestionId(question);
  const isSocialStudies = (question.subquestions?.length ?? 0) > 0;
  const phaseLabel = isFinal
    ? t("card.final")
    : t(`card.phase_${phase}` as Parameters<typeof t>[0]);

  const mathCodes = useMemo(() => getLearningContentCodes(question), [question]);

  const ssGrades = useMemo(
    () => isSocialStudies ? aggregateUnique(question.subquestions!, (s) => [s.年級]) : [],
    [question.subquestions, isSocialStudies]
  );
  const ssSubjects = useMemo(
    () => isSocialStudies ? aggregateUnique(question.subquestions!, (s) => s.科目) : [],
    [question.subquestions, isSocialStudies]
  );
  const ssCoreComp = useMemo(
    () => isSocialStudies ? aggregateUnique(question.subquestions!, (s) => s.核心素養) : [],
    [question.subquestions, isSocialStudies]
  );
  const ssScienceComp = useMemo(
    () => isSocialStudies ? aggregateUnique(question.subquestions!, (s) => s.科學能力 ?? []) : [],
    [question.subquestions, isSocialStudies]
  );
  const ssLcCodes = useMemo(
    () => isSocialStudies ? aggregateUnique(question.subquestions!, (s) => s.學習內容.map((lc) => lc.編碼)) : [],
    [question.subquestions, isSocialStudies]
  );
  const ssLpCodes = useMemo(
    () => isSocialStudies ? aggregateUnique(question.subquestions!, (s) => s.學習表現.map((lp) => lp.編碼)) : [],
    [question.subquestions, isSocialStudies]
  );

  const handleDownloadJson = () => {
    const json = JSON.stringify(question, null, 2);
    const blob = new Blob([json], { type: "application/json" });
    downloadBlob(blob, `${questionId}.json`);
  };

  const handleDownloadPng = () => {
    if (!question.image_base64) return;
    const blob = base64ToBlob(question.image_base64, "image/png");
    downloadBlob(blob, `${questionId}.png`);
  };

  const handleDownloadOdt = () => {
    const ts = formatTimestamp();
    buildExamOdt(`exam_${ts}`, [question]).then((blob) => {
      downloadBlob(blob, `exam_${ts}.odt`);
    });
  };

  const handleSelectionMouseUp = useCallback(() => {
    if (!selectionEnabled || isRunInFlight || !cardRef.current) return;
    const selection = window.getSelection();
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return;

    const segments = serializeSelection(cardRef.current, selection.getRangeAt(0));
    if (segments.length === 0) {
      setSelectionError(t("card.emptySelection"));
      selection.removeAllRanges();
      return;
    }

    setSelectionError(null);
    setSubmitError(null);
    setAnnotations((previous) => [
      ...previous,
      {
        id: nextAnnotationId.current++,
        segments,
        instruction: "",
      },
    ]);
    selection.removeAllRanges();
  }, [isRunInFlight, selectionEnabled, t]);

  const handleInstructionChange = (annotationId: number, instruction: string) => {
    setAnnotations((previous) => previous.map((annotation) => (
      annotation.id === annotationId ? { ...annotation, instruction } : annotation
    )));
    setSubmitError(null);
  };

  const handleDeleteAnnotation = (annotationId: number) => {
    setAnnotations((previous) => previous.filter((annotation) => annotation.id !== annotationId));
    setSubmitError(null);
  };

  const canSubmit = Boolean(
    recordId &&
    !isRunInFlight &&
    annotations.length > 0 &&
    annotations.every((annotation) => annotation.instruction.trim().length > 0),
  );

  const handleSubmit = async () => {
    if (!recordId || !canSubmit || isRunInFlight) return;

    setSubmitError(null);
    void modificationRun.start({
      annotations: annotations.map((annotation) => ({
        segments: annotation.segments,
        修改指示: annotation.instruction,
      })),
    });
  };

  const runError = modificationRun.error === null
    ? null
    : getModificationSubmitError(modificationRun.error, t("card.modificationSubmitError"));
  const displayedSubmitError = runError ?? submitError;

  return (
    <div
      ref={cardRef}
      onMouseUp={handleSelectionMouseUp}
      className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm space-y-3"
    >
      {isRunInFlight && (
        <GenerationStatusBar
          runState="running"
          completedCount={0}
          requestedTotal={1}
          subject="math"
          stageEvents={[]}
          subQuestionCount={null}
          startedAt={null}
          finishedAt={null}
          availableTargets={[]}
          onJump={() => {}}
          onFeedback={null}
          mode="modification"
          modificationStageEvents={modificationRun.stageEvents}
        />
      )}

      {/* Header chips */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-wrap gap-1.5">
          {!isFinal && (
            <Chip label={phaseLabel} tone="orange" />
          )}
          {isSocialStudies ? (
            <>
              {ssGrades.map((g) => (
                <Chip key={`g-${g}`} label={`${g}年級`} tone="blue" />
              ))}
              {ssSubjects.map((s) => (
                <Chip key={`s-${s}`} label={s} tone="purple" />
              ))}
              {ssCoreComp.map((c) => (
                <Chip key={`cc-${c}`} label={c} tone="amber" />
              ))}
              {ssScienceComp.map((c) => (
                <Chip key={`sci-${c}`} label={c} tone="amber" />
              ))}
              {question.情境子類別 && (
                <Chip label={question.情境子類別} tone="blue" />
              )}
              {ssLcCodes.map((code) => (
                <Chip key={`lc-${code}`} label={code} tone="gray" />
              ))}
              {ssLpCodes.map((code) => (
                <Chip key={`lp-${code}`} label={code} tone="teal" />
              ))}
            </>
          ) : (
            <>
              {(question.情境 ?? []).map((c) => (
                <Chip key={`ctx-${c}`} label={c} tone="blue" />
              ))}
              <Chip label={question.題型種類} tone="purple" />
              <Chip label={question.題型} tone="purple" />
              {(question.數學思考 ?? []).map((m) => (
                <Chip key={`mt-${m}`} label={m} tone="amber" />
              ))}
              {mathCodes.map((code) => (
                <Chip key={`code-${code}`} label={code} tone="gray" />
              ))}
            </>
          )}
          {modificationResult && (
            <Chip label={t("card.modified")} tone="green" />
          )}
        </div>
        <VerificationBadge passed={passed} verifiedLabel={t("card.verified")} unverifiedLabel={t("card.unverified")} />
      </div>

      {question.image_stale && (
        <div
          role="status"
          className="rounded border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900"
        >
          {t("card.imageStale")}
        </div>
      )}

      {(() => {
        const figure = pickFigure(question.chart_spec, question.image_base64, "Question diagram");
        if (!figure) return null;
        if (figure.kind === "ts") {
          return (
            <div className="rounded border border-gray-200 p-2">
              <FigureRenderer spec={figure.spec} alt="Question diagram" />
            </div>
          );
        }
        return (
          <img
            src={figure.src}
            alt="Question diagram"
            className="max-w-full rounded border border-gray-200"
          />
        );
      })()}

      {/* Social studies: core question + passage + subquestions */}
      {isSocialStudies ? (
        <div className="space-y-3">
          {question.核心問題 && (
            <div className="rounded bg-blue-50 border border-blue-100 p-3">
              <div className="text-xs font-semibold text-blue-600 mb-1">{t("card.coreQuestion")}</div>
              <div
                className="text-sm leading-relaxed whitespace-pre-wrap"
                {...selectionFieldProps("核心問題", selectionEnabled)}
              >
                {question.核心問題}
              </div>
            </div>
          )}
          {question.文本 && (
            <div className="rounded bg-gray-50 border border-gray-200 p-3">
              <div className="text-xs font-semibold text-gray-500 mb-1">{t("card.passage")}</div>
              <div
                className="text-sm leading-relaxed whitespace-pre-wrap"
                {...selectionFieldProps("文本", selectionEnabled)}
              >
                {question.文本}
              </div>
            </div>
          )}
          <div className="space-y-2">
            {question.subquestions!.map((sub, index) => (
              <SubQuestionBlock
                key={sub.id}
                sub={sub}
                index={index}
                showAnswersByDefault={!isFinal}
                selectionEnabled={selectionEnabled}
                onInteractionSubmit={onInteractionSubmit}
              />
            ))}
          </div>
        </div>
      ) : (
        <>
          <div className="space-y-1 text-sm leading-relaxed">
            {question.題目.map((line, i) => (
              <p
                key={i}
                className="whitespace-pre-wrap"
                {...selectionFieldProps(`題目[${i}]`, selectionEnabled)}
              >
                {line}
              </p>
            ))}
          </div>

          <div>
            <button
              type="button"
              onClick={() => setShowSolution((v) => !v)}
              className="text-sm font-medium text-blue-600 hover:text-blue-700"
            >
              {showSolution ? t("card.hide_solution") : t("card.show_solution")}
            </button>
            {showSolution && (
              <div className="mt-2 space-y-1 rounded bg-gray-50 p-3 text-sm leading-relaxed">
                {question.正確解題分析.map((line, i) => (
                  <p
                    key={i}
                    className="whitespace-pre-wrap"
                    {...selectionFieldProps(`正確解題分析[${i}]`, selectionEnabled)}
                  >
                    {line}
                  </p>
                ))}
                {question.誘答分析 && Object.keys(question.誘答分析).length > 0 && (
                  <DistractorPanel
                    analysis={question.誘答分析}
                    selectionEnabled={selectionEnabled}
                    fieldPathPrefix="誘答分析"
                  />
                )}
              </div>
            )}
          </div>
        </>
      )}

      {modificationResult && (
        <>
          <section
            aria-label={t("card.rippleReport")}
            className="rounded border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900"
          >
            <h3 className="font-semibold">{t("card.rippleReport")}</h3>
            {modificationResult.ripple_report.length > 0 ? (
              <ul className="mt-1 list-disc space-y-1 pl-5">
                {modificationResult.ripple_report.map((fieldPath) => (
                  <li key={fieldPath}>{fieldPath}</li>
                ))}
              </ul>
            ) : (
              <p className="mt-1">{t("card.rippleReportNone")}</p>
            )}
          </section>
          {!modificationResult.verified && modificationResult.failure_details && (
            <div
              role="alert"
              aria-label={t("card.modificationFailureTitle")}
              className="rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900"
            >
              <h3 className="font-semibold">{t("card.modificationFailureTitle")}</h3>
              <p className="mt-1 whitespace-pre-wrap">
                {modificationResult.failure_details}
              </p>
            </div>
          )}
        </>
      )}

      {selectionEnabled && (
        <section aria-label={t("card.annotations")} className="space-y-2 border-t border-gray-100 pt-2">
          {annotations.length > 0 && (
            <ul aria-label={t("card.annotations")} className="flex flex-wrap gap-1.5">
              {annotations.flatMap((annotation, annotationIndex) => (
                annotation.segments.map((segment, segmentIndex) => (
                  <li
                    key={`${annotation.id}-${segmentIndex}`}
                    data-annotation-id={annotation.id}
                    data-field-path={segment.field_path}
                    data-start={segment.start}
                    data-end={segment.end}
                    data-quoted-text={segment.quoted_text}
                    className={segmentIndex === 0
                      ? "inline-flex min-w-64 flex-col items-stretch gap-2 rounded-lg bg-indigo-100 p-2 text-xs font-medium text-indigo-800"
                      : "inline-flex items-center gap-1 rounded-full bg-indigo-100 px-2 py-0.5 text-xs font-medium text-indigo-800"}
                  >
                    <div className="flex items-center gap-1">
                      <span>{segment.field_path}</span>
                      <span>{segment.start}–{segment.end}</span>
                      <span>「{segment.quoted_text}」</span>
                      {segmentIndex === 0 && (
                        <button
                          type="button"
                          onClick={() => handleDeleteAnnotation(annotation.id)}
                          aria-label={`${t("card.deleteAnnotation")} ${annotationIndex + 1}`}
                          className="ml-auto rounded px-1 text-indigo-700 hover:bg-indigo-200"
                        >
                          ×
                        </button>
                      )}
                    </div>
                    {segmentIndex === 0 && (
                      <div className="space-y-1">
                        <label
                          htmlFor={`modification-instruction-${annotation.id}`}
                          className="block text-xs font-semibold text-indigo-900"
                        >
                          {t("card.modificationInstruction")}
                        </label>
                        <textarea
                          id={`modification-instruction-${annotation.id}`}
                          aria-label={`${t("card.modificationInstruction")} ${annotationIndex + 1}`}
                          value={annotation.instruction}
                          onChange={(event) => handleInstructionChange(annotation.id, event.target.value)}
                          placeholder={t("card.modificationInstructionPlaceholder")}
                          rows={2}
                          className="w-full rounded border border-indigo-200 bg-white px-2 py-1 text-sm font-normal text-gray-800 outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                        />
                      </div>
                    )}
                  </li>
                ))
              ))}
            </ul>
          )}
          {selectionError && (
            <p role="alert" className="text-sm text-red-700">{selectionError}</p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={handleSubmit}
              disabled={!canSubmit || isRunInFlight}
              className="rounded bg-indigo-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isRunInFlight ? t("card.submittingModifications") : t("card.submitModifications")}
            </button>
            {displayedSubmitError && (() => {
              const isStaleBase = displayedSubmitError.code === "stale_base";
              const titleKey = displayedSubmitError.code
                ? MODIFICATION_ERROR_TITLE_KEYS[displayedSubmitError.code]
                : undefined;
              return (
                <div
                  role="alert"
                  data-error-code={displayedSubmitError.code}
                  data-severity={isStaleBase ? "warning" : "error"}
                  className={isStaleBase
                    ? "rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900"
                    : "rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800"}
                >
                  <p className="font-semibold">
                    {t(titleKey ?? "card.modificationErrorTitle")}
                  </p>
                  <p className="mt-1 whitespace-pre-wrap">{displayedSubmitError.message}</p>
                </div>
              );
            })()}
          </div>
        </section>
      )}

      <div className="flex flex-wrap gap-2 pt-1">
        <button
          type="button"
          onClick={handleDownloadJson}
          disabled={!isFinal}
          className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {t("card.download_json")}
        </button>
        {question.image_base64 && (
          <button
            type="button"
            onClick={handleDownloadPng}
            disabled={!isFinal}
            className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t("card.download_png")}
          </button>
        )}
        <button
          type="button"
          onClick={handleDownloadOdt}
          disabled={!isFinal}
          className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {t("card.download_odt")}
        </button>
      </div>
    </div>
  );
}

type ChipTone = "blue" | "purple" | "amber" | "gray" | "teal" | "orange" | "green";

const TONE_CLASSES: Record<ChipTone, string> = {
  blue: "bg-blue-100 text-blue-800",
  purple: "bg-purple-100 text-purple-800",
  amber: "bg-amber-100 text-amber-800",
  gray: "bg-gray-100 text-gray-800",
  teal: "bg-teal-100 text-teal-800",
  orange: "bg-orange-100 text-orange-800",
  green: "bg-green-100 text-green-800",
};

function Chip({ label, tone, title }: { label: string; tone: ChipTone; title?: string }) {
  return (
    <span
      title={title}
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${TONE_CLASSES[tone]}`}
    >
      {label}
    </span>
  );
}

function VerificationBadge({
  passed,
  verifiedLabel,
  unverifiedLabel,
}: {
  passed: boolean;
  verifiedLabel: string;
  unverifiedLabel: string;
}) {
  if (passed) {
    return (
      <span className="inline-flex shrink-0 items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800">
        {verifiedLabel}
      </span>
    );
  }
  return (
    <span className="inline-flex shrink-0 items-center rounded-full bg-yellow-100 px-2 py-0.5 text-xs font-medium text-yellow-800">
      {unverifiedLabel}
    </span>
  );
}

import { useMemo, useState } from "react";

import type { ExamQuestion, SubQuestion, RubricEntry } from "../hooks/useGenerate";
import { useT } from "../i18n/useT";
import { buildExamOdt, formatTimestamp } from "../utils/odt";

export interface QuestionCardProps {
  question: ExamQuestion;
}

interface VerificationShape {
  passed?: boolean;
}

function getQuestionId(question: ExamQuestion): string {
  return question.id && question.id.length > 0 ? question.id : "question";
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

function SubQuestionBlock({ sub }: { sub: SubQuestion }) {
  const t = useT();
  const [showAnswer, setShowAnswer] = useState(false);

  return (
    <div className="rounded border border-gray-100 bg-gray-50 p-3 space-y-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-xs font-semibold text-gray-500">
          {t("card.subquestion")}{sub.序號}題
        </span>
        <Chip label={`${sub.年級}年級`} tone="blue" />
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

      {sub.image_base64 && (
        <img
          src={`data:image/png;base64,${sub.image_base64}`}
          alt={`第${sub.序號}題素材圖片`}
          className="max-w-full rounded border border-gray-200 bg-white"
        />
      )}

      <div className="text-sm leading-relaxed whitespace-pre-wrap">{sub.題目}</div>

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
                <span className="whitespace-pre-wrap">{sub.答案}</span>
              </div>
            )}
            {sub.答案解析 && (
              <div>
                <span className="font-medium text-gray-700">{t("card.answerExplanation")}：</span>
                <span className="whitespace-pre-wrap">{sub.答案解析}</span>
              </div>
            )}
            {sub.評分規準 && sub.評分規準.length > 0 && (
              <div>
                <div className="font-medium text-gray-700 mb-1">{t("card.rubric")}</div>
                <div className="space-y-1">
                  {sub.評分規準.map((r: RubricEntry) => (
                    <div key={r.code} className="flex gap-2 items-start">
                      <span className={`inline-flex shrink-0 items-center rounded px-1.5 py-0.5 text-xs font-bold ${RUBRIC_TONE[r.code] ?? "bg-gray-100 text-gray-600"}`}>
                        {r.code}
                      </span>
                      <span className="text-xs leading-relaxed text-gray-700">{r.規準說明}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default function QuestionCard({ question }: QuestionCardProps) {
  const t = useT();
  const [showSolution, setShowSolution] = useState(false);

  const verification = question.verification as VerificationShape | undefined;
  const passed = Boolean(verification?.passed);
  const questionId = getQuestionId(question);
  const isSocialStudies = (question.subquestions?.length ?? 0) > 0;

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

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm space-y-3">
      {/* Header chips */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-wrap gap-1.5">
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
        </div>
        <VerificationBadge passed={passed} verifiedLabel={t("card.verified")} unverifiedLabel={t("card.unverified")} />
      </div>

      {question.image_base64 && (
        <img
          src={`data:image/png;base64,${question.image_base64}`}
          alt="Question diagram"
          className="max-w-full rounded border border-gray-200"
        />
      )}

      {/* Social studies: core question + passage + subquestions */}
      {isSocialStudies ? (
        <div className="space-y-3">
          {question.核心問題 && (
            <div className="rounded bg-blue-50 border border-blue-100 p-3">
              <div className="text-xs font-semibold text-blue-600 mb-1">{t("card.coreQuestion")}</div>
              <div className="text-sm leading-relaxed whitespace-pre-wrap">{question.核心問題}</div>
            </div>
          )}
          {question.文本 && (
            <div className="rounded bg-gray-50 border border-gray-200 p-3">
              <div className="text-xs font-semibold text-gray-500 mb-1">{t("card.passage")}</div>
              <div className="text-sm leading-relaxed whitespace-pre-wrap">{question.文本}</div>
            </div>
          )}
          <div className="space-y-2">
            {question.subquestions!.map((sub) => (
              <SubQuestionBlock key={sub.id} sub={sub} />
            ))}
          </div>
        </div>
      ) : (
        <>
          <div className="space-y-1 text-sm leading-relaxed">
            {question.題目.map((line, i) => (
              <p key={i} className="whitespace-pre-wrap">
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
                  <p key={i} className="whitespace-pre-wrap">
                    {line}
                  </p>
                ))}
              </div>
            )}
          </div>
        </>
      )}

      <div className="flex flex-wrap gap-2 pt-1">
        <button
          type="button"
          onClick={handleDownloadJson}
          className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          {t("card.download_json")}
        </button>
        {question.image_base64 && (
          <button
            type="button"
            onClick={handleDownloadPng}
            className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            {t("card.download_png")}
          </button>
        )}
        <button
          type="button"
          onClick={handleDownloadOdt}
          className="rounded border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
        >
          {t("card.download_odt")}
        </button>
      </div>
    </div>
  );
}

type ChipTone = "blue" | "purple" | "amber" | "gray" | "teal";

const TONE_CLASSES: Record<ChipTone, string> = {
  blue: "bg-blue-100 text-blue-800",
  purple: "bg-purple-100 text-purple-800",
  amber: "bg-amber-100 text-amber-800",
  gray: "bg-gray-100 text-gray-800",
  teal: "bg-teal-100 text-teal-800",
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

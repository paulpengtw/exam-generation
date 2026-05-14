import { useMemo, useState } from "react";

import type { ExamQuestion } from "../hooks/useGenerate";
import { useT } from "../i18n/useT";

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

export default function QuestionCard({ question }: QuestionCardProps) {
  const t = useT();
  const [showSolution, setShowSolution] = useState(false);

  const verification = question.verification as VerificationShape | undefined;
  const passed = Boolean(verification?.passed);
  const questionId = getQuestionId(question);

  const codes = useMemo(
    () => question.學習內容.map((item) => item.編碼).filter(Boolean),
    [question.學習內容],
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

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-wrap gap-1.5">
          {question.情境.map((c) => (
            <Chip key={`ctx-${c}`} label={c} tone="blue" />
          ))}
          <Chip label={question.題型種類} tone="purple" />
          <Chip label={question.題型} tone="purple" />
          {question.數學思考.map((m) => (
            <Chip key={`mt-${m}`} label={m} tone="amber" />
          ))}
          {codes.map((code) => (
            <Chip key={`code-${code}`} label={code} tone="gray" />
          ))}
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
      </div>
    </div>
  );
}

type ChipTone = "blue" | "purple" | "amber" | "gray";

const TONE_CLASSES: Record<ChipTone, string> = {
  blue: "bg-blue-100 text-blue-800",
  purple: "bg-purple-100 text-purple-800",
  amber: "bg-amber-100 text-amber-800",
  gray: "bg-gray-100 text-gray-800",
};

function Chip({ label, tone }: { label: string; tone: ChipTone }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${TONE_CLASSES[tone]}`}>
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

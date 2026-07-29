import { useEffect, useState } from "react";
import { useT } from "../i18n/useT";

function formatDuration(
  durationMs: number,
  minuteUnit: string,
  secondUnit: string,
) {
  const totalSeconds = Math.floor(durationMs / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;

  return `${minutes > 0 ? `${minutes}${minuteUnit}` : ""}${seconds}${secondUnit}`;
}

function ElapsedTime({ startedAt }: { startedAt: number }) {
  const [now, setNow] = useState(startedAt);
  const t = useT();

  useEffect(() => {
    const intervalId = setInterval(() => {
      setNow(Date.now());
    }, 1000);

    return () => clearInterval(intervalId);
  }, []);

  return (
    <span
      data-testid="statusbar-elapsed"
      className="shrink-0 whitespace-nowrap tabular-nums"
    >
      {formatDuration(
        now - startedAt,
        t("statusbar.unit_minute"),
        t("statusbar.unit_second"),
      )}
    </span>
  );
}

export type RunState = "idle" | "running" | "done" | "error";
export type JumpTarget = "form" | "progress" | "results";

const JUMP_BUTTONS: readonly {
  target: JumpTarget;
  labelKey: string;
}[] = [
  { target: "form", labelKey: "statusbar.jump_form" },
  { target: "progress", labelKey: "statusbar.jump_progress" },
  { target: "results", labelKey: "statusbar.jump_results" },
];

export interface GenerationStatusBarProps {
  runState: RunState;
  completedCount: number;
  requestedTotal: number;
  startedAt: number | null;
  finishedAt: number | null;
  availableTargets: readonly JumpTarget[];
  onJump: (target: JumpTarget) => void;
  onFeedback: (() => void) | null;
}

export default function GenerationStatusBar({
  runState,
  completedCount,
  requestedTotal,
  startedAt,
  finishedAt,
  availableTargets,
  onJump,
  onFeedback,
}: GenerationStatusBarProps) {
  const t = useT();

  return (
    <div
      aria-label={t("statusbar.aria")}
      className="fixed inset-x-0 bottom-0 z-40 border-t border-gray-300 bg-white shadow-[0_-4px_12px_rgba(0,0,0,0.08)]"
    >
      <div className="mx-auto flex h-12 max-w-5xl flex-nowrap items-center gap-2 whitespace-nowrap px-3 text-xs sm:px-4 sm:text-sm">
        <div
          className={`flex min-w-0 items-center gap-2 ${
            runState === "running"
              ? "text-blue-600"
              : runState === "done"
                ? "text-green-600"
                : runState === "error"
                  ? "text-red-600"
                  : "text-gray-500"
          }`}
        >
          <span data-testid="statusbar-status" className="truncate">
            {runState === "idle" ? t("statusbar.not_started") : null}
            {runState === "running" ? (
              <>
                ◐ {t("statusbar.running")} · {t("statusbar.completed_prefix")}{" "}
                {completedCount} / {requestedTotal}
              </>
            ) : null}
            {runState === "done" &&
            startedAt !== null &&
            finishedAt !== null ? (
              <>
                ✓ {t("statusbar.done")} {completedCount}{" "}
                {t("statusbar.unit_question")} ·{" "}
                {formatDuration(
                  finishedAt - startedAt,
                  t("statusbar.unit_minute"),
                  t("statusbar.unit_second"),
                )}
              </>
            ) : null}
            {runState === "error" ? <>✕ {t("statusbar.error")}</> : null}
          </span>
          {runState === "running" && startedAt !== null ? (
            <ElapsedTime startedAt={startedAt} />
          ) : null}
        </div>

        <div className="ml-auto flex shrink-0 items-center gap-1 sm:gap-2">
          {JUMP_BUTTONS.map(({ target, labelKey }) => (
            <button
              key={target}
              type="button"
              disabled={!availableTargets.includes(target)}
              onClick={() => onJump(target)}
              className="rounded border border-gray-300 bg-white px-1.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50 sm:px-2 sm:text-sm"
            >
              {t(labelKey)}
            </button>
          ))}
          {onFeedback !== null ? (
            <button
              type="button"
              onClick={onFeedback}
              className="rounded border border-blue-600 bg-white px-1.5 py-1 text-xs font-medium text-blue-600 hover:bg-blue-50 sm:px-2 sm:text-sm"
            >
              {t("statusbar.feedback")}
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

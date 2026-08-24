import { useId, useMemo, useState } from "react";
import type { DragEvent, JSX, KeyboardEvent } from "react";

import type { DragDropSpec, SliderSpec } from "../hooks/useGenerate";
import { useT } from "../i18n/useT";

export type InteractionSpec = DragDropSpec | SliderSpec;

export type InteractionResponse =
  | { placements: Record<string, string> }
  | { value: number };

export interface InteractionSubmission {
  item_id: string;
  題型: string;
  response: InteractionResponse;
  score: number;
  max_score: number;
}

type SliderSubmission = Omit<InteractionSubmission, "response"> & {
  response: { value: number };
};

type DragDropSubmission = Omit<InteractionSubmission, "response"> & {
  response: { placements: Record<string, string> };
};

export interface InteractiveItemViewerProps {
  itemId: string;
  題型: string;
  interaction: InteractionSpec;
  distractorAnalysis?: Record<string, string>;
  onSubmit?: (submission: InteractionSubmission) => void;
}

function isSliderSpec(interaction: InteractionSpec): interaction is SliderSpec {
  return "min" in interaction && "max" in interaction && "correct_value" in interaction;
}

function initialSliderValue(spec: SliderSpec): number {
  const midpoint = spec.min + (spec.max - spec.min) / 2;
  if (spec.step <= 0) return midpoint;
  const steps = Math.round((midpoint - spec.min) / spec.step);
  return Number((spec.min + steps * spec.step).toFixed(10));
}

function displayValue(value: number): string {
  return String(value);
}

function sliderTicks(spec: SliderSpec): number[] {
  if (!spec.show_ticks || spec.step <= 0 || spec.max <= spec.min) return [];
  const count = Math.min(10, Math.floor((spec.max - spec.min) / spec.step));
  if (count === 0) return [spec.min, spec.max];
  return Array.from({ length: count + 1 }, (_, index) => {
    const ratio = index / count;
    const value = spec.min + (spec.max - spec.min) * ratio;
    const steps = Math.round((value - spec.min) / spec.step);
    return Number((spec.min + steps * spec.step).toFixed(10));
  });
}

function directionalSliderRationale(
  value: number,
  spec: SliderSpec,
  analysis: Record<string, string>,
): string | undefined {
  const belowKeys = ["below_range", "below", "under_range", "under", "low"];
  const aboveKeys = ["above_range", "above", "over_range", "over", "high"];
  const hasFarOffZone = Boolean(analysis.far_off);
  // The approved prototype treats nearby wrong values as directional zones
  // (55–60 for its 0–100 / correct=63 example) and distant values as far_off.
  // Use one tenth of the available range as that nearby band for other specs.
  const nearZoneWidth = Math.max(spec.tolerance, (spec.max - spec.min) * 0.1);
  const isNearBelow = spec.correct_value - value <= nearZoneWidth;
  const isNearAbove = value - spec.correct_value <= nearZoneWidth;
  const keys = value < spec.correct_value - spec.tolerance && (!hasFarOffZone || isNearBelow)
    ? belowKeys
    : value > spec.correct_value + spec.tolerance && (!hasFarOffZone || isNearAbove)
      ? aboveKeys
      : [];
  for (const key of keys) {
    if (analysis[key]) return analysis[key];
  }
  return analysis.far_off;
}

function scoreDragDrop(
  spec: DragDropSpec,
  placements: Record<string, string>,
): { score: number; maxScore: number } {
  const mappingEntries = Object.entries(spec.correct_mapping);
  const maxScore = mappingEntries.length;
  const correctCount = mappingEntries.filter(
    ([draggableId, targetId]) => placements[draggableId] === targetId,
  ).length;
  if (!spec.exact_match) return { score: correctCount, maxScore };

  const placementIds = new Set(Object.keys(placements));
  const mappingIds = new Set(Object.keys(spec.correct_mapping));
  const sameIds = placementIds.size === mappingIds.size
    && [...mappingIds].every((id) => placementIds.has(id));
  return { score: sameIds && correctCount === maxScore ? maxScore : 0, maxScore };
}

function placementRationale(
  draggableId: string,
  targetId: string | undefined,
  analysis: Record<string, string>,
): string | undefined {
  if (!targetId) return undefined;
  return analysis[`${draggableId}→${targetId}`]
    ?? analysis[`${draggableId}->${targetId}`];
}

function SliderViewer({
  itemId,
  題型,
  spec,
  distractorAnalysis,
  onSubmit,
}: {
  itemId: string;
  題型: string;
  spec: SliderSpec;
  distractorAnalysis: Record<string, string>;
  onSubmit?: (submission: InteractionSubmission) => void;
}) {
  const t = useT();
  const [value, setValue] = useState(() => initialSliderValue(spec));
  const [submission, setSubmission] = useState<SliderSubmission | null>(null);
  const sliderListId = `interactive-slider-ticks-${useId().replaceAll(":", "")}`;
  const ticks = sliderTicks(spec);

  function handleSubmit(): void {
    const score = Math.abs(value - spec.correct_value) <= spec.tolerance ? 1 : 0;
    const nextSubmission: SliderSubmission = {
      item_id: itemId,
      題型,
      response: { value },
      score,
      max_score: 1,
    };
    setSubmission(nextSubmission);
    onSubmit?.(nextSubmission);
  }

  function handleReset(): void {
    setValue(initialSliderValue(spec));
    setSubmission(null);
  }

  const isCorrect = submission?.score === 1;
  const rationale = submission && !isCorrect
    ? directionalSliderRationale(value, spec, distractorAnalysis)
    : undefined;

  return (
    <div data-testid="interactive-item-viewer" className="rounded border border-blue-100 bg-white p-3 space-y-3">
      <div className="flex items-center gap-3">
        <span className="text-sm text-gray-600">{displayValue(spec.min)}{spec.unit}</span>
        <input
          type="range"
          min={spec.min}
          max={spec.max}
          step={spec.step}
          value={value}
          list={ticks.length > 0 ? sliderListId : undefined}
          aria-label={t("interactive.sliderLabel")}
          onChange={(event) => {
            setValue(Number(event.currentTarget.value));
            setSubmission(null);
          }}
          className="min-w-0 flex-1"
        />
        <span className="text-sm text-gray-600">{displayValue(spec.max)}{spec.unit}</span>
        <span data-testid="interactive-slider-value" className="min-w-16 text-center font-bold">
          {displayValue(value)}{spec.unit}
        </span>
      </div>
      {ticks.length > 0 && (
        <datalist id={sliderListId} data-testid="interactive-slider-ticks">
          {ticks.map((tick) => <option key={tick} value={tick} />)}
        </datalist>
      )}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleSubmit}
          className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white"
        >
          {t("interactive.submit")}
        </button>
        <button
          type="button"
          onClick={handleReset}
          className="rounded border border-gray-300 px-4 py-2 text-sm"
        >
          {t("interactive.reset")}
        </button>
        {submission && (
          <span data-testid="interactive-score" role="status" aria-live="polite" className="font-bold">
            {t("interactive.score")} {submission.score} / {submission.max_score}
          </span>
        )}
      </div>
      {submission && (
        <div className="space-y-1 text-sm" data-testid="interactive-feedback" aria-live="polite">
          <span
            data-testid="interactive-verdict"
            role="img"
            aria-label={isCorrect ? t("interactive.correct") : t("interactive.wrong")}
            className={isCorrect ? "text-green-700" : "text-red-700"}
          >
            {isCorrect ? "✓" : "✗"}
          </span>
          {!isCorrect && rationale && <div className="text-red-700">{rationale}</div>}
        </div>
      )}
      {submission && (
        <details className="text-xs">
          <summary>{t("interactive.submission")}</summary>
          <pre className="mt-1 overflow-x-auto rounded bg-gray-50 p-2">
            {JSON.stringify(submission, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}

function DragDropViewer({
  itemId,
  題型,
  spec,
  distractorAnalysis,
  onSubmit,
}: {
  itemId: string;
  題型: string;
  spec: DragDropSpec;
  distractorAnalysis: Record<string, string>;
  onSubmit?: (submission: InteractionSubmission) => void;
}) {
  const t = useT();
  const [placements, setPlacements] = useState<Record<string, string>>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [submission, setSubmission] = useState<DragDropSubmission | null>(null);
  // The mock asks for shuffling but does not provide a seed. Reversing the
  // source order is a stable deterministic shuffle, so it stays fixed while
  // a student interacts and remains predictable in tests.
  const orderedDraggables = useMemo(
    () => spec.shuffle_draggables ? [...spec.draggables].reverse() : [...spec.draggables],
    [spec.draggables, spec.shuffle_draggables],
  );

  function clearSubmission(): void {
    setSubmission(null);
  }

  function placeDraggable(draggableId: string, targetId: string): void {
    const target = spec.targets.find((candidate) => candidate.id === targetId);
    if (!target || !spec.draggables.some((draggable) => draggable.id === draggableId)) return;
    const currentTargetId = placements[draggableId];
    const occupied = Object.values(placements).filter(
      (placedTargetId) => placedTargetId === targetId,
    ).length;
    if (currentTargetId !== targetId && occupied >= (target.capacity ?? 1)) return;

    setPlacements((current) => ({ ...current, [draggableId]: targetId }));
    setSelectedId(null);
    clearSubmission();
  }

  function removeDraggable(draggableId: string): void {
    setPlacements((current) => {
      const next = { ...current };
      delete next[draggableId];
      return next;
    });
    setSelectedId(null);
    clearSubmission();
  }

  function handleDragStart(event: DragEvent<HTMLElement>, draggableId: string): void {
    event.dataTransfer.setData("text/plain", draggableId);
    // Keep the prototype's legacy text type available to older drag sources.
    event.dataTransfer.setData("text", draggableId);
  }

  function handleDrop(event: DragEvent<HTMLElement>, targetId: string): void {
    event.preventDefault();
    const draggableId = event.dataTransfer.getData("text/plain")
      || event.dataTransfer.getData("text");
    if (draggableId) placeDraggable(draggableId, targetId);
  }

  function handleTargetKeyDown(event: KeyboardEvent<HTMLDivElement>, targetId: string): void {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    if (selectedId) placeDraggable(selectedId, targetId);
  }

  function handleSubmit(): void {
    const { score, maxScore } = scoreDragDrop(spec, placements);
    const nextSubmission: DragDropSubmission = {
      item_id: itemId,
      題型,
      response: { placements: { ...placements } },
      score,
      max_score: maxScore,
    };
    setSubmission(nextSubmission);
    onSubmit?.(nextSubmission);
  }

  function handleReset(): void {
    setPlacements({});
    setSelectedId(null);
    setSubmission(null);
  }

  function verdictFor(draggableId: string): "correct" | "wrong" | undefined {
    if (!submission) return undefined;
    const placedTargetId = submission.response.placements[draggableId];
    return placedTargetId !== undefined && spec.correct_mapping[draggableId] === placedTargetId
      ? "correct"
      : "wrong";
  }

  function verdictElement(draggableId: string): JSX.Element | null {
    const verdict = verdictFor(draggableId);
    if (!verdict) return null;
    return (
      <span
        data-testid={`interactive-verdict-${draggableId}`}
        role="img"
        aria-label={verdict === "correct" ? t("interactive.correct") : t("interactive.wrong")}
        className={verdict === "correct" ? "text-green-700" : "text-red-700"}
      >
        {verdict === "correct" ? "✓" : "✗"}
      </span>
    );
  }

  return (
    <div data-testid="interactive-item-viewer" className="rounded border border-blue-100 bg-white p-3 space-y-3">
      <div className="text-sm font-medium text-gray-700">{t("interactive.draggables")}</div>
      <div className="flex min-h-10 flex-wrap gap-2" aria-label={t("interactive.draggables")}>
        {orderedDraggables
          .filter((draggable) => placements[draggable.id] === undefined)
          .map((draggable) => (
            <button
              key={draggable.id}
              type="button"
              data-testid={`interactive-chip-${draggable.id}`}
              draggable
              aria-pressed={selectedId === draggable.id}
              onClick={() => setSelectedId((current) => current === draggable.id ? null : draggable.id)}
              onDragStart={(event) => handleDragStart(event, draggable.id)}
              className={selectedId === draggable.id
                ? "rounded border-2 border-blue-700 bg-blue-600 px-3 py-2 text-sm text-white"
                : "rounded border border-blue-500 bg-blue-50 px-3 py-2 text-sm"}
            >
              <span>{draggable.label}</span> {verdictElement(draggable.id)}
            </button>
          ))}
      </div>
      <div className="grid gap-3 sm:grid-cols-2" aria-label={t("interactive.targets")}>
        {spec.targets.map((target) => {
          const targetPlacements = orderedDraggables.filter(
            (draggable) => placements[draggable.id] === target.id,
          );
          return (
            <div
              key={target.id}
              role="group"
              aria-label={target.label}
              tabIndex={0}
              onClick={() => { if (selectedId) placeDraggable(selectedId, target.id); }}
              onKeyDown={(event) => handleTargetKeyDown(event, target.id)}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => handleDrop(event, target.id)}
              className="min-h-20 rounded border-2 border-dashed border-gray-300 p-2"
            >
              <h4 className="mb-2 text-sm font-semibold text-gray-600">{target.label}</h4>
              {targetPlacements.length === 0 && (
                <span className="text-xs text-gray-400">{t("interactive.empty")}</span>
              )}
              {targetPlacements.map((draggable) => {
                const targetId = submission?.response.placements[draggable.id];
                const rationale = submission && verdictFor(draggable.id) === "wrong"
                  ? placementRationale(draggable.id, targetId, distractorAnalysis)
                  : undefined;
                return (
                  <div key={draggable.id} className="mt-1 rounded bg-gray-100 p-2 text-sm">
                    <span
                      draggable
                      onDragStart={(event) => handleDragStart(event, draggable.id)}
                    >
                      {draggable.label}
                    </span>{" "}{verdictElement(draggable.id)}
                    <button
                      type="button"
                      aria-label={`${t("interactive.remove")} ${draggable.label}`}
                      onClick={(event) => {
                        event.stopPropagation();
                        removeDraggable(draggable.id);
                      }}
                      className="float-right text-gray-500"
                    >
                      ✕
                    </button>
                    {rationale && <div className="mt-1 text-xs text-red-700">{rationale}</div>}
                  </div>
                );
              })}
            </div>
          );
        })}
      </div>
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleSubmit}
          className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white"
        >
          {t("interactive.submit")}
        </button>
        <button
          type="button"
          onClick={handleReset}
          className="rounded border border-gray-300 px-4 py-2 text-sm"
        >
          {t("interactive.reset")}
        </button>
        {submission && (
          <span data-testid="interactive-score" role="status" aria-live="polite" className="font-bold">
            {t("interactive.score")} {submission.score} / {submission.max_score}
          </span>
        )}
      </div>
      {submission && (
        <details className="text-xs">
          <summary>{t("interactive.submission")}</summary>
          <pre className="mt-1 overflow-x-auto rounded bg-gray-50 p-2">
            {JSON.stringify(submission, null, 2)}
          </pre>
        </details>
      )}
    </div>
  );
}

export default function InteractiveItemViewer({
  itemId,
  題型,
  interaction,
  distractorAnalysis = {},
  onSubmit,
}: InteractiveItemViewerProps) {
  if (isSliderSpec(interaction)) {
    return (
      <SliderViewer
        itemId={itemId}
        題型={題型}
        spec={interaction}
        distractorAnalysis={distractorAnalysis}
        onSubmit={onSubmit}
      />
    );
  }

  return (
    <DragDropViewer
      itemId={itemId}
      題型={題型}
      spec={interaction}
      distractorAnalysis={distractorAnalysis}
      onSubmit={onSubmit}
    />
  );
}

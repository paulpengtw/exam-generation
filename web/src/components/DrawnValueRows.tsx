import { useCallback, useEffect, useState, type ReactNode } from "react";

import { ActionButton, ActionFailure, useActionFeedback } from "../motion/actionFeedback";
import { useT } from "../i18n/useT";
import { durations } from "../motion/tokens";

export type DrawnValueLabelMap = Readonly<Record<string, string>>;

export interface RedrawResult {
  ok?: boolean;
  sameValue?: boolean;
  value?: unknown;
}

export type RedrawAction = () => RedrawResult | void | Promise<RedrawResult | void>;

export function RedrawActionButton({
  onRedraw,
  label,
  disabled = false,
  genericError,
  onPendingChange,
  onSuccess,
}: {
  onRedraw: RedrawAction;
  label: ReactNode;
  disabled?: boolean;
  genericError?: string;
  onPendingChange?: (pending: boolean) => void;
  onSuccess?: (result: RedrawResult | void) => void;
}) {
  const t = useT();
  const [sameValue, setSameValue] = useState(false);
  const action = useActionFeedback<RedrawResult | void>({
    action: async () => {
      const result = await onRedraw();
      if (result?.ok === false) {
        throw new ActionFailure(genericError ?? t("form.confirm_resolve_error"));
      }
      return result;
    },
    genericError: genericError ?? t("form.confirm_resolve_error"),
    onSuccess: (result) => {
      setSameValue(result?.sameValue === true);
      onSuccess?.(result);
    },
  });

  useEffect(() => {
    onPendingChange?.(action.state === "pending");
  }, [action.state, onPendingChange]);

  return (
    <>
      <ActionButton
        feedback={action}
        label={label}
        pendingLabel={t("form.confirm_redraw_pending")}
        doneLabel={label}
        disabled={disabled}
        data-testid="redraw-control"
        onPress={() => {
          setSameValue(false);
          onPendingChange?.(true);
        }}
      />
      {sameValue && (
        <span data-testid="redraw-same-value-hint" className="text-xs text-amber-700">
          {t("form.confirm_redraw_same")}
        </span>
      )}
    </>
  );
}

export interface DrawnValueRowsProps {
  /** Canonical resolver paths, including any paths outside this component's scope. */
  drawnPaths: readonly string[];
  /** Labels are keyed by a resolver field name; full paths are also accepted. */
  fieldLabels: DrawnValueLabelMap;
  /** Reads the completed value for one canonical resolver path. */
  valueForPath: (path: string) => unknown;
  /** Optional field control rendered in the value slot while the row stays generic. */
  renderValue?: (path: string, value: unknown) => ReactNode;
  /** Editor rendered after the user activates edit-in-place for a drawn row. */
  renderEditor?: (path: string, value: unknown) => ReactNode;
  /** Whether a drawn row has an edit control. Defaults to true when renderEditor exists. */
  canEdit?: (path: string, value: unknown) => boolean;
  /** Called by a drawn row's 重抽 control. */
  onRedraw?: (path: string) => RedrawResult | void | Promise<RedrawResult | void>;
  /** Whether a drawn row has a 重抽 control. Defaults to true when onRedraw exists. */
  canRedraw?: (path: string) => boolean;
  editLabel?: ReactNode;
  redrawLabel?: ReactNode;
  clearedPaths?: readonly string[];
  clearedNotice?: ReactNode;
  /** Only drawn paths with this prefix are rendered. */
  pathPrefix?: string;
  /** Fields rendered even when they were pinned rather than drawn. */
  alwaysPaths?: readonly string[];
  emptyValue?: ReactNode;
  drawnBadge?: ReactNode;
  pinnedBadge?: ReactNode;
  compact?: boolean | ((path: string) => boolean);
  /** Disables all redraw controls while the resolver is processing a request. */
  redrawDisabled?: boolean;
  /** Canonical path currently being re-resolved; its value row is dimmed. */
  resolvingPath?: string | null;
}

function fieldName(path: string): string {
  const lastSegment = path.match(/(?:^|\.)([^.[\]]+)$/)?.[1];
  return lastSegment ?? path;
}

function labelForPath(path: string, fieldLabels: DrawnValueLabelMap): string | undefined {
  return fieldLabels[path] ?? fieldLabels[fieldName(path)];
}

function displayValue(value: unknown, emptyValue: ReactNode): ReactNode {
  if (value === undefined || value === null || value === "") return emptyValue;
  if (Array.isArray(value)) return value.map(String).join("、");
  return String(value);
}

export default function DrawnValueRows({
  drawnPaths,
  fieldLabels,
  valueForPath,
  renderValue,
  renderEditor,
  canEdit,
  onRedraw,
  canRedraw,
  editLabel = "編輯",
  redrawLabel = "重抽",
  clearedPaths = [],
  clearedNotice,
  pathPrefix,
  alwaysPaths = [],
  emptyValue = "",
  drawnBadge,
  pinnedBadge,
  compact = false,
  redrawDisabled = false,
  resolvingPath = null,
}: DrawnValueRowsProps) {
  const [editingPath, setEditingPath] = useState<string | null>(null);
  const [pendingPaths, setPendingPaths] = useState<Set<string>>(() => new Set());
  const [flashCounts, setFlashCounts] = useState<Map<string, number>>(() => new Map());
  const [flashActivePaths, setFlashActivePaths] = useState<Set<string>>(() => new Set());
  const markRedrawSuccess = useCallback((path: string) => {
    setFlashCounts((current) => {
      const next = new Map(current);
      next.set(path, (next.get(path) ?? 0) + 1);
      return next;
    });
    setFlashActivePaths((current) => {
      const next = new Set(current);
      next.add(path);
      return next;
    });
    window.setTimeout(() => {
      setFlashActivePaths((current) => {
        const next = new Set(current);
        next.delete(path);
        return next;
      });
    }, durations.standard);
  }, []);
  const paths = [...new Set([
    ...alwaysPaths,
    ...drawnPaths.filter((path) => pathPrefix === undefined || path.startsWith(pathPrefix)),
  ])];
  const rows = paths.flatMap((path) => {
    const label = labelForPath(path, fieldLabels);
    if (!label) return [];
    return [{ path, label, drawn: drawnPaths.includes(path), value: valueForPath(path) }];
  });

  return (
    <>
      {rows.map(({ path, label, drawn, value }) => {
        const renderedValue = displayValue(value, emptyValue);
        const editable = drawn && renderEditor !== undefined && (canEdit?.(path, value) ?? true);
        const redrawable = drawn && onRedraw !== undefined && (canRedraw?.(path) ?? true);
        const isEditing = editingPath === path && editable;
        const valueContent = isEditing
          ? renderEditor(path, value)
          : renderValue
          ? renderValue(path, value)
          : <span>{renderedValue}</span>;
        const badge = drawn ? drawnBadge : pinnedBadge;
        const isCompact = typeof compact === "function" ? compact(path) : compact;
        const isRedrawPending = pendingPaths.has(path) || resolvingPath === path;
        const flashCount = flashCounts.get(path) ?? 0;
        const controls = (editable || redrawable) && (
          <span className="ml-3 inline-flex flex-wrap gap-1">
            {editable && !isEditing && (
              <button
                type="button"
                onClick={() => setEditingPath(path)}
                className="rounded border border-gray-300 bg-white px-2 py-0.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
              >
                {editLabel}
              </button>
            )}
            {redrawable && (
              <RedrawActionButton
                onRedraw={() => {
                  setEditingPath(null);
                  return onRedraw(path);
                }}
                label={redrawLabel}
                disabled={redrawDisabled}
                onSuccess={() => markRedrawSuccess(path)}
                onPendingChange={(pending) => {
                  setPendingPaths((current) => {
                    const next = new Set(current);
                    if (pending) next.add(path);
                    else next.delete(path);
                    return next.size === current.size && [...next].every((item) => current.has(item))
                      ? current
                      : next;
                  });
                }}
              />
            )}
          </span>
        );
        const notice = clearedPaths.includes(path) && clearedNotice !== undefined && (
          <span className="ml-2 text-xs font-medium text-amber-700">{clearedNotice}</span>
        );
        if (isCompact) {
          return (
            <div
              key={path}
              className={`text-sm text-gray-700 transition-opacity duration-quick ease-signature ${isRedrawPending ? "opacity-50" : ""} ${flashActivePaths.has(path) ? "redraw-flash" : ""}`}
              data-drawn-value-path={path}
              data-redraw-flash={flashCount > 0 ? String(flashCount) : undefined}
            >
              {renderValue ? <span>{label}: </span> : <span>{label}: {renderedValue}</span>}
              {(renderValue || isEditing) && valueContent}
              {badge !== undefined && (
                <span className={`ml-2 text-xs font-medium ${drawn ? "text-amber-700" : "text-green-700"}`}>
                  {badge}
                </span>
              )}
              {notice}
              {controls}
            </div>
          );
        }
        return (
          <div
            key={path}
            className={`flex gap-3 text-sm transition-opacity duration-quick ease-signature ${isRedrawPending ? "opacity-50" : ""} ${flashActivePaths.has(path) ? "redraw-flash" : ""}`}
            data-drawn-value-path={path}
            data-redraw-flash={flashCount > 0 ? String(flashCount) : undefined}
          >
            <dt className="w-40 shrink-0 font-medium text-gray-600">{label}</dt>
            <dd className="min-w-0 break-words text-gray-900">
              {valueContent}
              {badge !== undefined && (
                <span className={`ml-2 text-xs font-medium ${drawn ? "text-amber-700" : "text-green-700"}`}>
                  {badge}
                </span>
              )}
              {notice}
              {controls}
            </dd>
          </div>
        );
      })}
    </>
  );
}

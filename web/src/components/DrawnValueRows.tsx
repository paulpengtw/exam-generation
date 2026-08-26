import type { ReactNode } from "react";

export type DrawnValueLabelMap = Readonly<Record<string, string>>;

export interface DrawnValueRowsProps {
  /** Canonical resolver paths, including any paths outside this component's scope. */
  drawnPaths: readonly string[];
  /** Labels are keyed by a resolver field name; full paths are also accepted. */
  fieldLabels: DrawnValueLabelMap;
  /** Reads the completed value for one canonical resolver path. */
  valueForPath: (path: string) => unknown;
  /** Optional field control rendered in the value slot while the row stays generic. */
  renderValue?: (path: string, value: unknown) => ReactNode;
  /** Only drawn paths with this prefix are rendered. */
  pathPrefix?: string;
  /** Fields rendered even when they were pinned rather than drawn. */
  alwaysPaths?: readonly string[];
  emptyValue?: ReactNode;
  drawnBadge?: ReactNode;
  pinnedBadge?: ReactNode;
  compact?: boolean | ((path: string) => boolean);
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
  pathPrefix,
  alwaysPaths = [],
  emptyValue = "",
  drawnBadge,
  pinnedBadge,
  compact = false,
}: DrawnValueRowsProps) {
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
        const valueContent = renderValue
          ? renderValue(path, value)
          : <span>{renderedValue}</span>;
        const badge = drawn ? drawnBadge : pinnedBadge;
        const isCompact = typeof compact === "function" ? compact(path) : compact;
        if (isCompact) {
          return (
            <div key={path} className="text-sm text-gray-700" data-drawn-value-path={path}>
              {renderValue ? <span>{label}: </span> : <span>{label}: {renderedValue}</span>}
              {renderValue && valueContent}
              {badge !== undefined && (
                <span className={`ml-2 text-xs font-medium ${drawn ? "text-amber-700" : "text-green-700"}`}>
                  {badge}
                </span>
              )}
            </div>
          );
        }
        return (
          <div key={path} className="flex gap-3 text-sm" data-drawn-value-path={path}>
            <dt className="w-40 shrink-0 font-medium text-gray-600">{label}</dt>
            <dd className="min-w-0 break-words text-gray-900">
              {valueContent}
              {badge !== undefined && (
                <span className={`ml-2 text-xs font-medium ${drawn ? "text-amber-700" : "text-green-700"}`}>
                  {badge}
                </span>
              )}
            </dd>
          </div>
        );
      })}
    </>
  );
}

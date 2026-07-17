/**
 * Prototype frontend TS/SVG renderer for illustrative chart_spec entries.
 *
 * Consumes today's chart_spec shape (render_mode + description + data) and
 * covers three illustrative shapes: tables, simple SVG geometry, scenario
 * cards. Anything else (including render_mode="chart") is unsupported and the
 * component returns null so the caller falls back to the server PNG path.
 *
 * Gated behind VITE_ENABLE_FRONTEND_TS_RENDERER — the routing policy in
 * docs/figure-rendering-policy.md documents when this path is active.
 */

const SCENARIO_KEYWORDS = ["情境卡", "菜單", "廣告", "海報", "票券", "看板", "簡介"];

export interface ChartSpecInput {
  render_mode?: string;
  chart_type?: string | null;
  description?: string;
  data?: Record<string, unknown> | null;
}

export type FigureCategory = "table" | "geometry" | "scenario_card" | "unsupported";

export function isFrontendTsEnabled(): boolean {
  return Boolean(import.meta.env.VITE_ENABLE_FRONTEND_TS_RENDERER);
}

export function classifySpec(spec: ChartSpecInput): FigureCategory {
  const mode = (spec.render_mode ?? "").toLowerCase();
  if (mode === "chart") return "unsupported";

  const data = (spec.data ?? {}) as Record<string, unknown>;
  if (
    Array.isArray(data.rows) &&
    Array.isArray((data as { columns?: unknown }).columns)
  ) {
    return "table";
  }
  if (Array.isArray(data.shapes)) {
    return "geometry";
  }

  const description = spec.description ?? "";
  if (SCENARIO_KEYWORDS.some((k) => description.includes(k))) {
    return "scenario_card";
  }

  return "unsupported";
}

interface Props {
  spec: ChartSpecInput;
  alt?: string;
}

interface TableData {
  columns: string[];
  rows: string[][];
}

interface Shape {
  type: string;
  points?: [number, number][];
  from?: [number, number];
  to?: [number, number];
  cx?: number;
  cy?: number;
  r?: number;
  label?: string;
}

interface ScenarioData {
  title?: string;
  items?: string[];
}

function TableFigure({ data }: { data: TableData }) {
  return (
    <table className="border-collapse text-sm">
      <thead>
        <tr>
          {data.columns.map((col, i) => (
            <th
              key={`col-${i}`}
              className="border border-gray-300 bg-gray-50 px-3 py-1 text-left font-semibold"
            >
              {col}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {data.rows.map((row, r) => (
          <tr key={`row-${r}`}>
            {row.map((cell, c) => (
              <td key={`cell-${r}-${c}`} className="border border-gray-300 px-3 py-1">
                {cell}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function GeometryFigure({ shapes, alt }: { shapes: Shape[]; alt?: string }) {
  return (
    <svg
      viewBox="0 0 100 100"
      xmlns="http://www.w3.org/2000/svg"
      className="max-w-full"
      aria-label={alt ?? "geometry figure"}
      role="img"
    >
      {shapes.map((shape, i) => {
        if (shape.type === "polygon" && shape.points) {
          return (
            <polygon
              key={`s-${i}`}
              points={shape.points.map(([x, y]) => `${x},${y}`).join(" ")}
              fill="none"
              stroke="#111"
              strokeWidth={1}
            />
          );
        }
        if (shape.type === "line" && shape.from && shape.to) {
          return (
            <line
              key={`s-${i}`}
              x1={shape.from[0]}
              y1={shape.from[1]}
              x2={shape.to[0]}
              y2={shape.to[1]}
              stroke="#111"
              strokeWidth={1}
            />
          );
        }
        if (shape.type === "circle" && shape.cx !== undefined) {
          return (
            <circle
              key={`s-${i}`}
              cx={shape.cx}
              cy={shape.cy ?? 0}
              r={shape.r ?? 1}
              fill="none"
              stroke="#111"
              strokeWidth={1}
            />
          );
        }
        return null;
      })}
    </svg>
  );
}

function ScenarioCard({ data, description }: { data: ScenarioData; description: string }) {
  return (
    <div className="rounded border border-amber-300 bg-amber-50 p-3">
      <div className="text-sm font-semibold text-amber-900">
        {data.title ?? description}
      </div>
      {data.items && data.items.length > 0 && (
        <ul className="mt-1 list-disc pl-5 text-sm text-amber-900">
          {data.items.map((item, i) => (
            <li key={`item-${i}`}>{item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function FigureRenderer({ spec, alt }: Props): JSX.Element | null {
  const category = classifySpec(spec);
  const data = (spec.data ?? {}) as Record<string, unknown>;

  if (category === "table") {
    return <TableFigure data={data as unknown as TableData} />;
  }
  if (category === "geometry") {
    return <GeometryFigure shapes={data.shapes as Shape[]} alt={alt} />;
  }
  if (category === "scenario_card") {
    return (
      <ScenarioCard
        data={data as unknown as ScenarioData}
        description={spec.description ?? ""}
      />
    );
  }

  console.warn("[figure-renderer-fallback] unsupported spec, using PNG", spec);
  return null;
}

# Figure Rendering — TS Renderer Evaluation + Routing Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prototype a frontend TS/SVG renderer for illustrative `chart_spec`s, evaluate it against the LLM-HTML + Playwright path, and codify the "quantitative → matplotlib, illustrative → HTML/Playwright (or frontend TS if Phase A is a go)" routing rule in a policy doc plus enforcement tests (joint GitHub issues #108 + #110).

**Architecture:** Phase A adds one `web/src/components/FigureRenderer.tsx` component gated behind a `VITE_ENABLE_FRONTEND_TS_RENDERER` build-time flag; it consumes today's `chart_spec` shape (`description` + `data`) for a small set of illustrative shapes (tables, simple SVG geometry, scenario cards) and falls back to the existing `<img src="data:image/png;base64,…">` path for anything it cannot express. Phase B lands a new `docs/figure-rendering-policy.md`, docstrings on the three `context_builder.py` files pointing at it, and pytest classification/dispatch tests that enforce the mapping between 題目內容類型 and `render_mode`. The Pydantic `ImageSpec.render_mode` enum only gains `"frontend_ts"` if Phase A is decided a go/hybrid — that step is gated in Task 10.

**Tech Stack:** React 19 + Vite + TypeScript for the web prototype; vitest + @testing-library/react for snapshot tests; pytest + Pydantic for backend classification/dispatch tests; markdown for the policy doc.

**Spec:** `docs/superpowers/specs/2026-07-15-figure-rendering-eval-and-routing-design.md`

## Global Constraints

- Joint plan for GitHub issues #108 (TS renderer evaluation) and #110 (routing policy). Both must ship together; Phase B does not wait on Phase A completing separately.
- Phase A's prototype is deliberately small — 2–3 illustrative shapes only (tables, simple geometry, scenario cards). No charting library. No changes to backend rendering.
- The TS renderer is **display-only**. Verifier and ODT export continue to consume server-side PNGs (`image_base64`); client-side rendering never replaces those PNGs in v1.
- When the TS component cannot express a given `chart_spec`, it must return `null` so `QuestionCard` transparently falls back to the current `<img>` PNG path. Every fallback is recorded (console-log line prefixed with `[figure-renderer-fallback]`) so coverage can be tracked.
- The `VITE_ENABLE_FRONTEND_TS_RENDERER` build flag defaults to **off**. With the flag unset or `""`, `QuestionCard` behaves exactly as today (PNG-only).
- Routing policy (Phase B) is the source of truth: precise/quantitative statistical charts → `render_mode:"chart"` (matplotlib); illustrative figures → `render_mode:"html"` today, `"frontend_ts"` only if the Phase A decision is go/hybrid.
- `render_mode:"html"` MUST remain accepted forever as a legacy alias for already-generated questions — never remove it from the `Literal[...]` union.
- All three subjects share the same policy doc and the same routing rule. Every `context_builder.py` gets the same docstring anchor.
- Web commands run from `/workspace/exam-generation/web/`. Backend commands run from `/workspace/exam-generation/` and use `uv run pytest`.
- Chinese identifiers stay in Chinese (`chart_spec`, `題目內容類型`, `文本素材類型`, `子題` etc.); do not translate.

## Pre-existing defect this plan fixes first

Commit `d534147` ("fix: remove unused fireEvent import that broke tsc build") removed `vitest`, `@vitest/ui`, `jsdom`, and all `@testing-library/*` devDependencies plus the `test`/`test:watch` scripts from `web/package.json` — while `web/vitest.config.ts`, `web/src/test/setup.ts`, and `web/src/components/{QuestionCard,CoreQuestionPicker}.test.tsx` remain in the tree. Task 1 restores the test tooling so this plan's vitest snapshot tests (and the two already-checked-in test files) can run. Test files stay excluded from `tsc -b` via `tsconfig.app.json`, so restoring them does not affect the production build.

---

### Task 1: Restore web test tooling

**Files:**
- Modify: `web/package.json` (scripts + devDependencies)
- Modify: `web/package-lock.json` (via npm)

**Interfaces:**
- Consumes: nothing.
- Produces: a working `npm test` (vitest run) command used by Tasks 4 and every later web test.

- [ ] **Step 1: Reinstall the test devDependencies**

```bash
cd /workspace/exam-generation/web
npm install -D vitest @vitest/ui jsdom @testing-library/jest-dom @testing-library/react @testing-library/user-event
```

- [ ] **Step 2: Restore the test scripts in `web/package.json`**

In the `"scripts"` block, after `"preview": "vite preview"`, add:

```json
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest"
```

- [ ] **Step 3: Run the existing test suite to verify it passes**

```bash
cd /workspace/exam-generation/web
npm test
```

Expected: PASS — `src/components/QuestionCard.test.tsx` and `src/components/CoreQuestionPicker.test.tsx` both green.

- [ ] **Step 4: Verify the production build still works**

```bash
cd /workspace/exam-generation/web
npm run build
```

Expected: `tsc -b && vite build` succeeds with no errors.

- [ ] **Step 5: Commit**

```bash
cd /workspace/exam-generation/web
git add package.json package-lock.json
git commit -m "fix(web): restore vitest + testing-library tooling removed by d534147"
```

---

### Task 2: Historical `chart_spec` coverage script

**Files:**
- Create: `scripts/analyze_chart_spec_coverage.py`
- Create: `tests/test_analyze_chart_spec_coverage.py`

**Interfaces:**
- Consumes: any directory of generated question JSON files (default `output/`).
- Produces: `classify_spec(spec: dict) -> str` returning one of `"chart"`, `"table"`, `"geometry"`, `"scenario_card"`, `"other"`; `main()` prints a Markdown summary table used by Task 6 to record measured coverage.

- [ ] **Step 1: Write the failing test**

Create `tests/test_analyze_chart_spec_coverage.py`:

```python
"""Tests for the chart_spec coverage classifier."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_chart_spec_coverage import classify_spec, iter_specs, summarize


def test_classify_chart_by_render_mode_and_chart_type() -> None:
    spec = {"render_mode": "chart", "chart_type": "histogram", "data": {}}
    assert classify_spec(spec) == "chart"


def test_classify_table_by_html_data_rows_columns() -> None:
    spec = {
        "render_mode": "html",
        "description": "課程表",
        "data": {"columns": ["時段", "課程"], "rows": [["9:00", "數學"]]},
    }
    assert classify_spec(spec) == "table"


def test_classify_geometry_by_data_shapes() -> None:
    spec = {
        "render_mode": "html",
        "description": "三角形示意圖",
        "data": {"shapes": [{"type": "triangle", "vertices": [[0, 0], [3, 0], [0, 4]]}]},
    }
    assert classify_spec(spec) == "geometry"


def test_classify_scenario_card_by_description_keyword() -> None:
    spec = {
        "render_mode": "html",
        "description": "情境卡：博物館入場資訊",
        "data": {"title": "入場資訊", "items": ["票價", "時段"]},
    }
    assert classify_spec(spec) == "scenario_card"


def test_classify_other_when_shape_unknown() -> None:
    spec = {"render_mode": "html", "description": "自訂 SVG", "data": {"svg": "<svg/>"}}
    assert classify_spec(spec) == "other"


def test_iter_specs_reads_top_level_and_subquestion_chart_specs(tmp_path: Path) -> None:
    payload = {
        "chart_spec": {"render_mode": "chart", "chart_type": "boxplot", "data": {}},
        "subquestions": [
            {"chart_spec": {"render_mode": "html", "description": "表格", "data": {"rows": []}}},
            {"chart_spec": None},
        ],
    }
    (tmp_path / "q.json").write_text(json.dumps(payload), encoding="utf-8")
    specs = list(iter_specs(tmp_path))
    assert len(specs) == 2
    assert {classify_spec(s) for s in specs} == {"chart", "table"}


def test_summarize_returns_markdown_with_counts_and_percentages() -> None:
    specs = [
        {"render_mode": "chart", "chart_type": "histogram", "data": {}},
        {"render_mode": "html", "description": "表格", "data": {"rows": []}},
        {"render_mode": "html", "description": "菜單", "data": {}},
    ]
    md = summarize(specs)
    assert "| category |" in md
    assert "| chart | 1 | 33.3% |" in md
    assert "| table | 1 | 33.3% |" in md
    assert "| other | 1 | 33.3% |" in md
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /workspace/exam-generation
uv run pytest tests/test_analyze_chart_spec_coverage.py -x
```

Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.analyze_chart_spec_coverage'`.

- [ ] **Step 3: Write the implementation**

Create `scripts/analyze_chart_spec_coverage.py`:

```python
"""Classify historical chart_spec entries by shape.

Scans a directory of generated question JSON files (both math flat structure and
社會領域/自然科學 題組 with subquestions[*].chart_spec) and emits a Markdown
summary of how many specs fall into each category. Used by Task 6 of the
figure-rendering plan to record measured coverage of the frontend TS prototype.

Run:
    uv run python scripts/analyze_chart_spec_coverage.py output/
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

SCENARIO_KEYWORDS = ("情境卡", "菜單", "廣告", "海報", "票券", "看板", "簡介")


def classify_spec(spec: dict) -> str:
    """Return the coverage category for a single chart_spec dict."""
    render_mode = (spec.get("render_mode") or "").lower()
    if render_mode == "chart":
        return "chart"

    data = spec.get("data") or {}
    if isinstance(data, dict):
        if "rows" in data and "columns" in data:
            return "table"
        if "shapes" in data:
            return "geometry"

    description = spec.get("description") or ""
    if any(k in description for k in SCENARIO_KEYWORDS):
        return "scenario_card"

    return "other"


def iter_specs(root: Path) -> Iterable[dict]:
    """Yield every non-null chart_spec found under root (top-level + subquestions)."""
    for path in sorted(root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        payloads = payload if isinstance(payload, list) else [payload]
        for item in payloads:
            if not isinstance(item, dict):
                continue
            top = item.get("chart_spec")
            if isinstance(top, dict):
                yield top
            for sq in item.get("subquestions") or []:
                if not isinstance(sq, dict):
                    continue
                sub = sq.get("chart_spec")
                if isinstance(sub, dict):
                    yield sub


def summarize(specs: list[dict]) -> str:
    """Render a Markdown table (category | count | percentage) for the given specs."""
    counts = Counter(classify_spec(s) for s in specs)
    total = sum(counts.values()) or 1
    order = ["chart", "table", "geometry", "scenario_card", "other"]
    lines = ["| category | count | percentage |", "| --- | --- | --- |"]
    for cat in order:
        if cat not in counts:
            continue
        n = counts[cat]
        pct = 100.0 * n / total
        lines.append(f"| {cat} | {n} | {pct:.1f}% |")
    lines.append(f"\nTotal chart_spec entries analyzed: **{sum(counts.values())}**")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify chart_spec entries by shape.")
    parser.add_argument("root", type=Path, help="Directory containing generated question JSON files.")
    args = parser.parse_args(argv)

    if not args.root.is_dir():
        print(f"error: {args.root} is not a directory", file=sys.stderr)
        return 2

    specs = list(iter_specs(args.root))
    print(summarize(specs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /workspace/exam-generation
uv run pytest tests/test_analyze_chart_spec_coverage.py -x
```

Expected: PASS — 6 tests green.

- [ ] **Step 5: Commit**

```bash
cd /workspace/exam-generation
git add scripts/analyze_chart_spec_coverage.py tests/test_analyze_chart_spec_coverage.py
git commit -m "feat(scripts): add chart_spec shape coverage classifier (#108)"
```

---

### Task 3: `FigureRenderer.tsx` prototype

**Files:**
- Create: `web/src/components/FigureRenderer.tsx`
- Create: `web/src/components/FigureRenderer.test.tsx`

**Interfaces:**
- Consumes: `ChartSpecInput` (loose shape mirroring the backend `ImageSpec` — `render_mode`, `chart_type`, `description`, `data`), plus the build-time flag `import.meta.env.VITE_ENABLE_FRONTEND_TS_RENDERER`.
- Produces:
  - `default export FigureRenderer(props: { spec: ChartSpecInput; alt?: string }): JSX.Element | null` — returns `null` for shapes the component cannot express (caller then falls back to the PNG `<img>`).
  - `export function isFrontendTsEnabled(): boolean` — Task 4 gates the `<FigureRenderer>` swap on this.
  - `export function classifySpec(spec: ChartSpecInput): "table" | "geometry" | "scenario_card" | "unsupported"` — same taxonomy as Task 2's Python classifier, minus `"chart"` (quantitative charts always stay on the server PNG path).

- [ ] **Step 1: Write the failing tests**

Create `web/src/components/FigureRenderer.test.tsx`:

```tsx
import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";

afterEach(() => {
  vi.unstubAllEnvs();
});

import FigureRenderer, {
  classifySpec,
  isFrontendTsEnabled,
} from "./FigureRenderer";

describe("classifySpec", () => {
  it("marks tables by data.rows + data.columns", () => {
    expect(
      classifySpec({
        render_mode: "html",
        data: { columns: ["a", "b"], rows: [["1", "2"]] },
      }),
    ).toBe("table");
  });

  it("marks geometry by data.shapes", () => {
    expect(
      classifySpec({
        render_mode: "html",
        data: { shapes: [{ type: "line", from: [0, 0], to: [10, 0] }] },
      }),
    ).toBe("geometry");
  });

  it("marks scenario cards by description keyword", () => {
    expect(
      classifySpec({
        render_mode: "html",
        description: "情境卡：入場資訊",
        data: {},
      }),
    ).toBe("scenario_card");
  });

  it("returns unsupported for quantitative chart specs", () => {
    expect(classifySpec({ render_mode: "chart", chart_type: "histogram", data: {} })).toBe(
      "unsupported",
    );
  });

  it("returns unsupported when data shape is unknown", () => {
    expect(classifySpec({ render_mode: "html", description: "任意 SVG", data: {} })).toBe(
      "unsupported",
    );
  });
});

describe("isFrontendTsEnabled", () => {
  it("is false when VITE_ENABLE_FRONTEND_TS_RENDERER is unset", () => {
    vi.stubEnv("VITE_ENABLE_FRONTEND_TS_RENDERER", "");
    expect(isFrontendTsEnabled()).toBe(false);
  });

  it("is true when VITE_ENABLE_FRONTEND_TS_RENDERER is non-empty", () => {
    vi.stubEnv("VITE_ENABLE_FRONTEND_TS_RENDERER", "1");
    expect(isFrontendTsEnabled()).toBe(true);
  });
});

describe("FigureRenderer", () => {
  it("renders an HTML table for table specs", () => {
    render(
      <FigureRenderer
        spec={{
          render_mode: "html",
          description: "課表",
          data: { columns: ["時段", "課程"], rows: [["9:00", "數學"], ["10:00", "國文"]] },
        }}
      />,
    );
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("時段")).toBeInTheDocument();
    expect(screen.getByText("數學")).toBeInTheDocument();
  });

  it("renders an SVG for geometry specs", () => {
    const { container } = render(
      <FigureRenderer
        spec={{
          render_mode: "html",
          description: "三角形",
          data: {
            shapes: [{ type: "polygon", points: [[0, 0], [40, 0], [0, 30]] }],
          },
        }}
        alt="triangle"
      />,
    );
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
    expect(svg?.querySelector("polygon")).not.toBeNull();
    expect(svg?.getAttribute("aria-label")).toBe("triangle");
  });

  it("renders a scenario card for scenario_card specs", () => {
    render(
      <FigureRenderer
        spec={{
          render_mode: "html",
          description: "情境卡：博物館",
          data: { title: "博物館", items: ["票價 200 元", "開放時間 9:00-17:00"] },
        }}
      />,
    );
    expect(screen.getByText("博物館")).toBeInTheDocument();
    expect(screen.getByText("票價 200 元")).toBeInTheDocument();
  });

  it("returns null and logs a fallback for unsupported specs", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { container } = render(
      <FigureRenderer
        spec={{ render_mode: "chart", chart_type: "histogram", data: {} }}
      />,
    );
    expect(container).toBeEmptyDOMElement();
    expect(warn).toHaveBeenCalledWith(
      expect.stringMatching(/^\[figure-renderer-fallback]/),
      expect.anything(),
    );
    warn.mockRestore();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /workspace/exam-generation/web
npm test -- src/components/FigureRenderer.test.tsx
```

Expected: FAIL — `Cannot find module './FigureRenderer'`.

- [ ] **Step 3: Write the implementation**

Create `web/src/components/FigureRenderer.tsx`:

```tsx
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
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /workspace/exam-generation/web
npm test -- src/components/FigureRenderer.test.tsx
```

Expected: PASS — 12 tests green.

- [ ] **Step 5: Commit**

```bash
cd /workspace/exam-generation/web
git add src/components/FigureRenderer.tsx src/components/FigureRenderer.test.tsx
git commit -m "feat(web): prototype FigureRenderer for illustrative chart_spec shapes (#108)"
```

---

### Task 4: Dev-only toggle in `QuestionCard`

**Files:**
- Modify: `web/src/components/QuestionCard.tsx` (three `image_base64` render sites at lines ~95, ~258)
- Modify: `web/src/components/QuestionCard.test.tsx` (add a case that verifies the swap)

**Interfaces:**
- Consumes: `FigureRenderer`, `isFrontendTsEnabled` from Task 3; `chart_spec` field already present on `SubQuestion` (line 65) and `ExamQuestion` (line 87) in `web/src/hooks/useGenerate.ts`.
- Produces: no new exports. Behavioral change: when `isFrontendTsEnabled()` returns true AND `spec.chart_spec` classifies to a supported shape, render the TS component in place of the PNG `<img>`; otherwise render the PNG `<img>` unchanged.

- [ ] **Step 1: Write the failing test additions**

Append to `web/src/components/QuestionCard.test.tsx` (before its final closing bracket), adding a new `describe` block:

```tsx
import { vi, afterEach } from "vitest";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("QuestionCard + FigureRenderer swap", () => {
  it("renders the PNG img when VITE_ENABLE_FRONTEND_TS_RENDERER is unset", () => {
    vi.stubEnv("VITE_ENABLE_FRONTEND_TS_RENDERER", "");
    const question = {
      情境: [],
      題型種類: "單一題",
      題型: "選擇題",
      題目: ["Q"],
      正確解題分析: ["A"],
      image_base64: "aGVsbG8=",
      chart_spec: {
        render_mode: "html",
        description: "課表",
        data: { columns: ["a"], rows: [["1"]] },
      },
    } as unknown as import("../hooks/useGenerate").ExamQuestion;
    render(<QuestionCard question={question} isFinal />);
    expect(screen.getByRole("img")).toHaveAttribute(
      "src",
      "data:image/png;base64,aGVsbG8=",
    );
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("renders the FigureRenderer when the flag is on and the spec is supported", () => {
    vi.stubEnv("VITE_ENABLE_FRONTEND_TS_RENDERER", "1");
    const question = {
      情境: [],
      題型種類: "單一題",
      題型: "選擇題",
      題目: ["Q"],
      正確解題分析: ["A"],
      image_base64: "aGVsbG8=",
      chart_spec: {
        render_mode: "html",
        description: "課表",
        data: { columns: ["時段"], rows: [["9:00"]] },
      },
    } as unknown as import("../hooks/useGenerate").ExamQuestion;
    render(<QuestionCard question={question} isFinal />);
    expect(screen.getByRole("table")).toBeInTheDocument();
    // The PNG <img> should not be rendered in the diagram slot when the TS renderer took over.
    expect(screen.queryByAltText("Question diagram")).toBeNull();
  });

  it("falls back to the PNG img when the flag is on but the spec is unsupported", () => {
    vi.stubEnv("VITE_ENABLE_FRONTEND_TS_RENDERER", "1");
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const question = {
      情境: [],
      題型種類: "單一題",
      題型: "選擇題",
      題目: ["Q"],
      正確解題分析: ["A"],
      image_base64: "aGVsbG8=",
      chart_spec: { render_mode: "chart", chart_type: "histogram", data: {} },
    } as unknown as import("../hooks/useGenerate").ExamQuestion;
    render(<QuestionCard question={question} isFinal />);
    expect(screen.getByAltText("Question diagram")).toHaveAttribute(
      "src",
      "data:image/png;base64,aGVsbG8=",
    );
    expect(warn).toHaveBeenCalledWith(
      expect.stringMatching(/^\[figure-renderer-fallback]/),
      expect.anything(),
    );
    warn.mockRestore();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /workspace/exam-generation/web
npm test -- src/components/QuestionCard.test.tsx
```

Expected: FAIL — the middle test expects `getByRole("table")` but current `QuestionCard` always renders the PNG `<img>`.

- [ ] **Step 3: Wire `FigureRenderer` into `QuestionCard`**

In `web/src/components/QuestionCard.tsx`, add the import (below the existing `import { useT } from "../i18n/useT";` line):

```tsx
import FigureRenderer, {
  classifySpec,
  isFrontendTsEnabled,
  type ChartSpecInput,
} from "./FigureRenderer";
```

Add this helper directly after the existing `base64ToBlob` function (around line 40):

```tsx
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
    // Log so fallback rate is trackable in the browser console.
    console.warn("[figure-renderer-fallback] unsupported spec, using PNG", spec);
  }
  if (imageBase64) {
    return { kind: "png", src: `data:image/png;base64,${imageBase64}` };
  }
  // Silence unused-var lint when neither branch fires.
  void alt;
  return null;
}
```

Replace the sub-question image block (currently lines ~95–101):

```tsx
      {sub.image_base64 && (
        <img
          src={`data:image/png;base64,${sub.image_base64}`}
          alt={`第${sub.序號}題素材圖片`}
          className="max-w-full rounded border border-gray-200 bg-white"
        />
      )}
```

with:

```tsx
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
```

Replace the top-level question image block (currently lines ~258–264):

```tsx
      {question.image_base64 && (
        <img
          src={`data:image/png;base64,${question.image_base64}`}
          alt="Question diagram"
          className="max-w-full rounded border border-gray-200"
        />
      )}
```

with:

```tsx
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
```

Leave the download button at line ~327 (`{question.image_base64 && …}`) unchanged — the PNG download always uses the server-rendered bytes even when display swaps to the TS renderer.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /workspace/exam-generation/web
npm test
```

Expected: PASS — all `QuestionCard`, `CoreQuestionPicker`, and `FigureRenderer` tests green.

- [ ] **Step 5: Verify build + lint**

```bash
cd /workspace/exam-generation/web
npm run lint && npm run build
```

Expected: no lint errors; `tsc -b && vite build` succeeds.

- [ ] **Step 6: Commit**

```bash
cd /workspace/exam-generation/web
git add src/components/QuestionCard.tsx src/components/QuestionCard.test.tsx
git commit -m "feat(web): route illustrative chart_spec to FigureRenderer when VITE_ENABLE_FRONTEND_TS_RENDERER is set (#108)"
```

---

### Task 5: Manual Phase A evaluation — record fidelity, latency, coverage

**Files:**
- Create: `docs/figure-rendering-evaluation.md` (Phase A findings — used by Task 6 to record the go/no-go/hybrid decision)

**Interfaces:**
- Consumes: the coverage script from Task 2 pointed at `output/`; the toggled prototype from Tasks 3 + 4.
- Produces: a markdown evaluation report that Task 6 cites when writing the routing policy.

- [ ] **Step 1: Run the coverage classifier over a fresh sample of generated questions**

```bash
cd /workspace/exam-generation
uv run python scripts/analyze_chart_spec_coverage.py output/ > /tmp/coverage.md
cat /tmp/coverage.md
```

Expected: prints a Markdown table with counts + percentages. If `output/` is empty, generate ~30 questions first (`uv run python -m src.social_studies.cli generate --count 10 --no-verify`, similar for math + natural sciences) and re-run.

- [ ] **Step 2: Run the web dev server with the flag on and eyeball ~10 real specs side-by-side**

```bash
cd /workspace/exam-generation/web
VITE_ENABLE_FRONTEND_TS_RENDERER=1 npm run dev
```

In the browser, generate questions with `題目內容類型 = 含圖片` (illustrative) and `graphs/charts/tables` (quantitative), and record:

- **Fidelity** — for each spec, note whether the TS render conveys the same information as the server PNG (score: match / degraded / broken).
- **Latency** — first illustrative render's time-to-visible with the flag ON vs OFF (browser DevTools Performance tab).
- **Coverage** — count how many `[figure-renderer-fallback]` log lines fired vs total illustrative specs rendered.

- [ ] **Step 3: Author `docs/figure-rendering-evaluation.md`**

Fill in with the observed numbers from Steps 1–2:

```markdown
# Frontend TS Renderer — Phase A Evaluation (issue #108)

## Scope

Prototype: `web/src/components/FigureRenderer.tsx` covering three illustrative
shapes — tables, simple SVG geometry, scenario cards. Gated behind
`VITE_ENABLE_FRONTEND_TS_RENDERER`. Compared against the current LLM-HTML +
Playwright path via a dev-only side-by-side.

## Historical coverage

Output of `uv run python scripts/analyze_chart_spec_coverage.py output/`:

<paste the Markdown table produced in Step 1>

## Fidelity (side-by-side of ~10 real specs)

| # | 題目內容類型 | shape | TS render | server PNG | verdict |
| --- | --- | --- | --- | --- | --- |
<one row per spec observed in Step 2 — verdict ∈ {match, degraded, broken}>

## Latency

- LLM-HTML + Playwright path: <ms> average (~<n> runs), dominated by the
  Sonnet HTML-generation call.
- Frontend TS path: <ms> average (~<n> runs); no LLM call, no server
  round-trip beyond the initial JSON payload.

## Cost

Every illustrative render in the current path incurs one Sonnet HTML-image
call (see `renderer.py` `_generate_html_via_llm`). The TS path incurs zero.
Estimated monthly savings at <N> illustrative questions/day: <$>.

## Coverage

- Total illustrative specs observed: <N>.
- Rendered by the TS component: <n> (<pct>%).
- Fallbacks logged: <n> (<pct>%).

## Export constraint

Verifier and ODT export both consume the server-side PNG (`image_base64`).
Even in the "go" outcome, the server path stays for those flows — TS
rendering only affects on-page display.

## Decision

**<GO | NO-GO | HYBRID>** — <one-sentence rationale>.

If HYBRID / GO, Task 10 of the plan extends the `render_mode` enum with
`"frontend_ts"` and updates `CONTENT_TYPE_INSTRUCTIONS`; the `"html"` value
remains a permanent legacy alias.
```

- [ ] **Step 4: Commit**

```bash
cd /workspace/exam-generation
git add docs/figure-rendering-evaluation.md
git commit -m "docs: record Phase A evaluation of the frontend TS renderer (#108)"
```

---

### Task 6: `docs/figure-rendering-policy.md` — the routing rule

**Files:**
- Create: `docs/figure-rendering-policy.md`

**Interfaces:**
- Consumes: Task 5's evaluation for the go/no-go/hybrid decision.
- Produces: the policy doc that Task 7 anchors to from the three `context_builder.py` files, and that Task 8 asserts prompts route to.

- [ ] **Step 1: Author the policy doc**

Create `docs/figure-rendering-policy.md`:

```markdown
# Figure Rendering Policy

Owner: exam-generation. Status: authoritative — the three `src/**/context_builder.py`
modules and the Pydantic `ImageSpec` schemas cite this file. Related GitHub
issues: #108 (frontend TS renderer evaluation), #110 (routing policy).

## The rule

Every `chart_spec` on an `ExamQuestion` or `SubQuestion` MUST route to one of
the following renderers, chosen by the character of the figure — **not** by the
question's subject, grade, or 學習內容 code.

| Figure family | Examples | `render_mode` | Renderer |
| --- | --- | --- | --- |
| Precise / quantitative statistical charts | 直方圖, 盒鬚圖, 折線圖, 圓餅圖, 未來加入的任何座標軸帶刻度的統計圖 | `"chart"` | matplotlib (`src/renderer.py::render_chart`) |
| Illustrative figures | 幾何示意圖, 座標平面, 數線, 表格, 菜單, 廣告, 海報, 情境卡, 流程圖 | `"html"` (or `"frontend_ts"` — see below) | LLM-HTML + Playwright (`src/renderer.py::_generate_html_via_llm` + `src/html_renderer.py`) |

### Why this split

- Statistical charts have deterministic axes, tick labels, and derived
  aggregates (mean, median, quantiles). Rendering them via an LLM introduces
  drift between the numeric spec and the pixels a student reads. matplotlib
  is deterministic and cheap; keep it authoritative.
- Illustrative figures are open-ended — no fixed axes, arbitrary layout,
  domain-specific pictorial conventions (e.g. a museum menu, a bus route
  card). The HTML path lets the LLM invent layout details the schema does
  not encode; this is the correct trade-off for that family.

## Phase A outcome (issue #108)

The Phase A evaluation (`docs/figure-rendering-evaluation.md`) recorded a
**<GO | NO-GO | HYBRID>** decision for adding a frontend TS renderer.

- **NO-GO**: `render_mode` stays `Literal["chart", "html"]`. The frontend TS
  prototype remains behind `VITE_ENABLE_FRONTEND_TS_RENDERER` for further
  experimentation but is not part of the shipped routing.
- **GO / HYBRID**: `render_mode` accepts a third value `"frontend_ts"` for
  illustrative figures whose display can be done client-side. Verifier and
  ODT export still consume the server-side PNG, so illustrative specs also
  keep producing one — the frontend TS renderer replaces the on-page
  `<img>` display only. `"html"` remains permanently accepted as a legacy
  alias for already-generated questions.

## What each subject's prompt must instruct

The three prompt assemblers already encode this rule in their
`CONTENT_TYPE_INSTRUCTIONS` tables (`src/context_builder.py`,
`src/social_studies/context_builder.py`,
`src/natural_sciences/context_builder.py`). Concretely, given
`題目內容類型` (or `文本素材類型` for 社會領域 全域):

| 題目內容類型 | Instruction MUST direct the model to |
| --- | --- |
| `純文字` | Omit `chart_spec` entirely. |
| `含圖片` | Emit `chart_spec` with `render_mode: "html"` (illustrative path). |
| `graphs/charts/tables` | Emit `chart_spec` with `render_mode: "chart"` when a listed statistical chart applies; otherwise `render_mode: "html"` for tables. |
| `customized` | Follow the user-supplied instruction verbatim; no default. |

## Enforcement

- `tests/test_figure_rendering_policy.py::test_prompt_routes_illustrative_to_html`
  and `::test_prompt_routes_quantitative_to_chart` assert the
  `CONTENT_TYPE_INSTRUCTIONS` strings for each of the three subjects contain
  the correct `render_mode:"…"` fragment.
- `tests/test_figure_rendering_policy.py::test_dispatch_matches_render_mode`
  fixture-tests that `render_image()` in `src/renderer.py` dispatches each
  ImageSpec to the intended renderer.

## Out of scope of this policy

- matplotlib improvements to individual chart renderers.
- Migrating already-generated questions to a different `render_mode`.
- Interactive (non-static) question features.
```

- [ ] **Step 2: Verify the doc links back to itself only via existing files**

```bash
cd /workspace/exam-generation
grep -n "figure-rendering-policy" docs/figure-rendering-policy.md
```

Expected: prints only self-references inside the doc; no broken paths elsewhere yet (Task 7 adds the backlinks from the three context_builder files).

- [ ] **Step 3: Commit**

```bash
cd /workspace/exam-generation
git add docs/figure-rendering-policy.md
git commit -m "docs: codify figure-rendering routing policy (#110)"
```

---

### Task 7: Point each `context_builder.py` at the policy doc

**Files:**
- Modify: `src/context_builder.py:1` (module docstring)
- Modify: `src/social_studies/context_builder.py:1` (module docstring)
- Modify: `src/natural_sciences/context_builder.py:2` (module docstring — line 1 is the `# ruff: noqa: E501` pragma)

**Interfaces:**
- Consumes: `docs/figure-rendering-policy.md` from Task 6.
- Produces: no code exports. Documentation cross-link that the classification test in Task 8 also asserts is present.

- [ ] **Step 1: Write the failing test**

Create `tests/test_context_builder_docstrings.py`:

```python
"""Every context_builder.py must cite the figure-rendering policy doc."""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_POLICY_ANCHOR = "docs/figure-rendering-policy.md"

_TARGETS = [
    _ROOT / "src" / "context_builder.py",
    _ROOT / "src" / "social_studies" / "context_builder.py",
    _ROOT / "src" / "natural_sciences" / "context_builder.py",
]


@pytest.mark.parametrize("path", _TARGETS, ids=lambda p: p.relative_to(_ROOT).as_posix())
def test_module_docstring_cites_figure_rendering_policy(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    # The policy anchor must appear inside the first module-level docstring block.
    head = text.split('"""', 3)
    assert len(head) >= 3, f"{path} has no module docstring"
    docstring = head[1]
    assert _POLICY_ANCHOR in docstring, (
        f"{path.relative_to(_ROOT).as_posix()} module docstring must cite "
        f"{_POLICY_ANCHOR}"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /workspace/exam-generation
uv run pytest tests/test_context_builder_docstrings.py -x
```

Expected: FAIL — none of the three docstrings contain `docs/figure-rendering-policy.md` yet.

- [ ] **Step 3: Update each docstring**

Replace `src/context_builder.py` line 1:

```python
"""Assemble LLM prompts with curriculum context and few-shot examples."""
```

with:

```python
"""Assemble LLM prompts with curriculum context and few-shot examples.

Figure routing: any `chart_spec` this module instructs the model to emit must
follow the rule in ``docs/figure-rendering-policy.md`` — precise/quantitative
statistical charts use ``render_mode: "chart"`` (matplotlib); illustrative
figures use ``render_mode: "html"`` (LLM-HTML + Playwright). See
``CONTENT_TYPE_INSTRUCTIONS`` below for the per-``題目內容類型`` mapping.
"""
```

Replace `src/social_studies/context_builder.py` line 1:

```python
"""Assemble LLM prompts for 108課綱 社會領域素養導向 question generation."""
```

with:

```python
"""Assemble LLM prompts for 108課綱 社會領域素養導向 question generation.

Figure routing: any `chart_spec` this module instructs the model to emit
(top-level 題組 material or per-小題 supplements) must follow the rule in
``docs/figure-rendering-policy.md`` — precise/quantitative statistical charts
use ``render_mode: "chart"`` (matplotlib); illustrative figures — maps,
posters, tables, scenario cards — use ``render_mode: "html"`` (LLM-HTML +
Playwright). See ``CONTENT_TYPE_INSTRUCTIONS`` below for the per-``文本素材類型``
mapping.
"""
```

Replace `src/natural_sciences/context_builder.py` line 2 (leave the `# ruff: noqa: E501` pragma on line 1):

```python
"""Assemble LLM prompts for PISA Science + 108課綱自然科學 question generation."""
```

with:

```python
"""Assemble LLM prompts for PISA Science + 108課綱自然科學 question generation.

Figure routing: any `chart_spec` this module instructs the model to emit
must follow the rule in ``docs/figure-rendering-policy.md`` —
precise/quantitative statistical charts use ``render_mode: "chart"``
(matplotlib); illustrative figures — 實驗裝置圖, 模型圖, 流程圖, 標籤圖,
data tables — use ``render_mode: "html"`` (LLM-HTML + Playwright). See
``CONTENT_TYPE_INSTRUCTIONS`` below for the per-``題目內容類型`` mapping.
"""
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /workspace/exam-generation
uv run pytest tests/test_context_builder_docstrings.py -x
```

Expected: PASS — 3 tests green.

- [ ] **Step 5: Commit**

```bash
cd /workspace/exam-generation
git add src/context_builder.py src/social_studies/context_builder.py src/natural_sciences/context_builder.py tests/test_context_builder_docstrings.py
git commit -m "docs: cite figure-rendering-policy from all three context_builder docstrings (#110)"
```

---

### Task 8: Classification test — prompts route each `題目內容類型` to the correct `render_mode`

**Files:**
- Create: `tests/test_figure_rendering_policy.py` (add classification tests; Task 9 extends the same file with dispatch tests)

**Interfaces:**
- Consumes: `CONTENT_TYPE_INSTRUCTIONS` from all three `context_builder.py` modules.
- Produces: pytest cases pinning the mapping specified in `docs/figure-rendering-policy.md`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_figure_rendering_policy.py`:

```python
"""Classification + dispatch tests for the figure-rendering routing policy.

Source of truth: docs/figure-rendering-policy.md.
"""

from __future__ import annotations

import pytest

from src.context_builder import CONTENT_TYPE_INSTRUCTIONS as MATH_CT
from src.natural_sciences.context_builder import (
    CONTENT_TYPE_INSTRUCTIONS as NS_CT,
)
from src.social_studies.context_builder import (
    CONTENT_TYPE_INSTRUCTIONS as SS_CT,
)

_SUBJECT_TABLES = [
    pytest.param("math", MATH_CT, id="math"),
    pytest.param("social_studies", SS_CT, id="social_studies"),
    pytest.param("natural_sciences", NS_CT, id="natural_sciences"),
]


@pytest.mark.parametrize("subject, table", _SUBJECT_TABLES)
def test_plain_text_bans_chart_spec(subject: str, table: dict) -> None:
    assert "純文字" in table
    text = table["純文字"]
    assert "chart_spec" in text
    # The policy forbids any chart_spec output for 純文字.
    assert ("不得輸出" in text) or ("不輸出" in text)


@pytest.mark.parametrize("subject, table", _SUBJECT_TABLES)
def test_illustrative_content_routes_to_html(subject: str, table: dict) -> None:
    assert "含圖片" in table
    text = table["含圖片"]
    assert 'render_mode: "html"' in text, (
        f"{subject}: 含圖片 instruction must direct the model to render_mode: \"html\""
    )


@pytest.mark.parametrize("subject, table", _SUBJECT_TABLES)
def test_quantitative_content_routes_to_chart_and_html_for_tables(
    subject: str, table: dict
) -> None:
    assert "graphs/charts/tables" in table
    text = table["graphs/charts/tables"]
    assert 'render_mode: "chart"' in text, (
        f"{subject}: graphs/charts/tables instruction must mention render_mode: \"chart\""
    )
    assert 'render_mode: "html"' in text, (
        f"{subject}: graphs/charts/tables instruction must also mention render_mode: \"html\" for tables"
    )
```

- [ ] **Step 2: Run the tests to verify they pass (they should — the current instructions already match)**

```bash
cd /workspace/exam-generation
uv run pytest tests/test_figure_rendering_policy.py -x
```

Expected: PASS — 9 parametrised tests green. If any fail, the corresponding `CONTENT_TYPE_INSTRUCTIONS` block has drifted from the policy — restore it before proceeding (do NOT loosen the test).

- [ ] **Step 3: Commit**

```bash
cd /workspace/exam-generation
git add tests/test_figure_rendering_policy.py
git commit -m "test: pin content_type -> render_mode routing per figure-rendering-policy (#110)"
```

---

### Task 9: Dispatch test — `render_image()` sends each `ImageSpec` to the intended renderer

**Files:**
- Modify: `tests/test_figure_rendering_policy.py` (append the dispatch cases created here)

**Interfaces:**
- Consumes: `src.renderer.render_image` (the fixture-based test injects fake `html_renderer` and `llm_client` so no matplotlib / Playwright / OpenAI call fires).
- Produces: pytest cases verifying the dispatch matrix in `render_image`.

- [ ] **Step 1: Write the failing tests (append to `tests/test_figure_rendering_policy.py`)**

Append to `tests/test_figure_rendering_policy.py`:

```python
# --- Dispatch tests ---------------------------------------------------------


class _RecordingHtmlRenderer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def render(self, html: str, output_path):  # noqa: D401
        self.calls.append((html, str(output_path)))
        return str(output_path)


class _RecordingLlmClient:
    def __init__(self) -> None:
        self.html_calls: list[dict] = []
        self.image_calls: list[dict] = []

    def generate(self, system: str, user: str, purpose: str = "") -> str:
        self.html_calls.append({"system": system, "user": user, "purpose": purpose})
        return "<!DOCTYPE html><html><body>fake</body></html>"

    def generate_image(self, prompt: str, output_path):
        self.image_calls.append({"prompt": prompt, "output_path": str(output_path)})
        return str(output_path)


def test_dispatch_chart_render_mode_uses_matplotlib(tmp_path, monkeypatch) -> None:
    from src import renderer

    called: dict = {}

    def fake_render_chart(spec, output_path):
        called["spec"] = spec
        called["output_path"] = str(output_path)
        return str(output_path)

    monkeypatch.setattr(renderer, "render_chart", fake_render_chart)
    html_renderer = _RecordingHtmlRenderer()
    llm_client = _RecordingLlmClient()

    out = tmp_path / "hist.png"
    result = renderer.render_image(
        {"render_mode": "chart", "chart_type": "histogram", "data": {"bins": [], "counts": []}},
        out,
        html_renderer=html_renderer,
        llm_client=llm_client,
        image_generation_mode="html",
    )

    assert result == str(out)
    assert called["spec"]["chart_type"] == "histogram"
    assert html_renderer.calls == []
    assert llm_client.html_calls == []
    assert llm_client.image_calls == []


def test_dispatch_html_render_mode_uses_playwright(tmp_path) -> None:
    from src import renderer

    html_renderer = _RecordingHtmlRenderer()
    llm_client = _RecordingLlmClient()

    out = tmp_path / "table.png"
    result = renderer.render_image(
        {"render_mode": "html", "description": "課表", "data": {"columns": ["a"], "rows": [["1"]]}},
        out,
        html_renderer=html_renderer,
        llm_client=llm_client,
        image_generation_mode="html",
    )

    assert result == str(out)
    assert len(llm_client.html_calls) == 1
    assert len(html_renderer.calls) == 1
    assert llm_client.image_calls == []


def test_dispatch_gpt_image_mode_bypasses_render_mode(tmp_path) -> None:
    from src import renderer

    html_renderer = _RecordingHtmlRenderer()
    llm_client = _RecordingLlmClient()

    out = tmp_path / "gpt.png"
    result = renderer.render_image(
        {"render_mode": "chart", "chart_type": "histogram", "data": {}},
        out,
        html_renderer=html_renderer,
        llm_client=llm_client,
        image_generation_mode="gpt_image",
    )

    assert result == str(out)
    assert html_renderer.calls == []
    assert llm_client.html_calls == []
    assert len(llm_client.image_calls) == 1


def test_dispatch_unknown_render_mode_returns_none(tmp_path) -> None:
    from src import renderer

    html_renderer = _RecordingHtmlRenderer()
    llm_client = _RecordingLlmClient()

    out = tmp_path / "unknown.png"
    result = renderer.render_image(
        {"render_mode": "nonsense", "data": {}},
        out,
        html_renderer=html_renderer,
        llm_client=llm_client,
        image_generation_mode="html",
    )

    assert result is None
    assert html_renderer.calls == []
    assert llm_client.html_calls == []
    assert llm_client.image_calls == []
```

- [ ] **Step 2: Run the tests to verify they pass**

```bash
cd /workspace/exam-generation
uv run pytest tests/test_figure_rendering_policy.py -x
```

Expected: PASS — 13 parametrised tests green (9 classification + 4 dispatch).

- [ ] **Step 3: Commit**

```bash
cd /workspace/exam-generation
git add tests/test_figure_rendering_policy.py
git commit -m "test: pin render_image dispatch by render_mode and image_generation_mode (#110)"
```

---

### Task 10 (conditional on Phase A = GO or HYBRID): Extend `render_mode` with `"frontend_ts"`

**Files:**
- Modify: `src/schemas.py:55` (`ImageSpec.render_mode` Literal)
- Modify: `src/social_studies/schemas.py:20` (`ImageSpec.render_mode` Literal)
- Modify: `src/natural_sciences/schemas.py:20` (`ImageSpec.render_mode` Literal)
- Modify: `src/context_builder.py:53-69` (`CONTENT_TYPE_INSTRUCTIONS`)
- Modify: `src/social_studies/context_builder.py:50-70` (`CONTENT_TYPE_INSTRUCTIONS`)
- Modify: `src/natural_sciences/context_builder.py:74-95` (`CONTENT_TYPE_INSTRUCTIONS`)
- Modify: `tests/test_figure_rendering_policy.py` (add coverage for the new value)

**Interfaces:**
- Consumes: the Task 5 decision recorded in `docs/figure-rendering-evaluation.md` (`GO` or `HYBRID`).
- Produces: `"frontend_ts"` accepted alongside `"chart"` and `"html"` (the latter permanently retained as a legacy alias); the illustrative `CONTENT_TYPE_INSTRUCTIONS` rows emit `render_mode: "frontend_ts"`.

**Skip this entire task** if `docs/figure-rendering-evaluation.md` records `NO-GO`. Move directly to Task 11.

- [ ] **Step 1: Write the failing test additions**

Append to `tests/test_figure_rendering_policy.py`:

```python
# --- frontend_ts extension (Phase A: GO or HYBRID) --------------------------


def test_image_spec_accepts_frontend_ts_render_mode() -> None:
    from src.schemas import ImageSpec as MathSpec
    from src.natural_sciences.schemas import ImageSpec as NsSpec
    from src.social_studies.schemas import ImageSpec as SsSpec

    for cls in (MathSpec, SsSpec, NsSpec):
        spec = cls(render_mode="frontend_ts", description="表格", data={"columns": [], "rows": []})
        assert spec.render_mode == "frontend_ts"
        # Legacy alias must still parse.
        assert cls(render_mode="html").render_mode == "html"


@pytest.mark.parametrize("subject, table", _SUBJECT_TABLES)
def test_illustrative_content_routes_to_frontend_ts(subject: str, table: dict) -> None:
    text = table["含圖片"]
    assert 'render_mode: "frontend_ts"' in text, (
        f"{subject}: 含圖片 must emit render_mode: \"frontend_ts\" post-GO"
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /workspace/exam-generation
uv run pytest tests/test_figure_rendering_policy.py -x
```

Expected: FAIL — Pydantic rejects `"frontend_ts"`, and the 含圖片 instructions still say `"html"`.

- [ ] **Step 3: Extend the three `ImageSpec` Literals**

In `src/schemas.py`, replace line 55:

```python
    render_mode: Literal["chart", "html"] = "chart"
```

with:

```python
    render_mode: Literal["chart", "html", "frontend_ts"] = "chart"
```

Apply the identical replacement to `src/social_studies/schemas.py` line 20 and `src/natural_sciences/schemas.py` line 20.

- [ ] **Step 4: Update illustrative `CONTENT_TYPE_INSTRUCTIONS` rows**

In `src/context_builder.py`, replace the `"含圖片"` block (lines 58–61):

```python
    "含圖片": (
        "本題目必須包含圖片或視覺示意素材（幾何圖形、示意圖、版面等）。"
        "請輸出 `chart_spec`，優先使用 `render_mode: \"html\"`，並在 `description` 與 `data` 中完整描述版面與內容。"
    ),
```

with:

```python
    "含圖片": (
        "本題目必須包含圖片或視覺示意素材（幾何圖形、示意圖、版面等）。"
        "請輸出 `chart_spec`，優先使用 `render_mode: \"frontend_ts\"`（前端 TS 渲染路徑；"
        "`\"html\"` 為既有題目的相容別名，仍可接受），並在 `description` 與 `data` 中完整描述版面與內容。"
    ),
```

In `src/social_studies/context_builder.py`, replace the `"含圖片"` block (lines 55–62):

```python
    "含圖片": (
        "本題組必須包含圖片式或視覺式非連續素材，例如地圖、圖解、廣告、表單、海報或網頁畫面。"
        "請在題組頂層輸出非 null 的 `chart_spec`，優先使用 `render_mode: \"html\"`，"
        "並在 `description` 與 `data` 中完整描述版面與內容。"
        "（重要）圖片必須是作答的必要條件：至少一道小題的答案必須直接依賴圖片中才有的資訊，無法僅憑文本回答。"
        "設計時請先確定「移除圖片後此題是否仍可作答」——若可以，請重新設計圖片，使其承載文本中未涵蓋的關鍵資訊"
        "（例如地圖上的地名/路線/分布、廣告上的價格/期限/規則、表單上的數據欄位）。"
    ),
```

with:

```python
    "含圖片": (
        "本題組必須包含圖片式或視覺式非連續素材，例如地圖、圖解、廣告、表單、海報或網頁畫面。"
        "請在題組頂層輸出非 null 的 `chart_spec`，優先使用 `render_mode: \"frontend_ts\"`"
        "（前端 TS 渲染路徑；`\"html\"` 為既有題目的相容別名，仍可接受），"
        "並在 `description` 與 `data` 中完整描述版面與內容。"
        "（重要）圖片必須是作答的必要條件：至少一道小題的答案必須直接依賴圖片中才有的資訊，無法僅憑文本回答。"
        "設計時請先確定「移除圖片後此題是否仍可作答」——若可以，請重新設計圖片，使其承載文本中未涵蓋的關鍵資訊"
        "（例如地圖上的地名/路線/分布、廣告上的價格/期限/規則、表單上的數據欄位）。"
    ),
```

In `src/natural_sciences/context_builder.py`, replace the `"含圖片"` block (lines 79–83; find the block that begins `"本題組必須包含視覺式科學素材"` after Task 7's docstring edit) — leave the leading `本題組必須包含視覺式科學素材` sentence intact and update the `render_mode` clause to say `render_mode: "frontend_ts"` (前端 TS 渲染路徑；`"html"` 為既有題目的相容別名，仍可接受）` using the same phrasing pattern as above. Preserve the ruff `# noqa: E501` pragma on line 1.

Leave every `graphs/charts/tables` block untouched — quantitative charts remain on the matplotlib path.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd /workspace/exam-generation
uv run pytest tests/test_figure_rendering_policy.py -x
```

Expected: PASS — the two new tests plus the existing 13 all green.

- [ ] **Step 6: Update the frontend renderer classifier to accept `render_mode: "frontend_ts"`**

In `web/src/components/FigureRenderer.tsx`, replace the opening of `classifySpec`:

```ts
export function classifySpec(spec: ChartSpecInput): FigureCategory {
  const mode = (spec.render_mode ?? "").toLowerCase();
  if (mode === "chart") return "unsupported";
```

with:

```ts
export function classifySpec(spec: ChartSpecInput): FigureCategory {
  const mode = (spec.render_mode ?? "").toLowerCase();
  if (mode === "chart") return "unsupported";
  // "html" and "frontend_ts" both flow through the illustrative branch below.
```

(The subsequent classification logic already handles both modes identically because it keys off `data` shape, not `render_mode`.)

- [ ] **Step 7: Run the full test suites**

```bash
cd /workspace/exam-generation
uv run pytest -x
cd /workspace/exam-generation/web
npm test
```

Expected: PASS for both.

- [ ] **Step 8: Commit**

```bash
cd /workspace/exam-generation
git add src/schemas.py src/social_studies/schemas.py src/natural_sciences/schemas.py \
        src/context_builder.py src/social_studies/context_builder.py src/natural_sciences/context_builder.py \
        tests/test_figure_rendering_policy.py \
        web/src/components/FigureRenderer.tsx
git commit -m "feat: accept render_mode=\"frontend_ts\" for illustrative figures (#108, #110)"
```

---

### Task 11: Link the policy from `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md` (`## Image Rendering Architecture` section, currently starting at line 344)

**Interfaces:**
- Consumes: `docs/figure-rendering-policy.md` from Task 6.
- Produces: an in-tree pointer so future contributors read the policy before touching `render_mode`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_context_builder_docstrings.py`:

```python
def test_claude_md_links_figure_rendering_policy() -> None:
    text = (_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "docs/figure-rendering-policy.md" in text
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /workspace/exam-generation
uv run pytest tests/test_context_builder_docstrings.py::test_claude_md_links_figure_rendering_policy -x
```

Expected: FAIL — `docs/figure-rendering-policy.md` is not yet cited from `CLAUDE.md`.

- [ ] **Step 3: Add the link in `CLAUDE.md`**

In `CLAUDE.md`, immediately after the paragraph starting `Images are described by \`ImageSpec\`` (line 346), insert:

```markdown
> **Routing rule:** which `render_mode` value the prompt asks the model to emit is codified in [`docs/figure-rendering-policy.md`](docs/figure-rendering-policy.md). Every `src/**/context_builder.py` module cites that doc from its top-level docstring — update the policy first, then the docstrings, then the `CONTENT_TYPE_INSTRUCTIONS` tables.
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /workspace/exam-generation
uv run pytest tests/test_context_builder_docstrings.py -x
```

Expected: PASS — 4 tests green (3 docstring cases + the new CLAUDE.md case).

- [ ] **Step 5: Commit**

```bash
cd /workspace/exam-generation
git add CLAUDE.md tests/test_context_builder_docstrings.py
git commit -m "docs: link figure-rendering-policy from CLAUDE.md Image Rendering section (#110)"
```

---

### Task 12: Final verification sweep

**Files:** none (verification only).

**Interfaces:**
- Consumes: every commit above.

- [ ] **Step 1: Full backend test suite**

```bash
cd /workspace/exam-generation
uv run pytest
```

Expected: all tests pass, including the new `tests/test_analyze_chart_spec_coverage.py`, `tests/test_context_builder_docstrings.py`, and `tests/test_figure_rendering_policy.py`.

- [ ] **Step 2: Full frontend test suite + build**

```bash
cd /workspace/exam-generation/web
npm test && npm run lint && npm run build
```

Expected: vitest green, no lint errors, `tsc -b && vite build` succeeds.

- [ ] **Step 3: Grep for accidental removals of the `"html"` legacy alias**

```bash
cd /workspace/exam-generation
grep -R 'Literal\["chart"\]' src/ && echo "FAIL: html alias removed" || echo "ok"
grep -R 'render_mode.*"html"' src/ | head -5
```

Expected: first grep prints `ok` (no bare `Literal["chart"]` — the "html" alias is still present); second grep shows lingering `"html"` references confirming the alias survived.

- [ ] **Step 4: Confirm the plan spec coverage**

Manually cross-check the spec's bullet list against the completed tasks:

- Phase A prototype → Tasks 3 + 4.
- Fidelity / latency / coverage evaluation → Task 5 (with Task 2 supplying coverage numbers).
- Export constraint captured → Task 5 evaluation doc + Task 6 policy doc.
- Phase B policy doc → Task 6.
- Context-builder docstrings → Task 7.
- Classification test → Task 8.
- Dispatch test → Task 9.
- Optional `frontend_ts` enum + updated instructions → Task 10 (skipped only on NO-GO).
- Policy linked from `CLAUDE.md` → Task 11.
- Fallback logging for coverage tracking → Task 3's `[figure-renderer-fallback]` console.warn + Task 4's fallback branch.
- `render_mode:"html"` retained as legacy alias forever → global constraints + Task 10 Literal.

If any spec bullet is unclaimed, open a follow-up issue rather than silently leaving it out.

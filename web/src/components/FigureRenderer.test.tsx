import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";

const recordFigureFallbackMock = vi.hoisted(() => vi.fn());

vi.mock("../utils/figureFallbackMetric", () => ({
  recordFigureFallback: recordFigureFallbackMock,
}));

afterEach(() => {
  vi.unstubAllEnvs();
  vi.clearAllMocks();
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

  it("returns null and records a fallback for unsupported specs", () => {
    const spec = { render_mode: "chart", chart_type: "histogram", data: {} };
    const { container } = render(
      <FigureRenderer spec={spec} />,
    );
    expect(container).toBeEmptyDOMElement();
    expect(recordFigureFallbackMock).toHaveBeenCalledWith(spec);
  });
});

import { beforeEach, describe, expect, it, vi } from "vitest";

const countMock = vi.hoisted(() => vi.fn());
const isSentryEnabledMock = vi.hoisted(() => vi.fn());

vi.mock("@sentry/react", () => ({
  metrics: {
    count: countMock,
  },
}));

vi.mock("../sentry", () => ({
  isSentryEnabled: isSentryEnabledMock,
}));

import { recordFigureFallback } from "./figureFallbackMetric";

beforeEach(() => {
  vi.clearAllMocks();
  isSentryEnabledMock.mockReturnValue(true);
});

describe("recordFigureFallback", () => {
  it("passes only category and render_mode attributes to Sentry", () => {
    recordFigureFallback({
      render_mode: "html",
      description: "課表",
      data: { columns: ["時段"], rows: [["9:00"]] },
    });

    expect(countMock.mock.calls[0]?.[2]?.attributes).toEqual({
      category: "table",
      render_mode: "html",
    });
  });

  it("increments the fallback counter for an unsupported chart spec", () => {
    recordFigureFallback({
      render_mode: "chart",
      chart_type: "histogram",
      data: {},
    });

    expect(countMock).toHaveBeenCalledTimes(1);
    expect(countMock).toHaveBeenCalledWith("figure_renderer.fallback", 1, {
      attributes: expect.objectContaining({
        category: "unsupported",
        render_mode: "chart",
      }),
    });
  });

  it("sanitizes an arbitrary render_mode to other", () => {
    recordFigureFallback({
      render_mode: "SomeWildValue123",
      data: {},
    });

    expect(countMock).toHaveBeenCalledWith("figure_renderer.fallback", 1, {
      attributes: expect.objectContaining({
        render_mode: "other",
      }),
    });
  });

  it("sanitizes a missing render_mode to other", () => {
    expect(() => recordFigureFallback({ data: {} })).not.toThrow();
    expect(countMock).toHaveBeenCalledWith("figure_renderer.fallback", 1, {
      attributes: expect.objectContaining({
        render_mode: "other",
      }),
    });
  });

  it("does not call Sentry when Sentry is disabled", () => {
    isSentryEnabledMock.mockReturnValue(false);

    recordFigureFallback({
      render_mode: "chart",
      chart_type: "histogram",
      data: {},
    });

    expect(countMock).not.toHaveBeenCalled();
  });
});

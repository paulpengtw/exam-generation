import * as Sentry from "@sentry/react";

import { classifySpec } from "../components/FigureRenderer";
import type { ChartSpecInput } from "../components/FigureRenderer";
import { isSentryEnabled } from "../sentry";

export function recordFigureFallback(spec: ChartSpecInput): void {
  if (!isSentryEnabled()) return;

  const renderMode = (spec.render_mode ?? "").toLowerCase();
  const sanitizedRenderMode =
    renderMode === "chart" || renderMode === "html" || renderMode === "gpt_image"
      ? renderMode
      : "other";

  Sentry.metrics.count("figure_renderer.fallback", 1, {
    attributes: {
      category: classifySpec(spec),
      render_mode: sanitizedRenderMode,
    },
  });
}

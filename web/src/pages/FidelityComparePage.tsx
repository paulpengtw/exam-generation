/**
 * Operator harness for the issue #110 fidelity comparison (Part A gate evidence).
 *
 * Load fidelity/manifest.json (built by scripts/build_fidelity_manifest.py),
 * eyeball server PNG vs frontend TS render for every illustrative spec, rate
 * each pair, and paste the exported Markdown into
 * docs/figure-rendering-evaluation.md. Gated behind
 * VITE_ENABLE_FRONTEND_TS_RENDERER like the FigureRenderer prototype itself.
 */

import { useState } from "react";
import FigureRenderer, {
  classifySpec,
  isFrontendTsEnabled,
  type ChartSpecInput,
} from "../components/FigureRenderer";

export interface FidelityEntry {
  id: string;
  subject: string;
  category: string;
  spec: ChartSpecInput;
  server_png_base64: string | null;
  question_text?: string;
}

export type Verdict = "unrated" | "match" | "minor-diff" | "broken";

// eslint-disable-next-line react-refresh/only-export-components -- utility export co-located with the harness page by design
export function parseManifest(text: string): FidelityEntry[] {
  const raw: unknown = JSON.parse(text);
  if (!Array.isArray(raw)) throw new Error("manifest must be a JSON array");
  return raw.map((entry, i) => {
    const e = entry as Partial<FidelityEntry> | null;
    if (!e || typeof e !== "object" || typeof e.id !== "string" || !e.spec) {
      throw new Error(`manifest entry ${i} is missing id or spec`);
    }
    return e as FidelityEntry;
  });
}

// eslint-disable-next-line react-refresh/only-export-components -- utility export co-located with the harness page by design
export function toMarkdownTable(
  entries: FidelityEntry[],
  verdicts: Record<string, Verdict>,
): string {
  const lines = [
    "| # | id | subject | shape | TS render | verdict |",
    "| --- | --- | --- | --- | --- | --- |",
  ];
  entries.forEach((e, i) => {
    const shape = classifySpec(e.spec);
    const ts = shape === "unsupported" ? "fallback (PNG)" : "TS";
    lines.push(
      `| ${i + 1} | ${e.id} | ${e.subject} | ${shape} | ${ts} | ${verdicts[e.id] ?? "unrated"} |`,
    );
  });
  return lines.join("\n");
}

export default function FidelityComparePage() {
  const [entries, setEntries] = useState<FidelityEntry[]>([]);
  const [verdicts, setVerdicts] = useState<Record<string, Verdict>>({});
  const [error, setError] = useState("");

  if (!isFrontendTsEnabled()) {
    return (
      <div className="mx-auto max-w-3xl p-6 text-sm text-gray-600">
        Fidelity harness is disabled. Rebuild the frontend with
        VITE_ENABLE_FRONTEND_TS_RENDERER=1 to use this page.
      </div>
    );
  }

  const onFile = async (file: File | undefined) => {
    if (!file) return;
    try {
      setEntries(parseManifest(await file.text()));
      setError("");
    } catch (e) {
      setEntries([]);
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6">
      <h1 className="text-lg font-bold">Figure fidelity comparison (issue #110)</h1>
      <p className="text-sm text-gray-600">
        Load fidelity/manifest.json produced by scripts/build_fidelity_manifest.py, rate
        each pair, then paste the Markdown below into docs/figure-rendering-evaluation.md.
      </p>
      <input
        type="file"
        accept="application/json,.json"
        aria-label="Load manifest"
        onChange={(e) => void onFile(e.target.files?.[0])}
      />
      {error && <div className="text-sm text-red-600">{error}</div>}
      {entries.map((entry) => (
        <div key={entry.id} className="rounded border border-gray-200 p-3">
          <div className="mb-2 flex items-center gap-3 text-sm">
            <span className="font-mono">{entry.id}</span>
            <span>{entry.subject}</span>
            <span className="text-gray-500">{classifySpec(entry.spec)}</span>
            <select
              aria-label={`verdict for ${entry.id}`}
              value={verdicts[entry.id] ?? "unrated"}
              onChange={(e) =>
                setVerdicts((v) => ({ ...v, [entry.id]: e.target.value as Verdict }))
              }
              className="ml-auto rounded border border-gray-300 px-2 py-1"
            >
              <option value="unrated">unrated</option>
              <option value="match">match</option>
              <option value="minor-diff">minor-diff</option>
              <option value="broken">broken</option>
            </select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="mb-1 text-xs text-gray-500">server PNG (Playwright)</div>
              {entry.server_png_base64 ? (
                <img
                  src={`data:image/png;base64,${entry.server_png_base64}`}
                  alt={`server render of ${entry.id}`}
                  className="max-w-full rounded border border-gray-200"
                />
              ) : (
                <div className="text-xs text-red-600">no server PNG (render failed)</div>
              )}
            </div>
            <div>
              <div className="mb-1 text-xs text-gray-500">frontend TS prototype</div>
              <FigureRenderer spec={entry.spec} alt={`TS render of ${entry.id}`} />
            </div>
          </div>
        </div>
      ))}
      {entries.length > 0 && (
        <textarea
          readOnly
          aria-label="fidelity markdown"
          className="h-40 w-full rounded border border-gray-300 p-2 font-mono text-xs"
          value={toMarkdownTable(entries, verdicts)}
        />
      )}
    </div>
  );
}

import { describe, expect, it, vi, afterEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import FidelityComparePage, {
  parseManifest,
  toMarkdownTable,
  type FidelityEntry,
} from "./FidelityComparePage";

afterEach(() => {
  vi.unstubAllEnvs();
});

const tableEntry: FidelityEntry = {
  id: "q1",
  subject: "social_studies",
  category: "table",
  spec: {
    render_mode: "html",
    description: "課表",
    data: { columns: ["時段"], rows: [["9:00"]] },
  },
  server_png_base64: "aGVsbG8=",
};

describe("parseManifest", () => {
  it("parses a valid manifest array", () => {
    expect(parseManifest(JSON.stringify([tableEntry]))).toHaveLength(1);
  });

  it("throws when the manifest is not an array", () => {
    expect(() => parseManifest("{}")).toThrow("manifest must be a JSON array");
  });

  it("throws when an entry is missing id or spec", () => {
    expect(() => parseManifest(JSON.stringify([{ subject: "math" }]))).toThrow(
      "missing id or spec",
    );
  });
});

describe("toMarkdownTable", () => {
  it("renders one row per entry with shape and verdict", () => {
    const md = toMarkdownTable([tableEntry], { q1: "match" });
    expect(md).toContain("| 1 | q1 | social_studies | table | TS | match |");
  });

  it("marks unsupported specs as fallback and defaults verdict to unrated", () => {
    const entry: FidelityEntry = {
      ...tableEntry,
      id: "q2",
      spec: { render_mode: "html", description: "自由描述", data: {} },
    };
    const md = toMarkdownTable([entry], {});
    expect(md).toContain(
      "| 1 | q2 | social_studies | unsupported | fallback (PNG) | unrated |",
    );
  });
});

describe("FidelityComparePage", () => {
  it("shows the disabled note when the flag is off", () => {
    vi.stubEnv("VITE_ENABLE_FRONTEND_TS_RENDERER", "");
    render(<FidelityComparePage />);
    expect(screen.getByText(/disabled/i)).toBeInTheDocument();
  });

  it("renders side-by-side rows after loading a manifest file", async () => {
    vi.stubEnv("VITE_ENABLE_FRONTEND_TS_RENDERER", "1");
    render(<FidelityComparePage />);
    const file = new File([JSON.stringify([tableEntry])], "manifest.json", {
      type: "application/json",
    });
    fireEvent.change(screen.getByLabelText("Load manifest"), {
      target: { files: [file] },
    });
    expect(await screen.findByRole("table")).toBeInTheDocument();
    expect(screen.getByAltText("server render of q1")).toHaveAttribute(
      "src",
      "data:image/png;base64,aGVsbG8=",
    );
    expect(screen.getByLabelText("fidelity markdown")).toBeInTheDocument();
  });
});

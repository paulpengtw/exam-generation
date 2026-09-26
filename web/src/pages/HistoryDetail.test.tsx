import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

const getDetailMock = vi.hoisted(() => vi.fn());
const downloadMock = vi.hoisted(() => vi.fn());
vi.mock("../api/client", () => ({
  ApiError: class ApiError extends Error {
    detail: string;

    constructor(_status: number, detail: string) {
      super(detail);
      this.name = "ApiError";
      this.detail = detail;
    }
  },
  getHistoryDetail: getDetailMock,
  downloadHistoryJson: downloadMock,
}));

vi.mock("../components/ReferenceExampleRecordSection", () => ({
  default: ({ record }: { record?: { entries: unknown[] } | null }) => {
    if (record === undefined) return null;
    if (record === null) {
      return <div data-testid="ref-section-no-record">No reference examples were recorded.</div>;
    }
    return (
      <div data-testid="ref-section" data-entries={JSON.stringify(record.entries)}>
        ref-section
      </div>
    );
  },
}));

vi.mock("../components/QuestionCard", () => ({
  default: ({
    question,
    recordId,
    phase,
    isFinal,
    trail,
    figurePolicyTrail,
  }: {
    question: { id?: string };
    recordId?: string;
    phase?: string;
    isFinal?: boolean;
    trail?: unknown;
    figurePolicyTrail?: unknown;
  }) => (
    <div
      data-testid="qc"
      data-record-id={recordId}
      data-phase={phase}
      data-final={String(isFinal)}
      data-trail={trail === undefined ? "undefined" : JSON.stringify(trail)}
      data-figure-policy-trail={
        figurePolicyTrail === undefined ? "undefined" : JSON.stringify(figurePolicyTrail)
      }
    >
      {question?.id ?? ""}
    </div>
  ),
}));

import HistoryDetail from "./HistoryDetail";

function LocationSpy() {
  const loc = useLocation();
  return (
    <div data-testid="loc-state">{JSON.stringify(loc.state ?? null)}</div>
  );
}

describe("HistoryDetail", () => {
  it("renders the stored question and calls the download API", async () => {
    getDetailMock.mockResolvedValueOnce({
      id: "abc",
      subject: "social_studies",
      question_id: "ss_1",
      created_at: "2026-07-15T00:00:00Z",
      params_json: { subject: "social_studies", grade: 8 },
      question_json: { id: "ss_1", 核心問題: "核心" },
    });
    downloadMock.mockResolvedValueOnce(new Blob(["{}"], { type: "application/json" }));

    render(
      <MemoryRouter initialEntries={["/history/abc"]}>
        <Routes>
          <Route path="/history/:id" element={<HistoryDetail recordId="abc" />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("qc")).toHaveTextContent("ss_1"));

    fireEvent.click(screen.getByRole("button", { name: /Download JSON/i }));
    await waitFor(() => expect(downloadMock).toHaveBeenCalledWith("abc", expect.any(AbortSignal)));
  });

  it("surfaces a history JSON download failure on the pressed control", async () => {
    getDetailMock.mockResolvedValueOnce({
      id: "failed-download",
      subject: "math",
      question_id: "q-failed-download",
      created_at: "2026-07-15T00:00:00Z",
      params_json: {},
      question_json: { id: "q-failed-download" },
    });
    downloadMock.mockRejectedValueOnce(new Error("network details"));

    render(
      <MemoryRouter initialEntries={["/history/failed-download"]}>
        <Routes>
          <Route path="/history/:id" element={<HistoryDetail recordId="failed-download" />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByTestId("qc")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Download JSON/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Unable to download the JSON file.",
    );
    expect(screen.getByRole("button", { name: /Download JSON/i })).toHaveAttribute(
      "data-action-state",
      "failed",
    );
  });

  it("重新帶入 is offered for completed and aborted details and carries params", async () => {
    getDetailMock.mockResolvedValueOnce({
      id: "abc",
      subject: "social_studies",
      question_id: "ss_1",
      created_at: "2026-07-15T00:00:00Z",
      params_json: { subject: "social_studies", grade: 8, topic: "climate" },
      question_json: { id: "ss_1" },
    });

    const firstRender = render(
      <MemoryRouter initialEntries={["/history/abc"]}>
        <Routes>
          <Route path="/history/:id" element={<HistoryDetail recordId="abc" />} />
          <Route path="/generate/social_studies" element={<LocationSpy />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Reload saved parameters/i }))
        .toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /Reload saved parameters/i }));

    await waitFor(() =>
      expect(screen.getByTestId("loc-state").textContent).toContain(
        '"topic":"climate"',
      ),
    );
    firstRender.unmount();

    getDetailMock.mockResolvedValueOnce({
      id: "aborted-id",
      subject: "social_studies",
      question_id: "",
      created_at: "2026-07-16T00:00:00Z",
      status: "aborted",
      error: null,
      params_json: {
        subject: "social_studies",
        grade: 8,
        q_type: ["已停用的題型"],
        topic: "aborted climate",
        core_question: "aborted core",
        sub_question_count: 3,
        subquestion_configs: JSON.stringify([{
          question_type: "Complex multiple-choice",
          instruction: "aborted subquestion",
        }]),
        per_question_params: JSON.stringify([{
          topic: "aborted climate",
          core_question: "aborted core",
          subquestion_configs: JSON.stringify([{
            question_type: "Complex multiple-choice",
            instruction: "aborted subquestion",
          }]),
        }]),
      },
      question_json: null,
    });

    render(
      <MemoryRouter initialEntries={["/history/aborted-id"]}>
        <Routes>
          <Route
            path="/history/:id"
            element={<HistoryDetail recordId="aborted-id" />}
          />
          <Route path="/generate/social_studies" element={<LocationSpy />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Reload saved parameters/i }))
        .toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /Reload saved parameters/i }));

    await waitFor(() =>
      expect(screen.getByTestId("loc-state").textContent).toContain(
        '"topic":"aborted climate"',
      ),
    );
    expect(screen.getByTestId("loc-state").textContent).toContain(
      '"core_question":"aborted core"',
    );
    expect(screen.getByTestId("loc-state").textContent).toContain("aborted subquestion");
  });

  it("uses the latest record identity returned by history detail for the card", async () => {
    getDetailMock.mockResolvedValueOnce({
      id: "latest-id",
      subject: "social_studies",
      question_id: "ss-child",
      created_at: "2026-07-16T00:00:00Z",
      params_json: { subject: "social_studies" },
      question_json: { id: "ss-child", verification: { passed: true } },
    });

    render(
      <MemoryRouter initialEntries={["/history/old-id"]}>
        <Routes>
          <Route path="/history/:id" element={<HistoryDetail recordId="old-id" />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("qc")).toHaveAttribute("data-record-id", "latest-id");
    });
    expect(screen.getByTestId("qc")).toHaveAttribute("data-final", "true");
  });

  it("passes a persisted verification trail to the history card", async () => {
    const trail = [
      {
        code: "verification_trail",
        kind: "verification",
        question_id: "ss-child",
        passed: true,
        details: "The answer is consistent.",
        my_answer: "A",
        provided_answer: "A",
        answer_match: true,
        chart_verification: null,
        model: "verify-model",
        timestamp: "2026-08-24T00:00:00Z",
      },
    ];
    getDetailMock.mockResolvedValueOnce({
      id: "trail-id",
      subject: "social_studies",
      question_id: "ss-child",
      created_at: "2026-07-16T00:00:00Z",
      status: "completed",
      error: null,
      params_json: { subject: "social_studies" },
      question_json: { id: "ss-child" },
      verification_trail: trail,
    });

    render(
      <MemoryRouter initialEntries={["/history/trail-id"]}>
        <Routes>
          <Route path="/history/:id" element={<HistoryDetail recordId="trail-id" />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("qc")).toHaveAttribute(
        "data-trail",
        JSON.stringify(trail),
      ),
    );
  });

  it("passes a legacy null verification trail to the history card", async () => {
    getDetailMock.mockResolvedValueOnce({
      id: "legacy-id",
      subject: "social_studies",
      question_id: "ss-legacy",
      created_at: "2026-07-16T00:00:00Z",
      status: "completed",
      error: null,
      params_json: { subject: "social_studies" },
      question_json: { id: "ss-legacy" },
      verification_trail: null,
    });

    render(
      <MemoryRouter initialEntries={["/history/legacy-id"]}>
        <Routes>
          <Route path="/history/:id" element={<HistoryDetail recordId="legacy-id" />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("qc")).toHaveAttribute("data-trail", "null"),
    );
  });

  it("passes the persisted figure-policy trail to the History card", async () => {
    const trail = [
      {
        code: "figure_policy",
        kind: "spec",
        question_id: "ss-policy",
        label: "題幹",
        effective_figure_kind: "地圖",
        timestamp: "2026-08-25T00:00:00Z",
      },
    ];
    getDetailMock.mockResolvedValueOnce({
      id: "policy-id",
      subject: "social_studies",
      question_id: "ss-policy",
      created_at: "2026-07-16T00:00:00Z",
      status: "completed",
      error: null,
      params_json: { subject: "social_studies" },
      question_json: { id: "ss-policy" },
      verification_trail: null,
      figure_policy_trail: trail,
    });

    render(
      <MemoryRouter initialEntries={["/history/policy-id"]}>
        <Routes>
          <Route path="/history/:id" element={<HistoryDetail recordId="policy-id" />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("qc")).toHaveAttribute(
        "data-figure-policy-trail",
        JSON.stringify(trail),
      ),
    );
  });

  it("keeps the downloaded question JSON free of verification trail fields", async () => {
    getDetailMock.mockResolvedValueOnce({
      id: "download-id",
      subject: "social_studies",
      question_id: "ss-download",
      created_at: "2026-07-16T00:00:00Z",
      status: "completed",
      error: null,
      params_json: { subject: "social_studies" },
      question_json: { id: "ss-download" },
      verification_trail: [
        {
          code: "verification_trail",
          kind: "verification",
          question_id: "ss-download",
          passed: true,
          details: "The answer is consistent.",
          my_answer: "A",
          provided_answer: "A",
          answer_match: true,
          chart_verification: null,
          model: "verify-model",
          timestamp: "2026-08-24T00:00:00Z",
        },
      ],
    });
    const downloadedQuestion = {
      id: "ss-download",
      題目: ["Question"],
      params_json: { subject: "social_studies" },
    };
    downloadMock.mockResolvedValueOnce(
      new Blob([JSON.stringify(downloadedQuestion)], { type: "application/json" }),
    );
    const blobs: Blob[] = [];
    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockImplementation((blob: Blob) => {
        blobs.push(blob);
        return "blob:history-download";
      });
    const revokeObjectURL = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);

    try {
      render(
        <MemoryRouter initialEntries={["/history/download-id"]}>
          <Routes>
            <Route
              path="/history/:id"
              element={<HistoryDetail recordId="download-id" />}
            />
          </Routes>
        </MemoryRouter>,
      );

      await waitFor(() => expect(screen.getByTestId("qc")).toBeInTheDocument());
      fireEvent.click(screen.getByRole("button", { name: /Download JSON/i }));

      await waitFor(() => expect(blobs).toHaveLength(1));
      const body = JSON.parse(await blobs[0].text()) as Record<string, unknown>;
      expect(body).not.toHaveProperty("verification_trail");
      expect(body).not.toHaveProperty("verification_trail_json");
      expect(body).not.toHaveProperty("correction_trail");
    } finally {
      createObjectURL.mockRestore();
      revokeObjectURL.mockRestore();
    }
  });

  it("renders failed detail params and error without question content or download", async () => {
    getDetailMock.mockResolvedValueOnce({
      id: "failed-id",
      subject: "social_studies",
      question_id: "",
      created_at: "2026-07-16T00:00:00Z",
      status: "failed",
      error: "Question generation failed (RuntimeError)",
      params_json: { subject: "social_studies", topic: "climate" },
      question_json: null,
    });

    render(
      <MemoryRouter initialEntries={["/history/failed-id"]}>
        <Routes>
          <Route
            path="/history/:id"
            element={<HistoryDetail recordId="failed-id" />}
          />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(
        screen.getByText("Question generation failed (RuntimeError)"),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText(/"topic": "climate"/)).toBeInTheDocument();
    expect(screen.queryByTestId("qc")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Download JSON/i }),
    ).not.toBeInTheDocument();
  });

  it("renders an aborted explanation and params without question content or download", async () => {
    getDetailMock.mockResolvedValueOnce({
      id: "aborted-id",
      subject: "social_studies",
      question_id: "",
      created_at: "2026-07-16T00:00:00Z",
      status: "aborted",
      error: null,
      params_json: { subject: "social_studies", topic: "climate" },
      question_json: null,
    });

    render(
      <MemoryRouter initialEntries={["/history/aborted-id"]}>
        <Routes>
          <Route
            path="/history/:id"
            element={<HistoryDetail recordId="aborted-id" />}
          />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(
        screen.getByText("This generation was ended by the user."),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText(/"topic": "climate"/)).toBeInTheDocument();
    expect(
      screen.queryByText("The generation ended without an error message."),
    ).not.toBeInTheDocument();
    expect(screen.queryByTestId("qc")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Download JSON/i }),
    ).not.toBeInTheDocument();
  });

  it("renders ReferenceExampleRecordSection in the failed panel when a partial record is present", async () => {
    const partialRecord = {
      disabled: false,
      entries: [
        {
          code: "reference_example",
          kind: "example",
          question_id: "ss-fail",
          stage: "generator",
          slot: null,
          description: "partial entry",
          source: "/some/path",
          timestamp: "2026-09-10T00:00:00Z",
        },
      ],
    };
    getDetailMock.mockResolvedValueOnce({
      id: "failed-with-record",
      subject: "social_studies",
      question_id: "",
      created_at: "2026-09-10T00:00:00Z",
      status: "failed",
      error: "generation failed",
      params_json: { subject: "social_studies" },
      question_json: null,
      reference_example_record: partialRecord,
    });

    render(
      <MemoryRouter initialEntries={["/history/failed-with-record"]}>
        <Routes>
          <Route
            path="/history/:id"
            element={<HistoryDetail recordId="failed-with-record" />}
          />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("ref-section")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("ref-section")).toHaveAttribute(
      "data-entries",
      JSON.stringify(partialRecord.entries),
    );
  });

  it("shows no-record message in the aborted panel when reference_example_record is null", async () => {
    getDetailMock.mockResolvedValueOnce({
      id: "aborted-no-record",
      subject: "social_studies",
      question_id: "",
      created_at: "2026-09-10T00:00:00Z",
      status: "aborted",
      error: null,
      params_json: { subject: "social_studies" },
      question_json: null,
      reference_example_record: null,
    });

    render(
      <MemoryRouter initialEntries={["/history/aborted-no-record"]}>
        <Routes>
          <Route
            path="/history/:id"
            element={<HistoryDetail recordId="aborted-no-record" />}
          />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("ref-section-no-record")).toBeInTheDocument(),
    );
    expect(
      screen.getByText("No reference examples were recorded."),
    ).toBeInTheDocument();
  });

  it("marks a persisted figure-policy degradation on the history detail", async () => {
    getDetailMock.mockResolvedValueOnce({
      id: "degraded-id",
      subject: "social_studies",
      question_id: "ss-child",
      created_at: "2026-07-16T00:00:00Z",
      status: "completed",
      error: null,
      params_json: { subject: "social_studies" },
      question_json: { id: "ss-child" },
      figure_policy_trail: [
        {
          code: "figure_policy",
          kind: "warning",
          question_id: "ss-child",
          message: "duplicate shipped",
          duplicate_image_shipped: true,
          left: "題幹",
          right: "小題 1",
          effective_figure_kind: "地圖",
          timestamp: "2026-08-24T00:00:00Z",
        },
      ],
    });

    render(
      <MemoryRouter initialEntries={["/history/degraded-id"]}>
        <Routes>
          <Route path="/history/:id" element={<HistoryDetail recordId="degraded-id" />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(screen.getByText("Figure-kind diversity degraded")).toBeInTheDocument(),
    );
  });
});

import { act } from "@testing-library/react";
import { resetWorkspaceStoreForTests, useWorkspaceStore } from "../lib/workspace/workspaceStore";

describe("HistoryDetail workspace readiness", () => {
  it.each([true, false])("becomes ready after loading succeeds=%s and rehydrates for another record", async (success) => {
    resetWorkspaceStoreForTests();
    let resolve!: (value: unknown) => void;
    let reject!: (error: Error) => void;
    getDetailMock.mockReturnValueOnce(new Promise((yes, no) => { resolve = yes; reject = no; }));
    const { rerender, unmount } = render(<MemoryRouter><HistoryDetail recordId="first" /></MemoryRouter>);
    expect(useWorkspaceStore.getState().surfaces["history.detail"]).toMatchObject({
      readiness: "hydrating", hasEditableState: false, hasReceivedResults: false,
    });
    await act(async () => {
      if (success) resolve({ id: "first", subject: "math", question_json: { id: "q1" }, params_json: {} });
      else reject(new Error("load failed"));
    });
    expect(useWorkspaceStore.getState().surfaces["history.detail"]?.readiness).toBe("ready");
    getDetailMock.mockReturnValueOnce(new Promise((yes) => { resolve = yes; }));
    rerender(<MemoryRouter><HistoryDetail recordId="second" /></MemoryRouter>);
    expect(useWorkspaceStore.getState().surfaces["history.detail"]?.readiness).toBe("hydrating");
    await act(async () => { resolve({ id: "second", subject: "math", question_json: { id: "q2" }, params_json: {} }); });
    expect(useWorkspaceStore.getState().surfaces["history.detail"]?.readiness).toBe("ready");
    unmount();
    expect(useWorkspaceStore.getState().surfaces["history.detail"]).toBeUndefined();
  });
});

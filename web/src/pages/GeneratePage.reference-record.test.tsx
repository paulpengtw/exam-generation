import { act, render, screen } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@sentry/react", () => ({
  captureException: vi.fn(),
}));

vi.mock("../sentry", () => ({ isSentryEnabled: () => false }));

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

vi.mock("../store/authStore", () => ({
  useAuthStore: {
    getState: () => ({ token: null, logout: vi.fn() }),
  },
}));

import QuestionCard from "../components/QuestionCard";
import { useGenerate } from "../hooks/useGenerate";
import type { GenerateParams } from "../hooks/useGenerate";
import { installFakeRunServer, type FakeRunServer } from "../test/fakeRunServer";
import { endedQuestion, runSnapshot } from "../test/runFixtures";

const question = {
  id: "ref-live",
  情境: [],
  題型種類: "題組題",
  題型: "選擇題",
  核心問題: "核心問題",
  文本: "文本",
  subquestions: [],
  題目: ["題目"],
  正確解題分析: ["解析"],
};

const refEntry1 = {
  code: "reference_example" as const,
  kind: "example" as const,
  question_id: "ref-live",
  stage: "generator",
  slot: null,
  description: "first ref example",
  source: "/some/path/few_shot_1.json",
  timestamp: "2026-09-10T00:00:00Z",
};

const refEntry2 = {
  code: "reference_example" as const,
  kind: "example" as const,
  question_id: "ref-live",
  stage: "generator",
  slot: 2,
  description: "second ref example",
  source: "/some/path/few_shot_2.json",
  timestamp: "2026-09-10T00:01:00Z",
};

interface LiveResultCardProps {
  params?: Partial<GenerateParams>;
}

function LiveResultCard({ params = {} }: LiveResultCardProps) {
  const { displayResults, generate } = useGenerate();

  useEffect(() => {
    generate({ subject: "social_studies", count: 1, ...params });
  }, [generate]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      {displayResults.map((item) => (
        <QuestionCard
          key={item.question.id ?? item.index}
          question={item.question}
          phase={item.phase}
          isFinal={item.isFinal}
          trail={item.trail}
          figurePolicyTrail={item.figurePolicyTrail}
          referenceExampleRecord={item.referenceExampleRecord ?? undefined}
        />
      ))}
    </>
  );
}

let server: FakeRunServer;

beforeEach(() => {
  vi.useFakeTimers();
  server = installFakeRunServer();
  server.setAcceptance({
    run_id: "run-1",
    protocol_version: 3,
    total: 1,
    questions: [{ index: 0, question_id: "ref-live" }],
  });
});

afterEach(() => {
  server.restore();
  vi.useRealTimers();
});

async function flush(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
  });
}

// The persisted record arrives with the polled result: there is no in-progress
// draft stage any more (a run is read from its saved state, not streamed), so
// the "in-progress" line and live count updates of the SSE era do not exist.
describe("live generation reference-record surfacing", () => {
  it("shows the persisted reference examples on the result card once the run ends", async () => {
    const ended = endedQuestion("ref-live", { question });
    ended.result!.reference_example_record = { disabled: false, entries: [refEntry1, refEntry2] };
    server.setSnapshot("run-1", runSnapshot([ended]));
    render(<LiveResultCard />);
    await flush();
    expect(server.submits()).toHaveLength(1);
    // Not yet: the run has not been read back.
    expect(screen.queryByTestId("ref-record-counts")).not.toBeInTheDocument();

    await flush(3_000);

    const btn = screen.getByRole("button", {
      name: "Show reference examples used during generation",
    });
    expect(btn).toBeInTheDocument();
    expect(screen.getByTestId("ref-record-counts")).toHaveTextContent("2 entries");
  });

  it("disabled run shows the disabled line on the final card", async () => {
    const ended = endedQuestion("ref-live", { question });
    ended.result!.reference_example_record = { disabled: true, entries: [] };
    server.setSnapshot("run-1", runSnapshot([ended]));
    render(<LiveResultCard params={{ disable_reference_fewshot: true }} />);
    await flush();
    await flush(3_000);

    expect(screen.getByText("Reference examples were turned off for this run.")).toBeInTheDocument();
  });

  it("a result without a stored record still renders its card", async () => {
    server.setSnapshot("run-1", runSnapshot([endedQuestion("ref-live", { question })]));
    render(<LiveResultCard />);
    await flush();
    await flush(3_000);

    expect(screen.getByTestId("question-card-content")).toBeInTheDocument();
  });
});

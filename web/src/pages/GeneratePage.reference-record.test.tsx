import type { FetchEventSourceInit } from "@microsoft/fetch-event-source";
import { act, render, screen, waitFor } from "@testing-library/react";
import { useEffect } from "react";
import { describe, expect, it, vi } from "vitest";

const fetchEventSourceMock = vi.hoisted(() => vi.fn().mockResolvedValue(undefined));

vi.mock("@microsoft/fetch-event-source", () => ({
  fetchEventSource: fetchEventSourceMock,
}));

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

function latestStreamOptions(): FetchEventSourceInit {
  const call = fetchEventSourceMock.mock.lastCall;
  if (!call) throw new Error("Expected the generation stream to open");
  return call[1] as FetchEventSourceInit;
}

describe("live generation reference-record surfacing", () => {
  it("shows in-progress line on draft, updates count on trail events, preserves section on result", async () => {
    fetchEventSourceMock.mockClear();
    render(<LiveResultCard />);
    await waitFor(() => expect(fetchEventSourceMock).toHaveBeenCalledOnce());

    // Emit question_update (draft)
    act(() => {
      latestStreamOptions().onmessage?.({
        id: "",
        event: "question_update",
        data: JSON.stringify({ index: 0, phase: "draft", question }),
      });
    });

    // Draft card shows in-progress line
    await screen.findByText("No reference example drawn yet (generation in progress).");

    // Send two reference_example trail events
    act(() => {
      latestStreamOptions().onmessage?.({
        id: "",
        event: "trail",
        data: JSON.stringify(refEntry1),
      });
      latestStreamOptions().onmessage?.({
        id: "",
        event: "trail",
        data: JSON.stringify(refEntry2),
      });
    });

    // After two entries, draft card should show count toggle button (still in-progress / collapsed)
    await waitFor(() => {
      const btn = screen.queryByRole("button", {
        name: "Show reference examples used during generation",
      });
      expect(btn).toBeInTheDocument();
      expect(btn?.textContent).toBe("2");
    });

    // Emit result (final)
    act(() => {
      latestStreamOptions().onmessage?.({
        id: "",
        event: "result",
        data: JSON.stringify(question),
      });
    });

    // Final card still has section with count
    await waitFor(() => {
      const btn = screen.queryByRole("button", {
        name: "Show reference examples used during generation",
      });
      expect(btn).toBeInTheDocument();
      expect(btn?.textContent).toBe("2");
    });
  });

  it("disabled run shows disabled line on draft and final cards", async () => {
    fetchEventSourceMock.mockClear();
    render(<LiveResultCard params={{ disable_reference_fewshot: true }} />);
    await waitFor(() => expect(fetchEventSourceMock).toHaveBeenCalledOnce());

    // Emit question_update (draft)
    act(() => {
      latestStreamOptions().onmessage?.({
        id: "",
        event: "question_update",
        data: JSON.stringify({ index: 0, phase: "draft", question }),
      });
    });

    // Draft card shows disabled line
    await screen.findByText("Reference examples were turned off for this run.");

    // Emit result (final)
    act(() => {
      latestStreamOptions().onmessage?.({
        id: "",
        event: "result",
        data: JSON.stringify(question),
      });
    });

    // Final card still shows disabled line
    await screen.findByText("Reference examples were turned off for this run.");
  });
});

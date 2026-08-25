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

vi.mock("../sentry", () => ({
  isSentryEnabled: () => false,
}));

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

const question = {
  id: "ss-live-policy",
  情境: [],
  題型種類: "題組題",
  題型: "選擇題",
  核心問題: "核心問題",
  文本: "文本",
  subquestions: [],
  題目: ["題目"],
  正確解題分析: ["解析"],
};

const warning = {
  code: "figure_policy" as const,
  kind: "warning" as const,
  question_id: "ss-live-policy",
  message: "duplicate image shipped",
  duplicate_image_shipped: true,
  left: "題幹",
  right: "小題 1",
  effective_figure_kind: "地圖",
  timestamp: "2026-08-25T00:00:00+00:00",
};

function LiveResultCard() {
  const { displayResults, generate } = useGenerate();

  useEffect(() => {
    generate({ subject: "social_studies", count: 1 });
  }, [generate]);

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

describe("live generation result figure-policy surfacing", () => {
  it("renders the persisted warning in the result card after the trail event arrives", async () => {
    fetchEventSourceMock.mockClear();
    render(<LiveResultCard />);
    await waitFor(() => expect(fetchEventSourceMock).toHaveBeenCalledOnce());

    act(() => {
      latestStreamOptions().onmessage?.({
        id: "",
        event: "result",
        data: JSON.stringify(question),
      });
      latestStreamOptions().onmessage?.({
        id: "",
        event: "trail",
        data: JSON.stringify(warning),
      });
    });

    const banner = await screen.findByRole("alert", {
      name: "Figure-kind degradation warning",
    });
    expect(banner).toHaveTextContent("題幹");
    expect(banner).toHaveTextContent("小題 1");
    expect(banner).toHaveTextContent("地圖");
  });
});

import { act, render, screen } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
import { installFakeRunServer, type FakeRunServer } from "../test/fakeRunServer";
import { endedQuestion, runSnapshot } from "../test/runFixtures";

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

let server: FakeRunServer;

beforeEach(() => {
  vi.useFakeTimers();
  server = installFakeRunServer();
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

describe("live generation result figure-policy surfacing", () => {
  it("renders the persisted warning in the result card once the polled result carries its trail", async () => {
    const ended = endedQuestion("ss-live-policy", { question });
    ended.result!.figure_policy_trail = [warning];
    server.setSnapshot("run-1", runSnapshot([ended]));
    server.setAcceptance({
      run_id: "run-1",
      protocol_version: 3,
      total: 1,
      questions: [{ index: 0, question_id: "ss-live-policy" }],
    });
    render(<LiveResultCard />);
    await flush();
    expect(server.submits()).toHaveLength(1);
    await flush(3_000);

    const banner = screen.getByRole("alert", {
      name: "Figure-kind degradation warning",
    });
    expect(banner).toHaveTextContent("題幹");
    expect(banner).toHaveTextContent("小題 1");
    expect(banner).toHaveTextContent("地圖");
  });
});

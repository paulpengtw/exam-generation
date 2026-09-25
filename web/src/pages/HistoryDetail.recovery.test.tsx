import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FetchEventSourceInit } from "@microsoft/fetch-event-source";
import { ApiError, type HistoryDetail as HistoryDetailPayload } from "../api/client";
import type { ExamQuestion } from "../hooks/useGenerate";
import { useAuthStore } from "../store/authStore";
import { useReleaseStore } from "../lib/release/releaseStore";
import { resetRecoveryStoreForTests, useRecoveryStore } from "../lib/recovery/recoveryStore";
import { loadSnapshot, loadTabPointer } from "../lib/recovery/storage";
import { runSaveAndUpdate } from "../lib/recovery/saveAndUpdate";
import { resetWorkspaceStoreForTests, useWorkspaceStore } from "../lib/workspace/workspaceStore";
import { canonicalQuestionIdentity } from "../lib/workspace/adapters/modificationWorkspace";
import ReleaseNotice from "../components/ReleaseNotice";

vi.stubGlobal("__BUILD_ID__", "build-A");
vi.stubGlobal("__BUILD_ENVIRONMENT__", "production");

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) => selector({ lang: "en-US" }),
}));

const getDetailMock = vi.hoisted(() => vi.fn());
const fetchMock = vi.hoisted(() => vi.fn());
const fetchEventSourceMock = vi.hoisted(() => vi.fn());

vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, getHistoryDetail: getDetailMock };
});
vi.mock("@microsoft/fetch-event-source", () => ({ fetchEventSource: fetchEventSourceMock }));

import HistoryDetail from "./HistoryDetail";

const route = "/history/record-1";
const user = { id: "user-1", email: "teacher@example.com", created_at: "2026-01-01T00:00:00Z" };

const originalQuestion: ExamQuestion = {
  id: "question-1",
  情境: [],
  題型種類: "單一題",
  題型: "選擇題",
  題目: ["A passage that can be selected twice"],
  正確解題分析: ["Answer"],
  verification: { passed: true },
};

const replacementQuestion: ExamQuestion = {
  ...originalQuestion,
  題目: ["A settled replacement passage"],
};

function historyPayload(
  overrides: Partial<HistoryDetailPayload> = {},
): HistoryDetailPayload {
  return {
    id: "record-1",
    subject: "math",
    question_id: "question-1",
    created_at: "2026-09-17T00:00:00Z",
    status: "completed",
    error: null,
    generation_log_id: null,
    params_json: { subject: "math" },
    question_json: originalQuestion as unknown as Record<string, unknown>,
    verification_trail: null,
    figure_policy_trail: null,
    reference_example_record: null,
    ...overrides,
  };
}

function renderPage() {
  window.history.replaceState({}, "", route);
  return render(
    <MemoryRouter initialEntries={[route]}>
      <ReleaseNotice />
      <Routes>
        <Route path="/history/:id" element={<HistoryDetail recordId="record-1" />} />
      </Routes>
    </MemoryRouter>,
  );
}

function setReleaseUpdateRequired() {
  useReleaseStore.setState({
    status: "update-required",
    requiredBuildId: "build-B",
    releaseRevision: 2,
    supportedRecoveryFormats: ["exam-generation.recovery/1"],
    checkNow: vi.fn().mockResolvedValue(undefined),
  });
}

function selectText(start: number, end: number) {
  const field = screen.getByText("A passage that can be selected twice", { exact: true });
  const textNode = field.firstChild;
  if (!(textNode instanceof Text)) throw new Error("Expected passage text node");
  const range = document.createRange();
  range.setStart(textNode, start);
  range.setEnd(textNode, end);
  const selection = window.getSelection();
  if (!selection) throw new Error("jsdom did not provide a Selection");
  selection.removeAllRanges();
  selection.addRange(range);
  fireEvent.mouseUp(field);
}

async function saveCurrentWorkspace() {
  const navigation = vi.fn();
  let result: Awaited<ReturnType<typeof runSaveAndUpdate>>;
  await act(async () => {
    result = await runSaveAndUpdate({
      navigate: navigation,
      now: () => Date.parse("2026-09-17T12:00:00Z"),
      origin: window.location.origin,
      environment: "production",
      buildId: "build-A",
    });
  });
  expect(result.ok).toBe(true);
  expect(navigation).toHaveBeenCalledOnce();
  return result;
}

beforeEach(() => {
  vi.stubGlobal("__BUILD_ID__", "build-A");
  vi.stubGlobal("__BUILD_ENVIRONMENT__", "production");
  localStorage.clear();
  sessionStorage.clear();
  resetRecoveryStoreForTests();
  resetWorkspaceStoreForTests();
  getDetailMock.mockReset().mockResolvedValue(historyPayload());
  fetchMock.mockReset();
  fetchEventSourceMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  useAuthStore.setState({ token: "token", user });
  useReleaseStore.setState({
    status: "checking",
    requiredBuildId: null,
    releaseRevision: null,
    lastCheckedAt: null,
    lastFailure: null,
    supportedRecoveryFormats: [],
  });
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  useAuthStore.setState({ token: null, user: null });
  resetRecoveryStoreForTests();
  resetWorkspaceStoreForTests();
});

describe("HistoryDetail modification recovery", () => {
  it("saves multiple unsent selections and instructions from the real History card", async () => {
    getDetailMock.mockResolvedValueOnce(historyPayload());
    setReleaseUpdateRequired();
    renderPage();

    await waitFor(() => expect(screen.getByText("A passage that can be selected twice")).toBeInTheDocument());
    selectText(2, 9);
    selectText(10, 16);
    fireEvent.change(screen.getByRole("textbox", { name: "Modification instruction 1" }), {
      target: { value: "Fix the first selection" },
    });
    fireEvent.change(screen.getByRole("textbox", { name: "Modification instruction 2" }), {
      target: { value: "Clarify the second selection" },
    });

    const save = screen.getByRole("button", { name: "Save Draft & Update" });
    expect(save).not.toBeDisabled();
    await saveCurrentWorkspace();

    const pointer = loadTabPointer();
    expect(pointer).not.toBeNull();
    const saved = loadSnapshot(pointer!.account_id, pointer!.snapshot_id);
    expect(saved?.form).toEqual({ kind: "form", version: 1, fields: {} });
    expect(saved?.modification).toMatchObject({
      route,
      recordId: "record-1",
      questionId: "question-1",
      contentIdentity: canonicalQuestionIdentity(originalQuestion),
      annotations: [
        { instruction: "Fix the first selection" },
        { instruction: "Clarify the second selection" },
      ],
    });
  });

  it("captures a settled replacement and restores it without replaying the modification run", async () => {
    getDetailMock.mockResolvedValueOnce(historyPayload());
    setReleaseUpdateRequired();
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ run_id: "run-1", status: "accepted" }), { status: 200 }),
    );
    fetchEventSourceMock.mockImplementationOnce(async (_url: string, init: FetchEventSourceInit) => {
      init.onmessage?.({
        id: "",
        event: "done",
        data: JSON.stringify({
          record_id: "record-2",
          question: replacementQuestion,
          ripple_report: ["題目[0]"],
          verified: true,
          verification: { passed: true },
          failure_details: null,
        }),
      });
    });

    const first = renderPage();
    await waitFor(() => expect(screen.getByText("A passage that can be selected twice")).toBeInTheDocument());
    selectText(2, 9);
    fireEvent.change(screen.getByRole("textbox", { name: "Modification instruction 1" }), {
      target: { value: "Fix this passage" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit modifications" }));
    await waitFor(() => expect(screen.getByText("A settled replacement passage")).toBeInTheDocument());

    await saveCurrentWorkspace();
    const pointer = loadTabPointer();
    const saved = loadSnapshot(pointer!.account_id, pointer!.snapshot_id);
    expect(saved?.modification).toMatchObject({
      recordId: "record-2",
      contentIdentity: canonicalQuestionIdentity(replacementQuestion),
      replacement: { record_id: "record-2", question: replacementQuestion },
    });

    first.unmount();
    resetWorkspaceStoreForTests();
    fetchMock.mockReset();
    fetchEventSourceMock.mockReset();
    getDetailMock.mockReset().mockResolvedValue(historyPayload({
      id: "record-2",
      question_id: "question-1",
      question_json: replacementQuestion as unknown as Record<string, unknown>,
    }));

    render(
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/history/:id" element={<HistoryDetail recordId="record-2" />} />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText("A settled replacement passage")).toBeInTheDocument());
    expect(screen.queryByRole("textbox", { name: "Modification instruction 1" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Submit modifications" })).toBeDisabled();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(fetchEventSourceMock).not.toHaveBeenCalled();
    expect(useRecoveryStore.getState().pending).not.toBeNull();
  });

  it("keeps Save Draft & Update disabled while the modification stream is active", async () => {
    let releaseStream!: () => void;
    const streamGate = new Promise<void>((resolve) => {
      releaseStream = resolve;
    });
    getDetailMock.mockResolvedValueOnce(historyPayload());
    setReleaseUpdateRequired();
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ run_id: "run-1", status: "accepted" }), { status: 200 }),
    );
    fetchEventSourceMock.mockImplementationOnce(async () => {
      await streamGate;
    });

    renderPage();
    await waitFor(() => expect(screen.getByText("A passage that can be selected twice")).toBeInTheDocument());
    selectText(2, 9);
    fireEvent.change(screen.getByRole("textbox", { name: "Modification instruction 1" }), {
      target: { value: "Fix this passage" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit modifications" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Submitting…" })).toBeDisabled());
    expect(screen.getByRole("button", { name: "Save Draft & Update" })).toBeDisabled();
    expect(useWorkspaceStore.getState().operations).toEqual([
      expect.objectContaining({ kind: "modification", surface: "history.modification" }),
    ]);

    await act(async () => {
      releaseStream();
    });
  });

  it("restores an unsent draft and enables it only after the exact base is checked", async () => {
    getDetailMock.mockResolvedValueOnce(historyPayload());
    setReleaseUpdateRequired();
    const first = renderPage();
    await waitFor(() => expect(screen.getByText("A passage that can be selected twice")).toBeInTheDocument());
    selectText(2, 9);
    fireEvent.change(screen.getByRole("textbox", { name: "Modification instruction 1" }), {
      target: { value: "Fix this passage" },
    });
    await saveCurrentWorkspace();

    first.unmount();
    resetWorkspaceStoreForTests();
    getDetailMock.mockReset().mockResolvedValue(historyPayload());
    render(
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/history/:id" element={<HistoryDetail recordId="record-1" />} />
        </Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByRole("textbox", { name: "Modification instruction 1" })).toHaveValue("Fix this passage"));
    expect(screen.getByRole("textbox", { name: "Modification instruction 1" })).not.toBeDisabled();
    expect(screen.getByRole("button", { name: "Submit modifications" })).not.toBeDisabled();
    expect(useRecoveryStore.getState().pending).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Acknowledge" }));
    expect(useRecoveryStore.getState().pending).toBeNull();
    expect(screen.getByRole("textbox", { name: "Modification instruction 1" })).toHaveValue("Fix this passage");
  });

  it.each([
    ["changed version", historyPayload({ id: "record-3" }), "This History record now points to a different version."],
    ["changed content", historyPayload({ question_json: { ...originalQuestion, 題目: ["Changed content"] } }), "The saved question content or revision changed."],
    ["changed content revision", historyPayload({ question_json: { ...originalQuestion, content_revision: 2 } }), "The saved question content or revision changed."],
  ])("blocks restored submission after a %s", async (_label, currentDetail, message) => {
    getDetailMock.mockResolvedValueOnce(historyPayload());
    setReleaseUpdateRequired();
    const first = renderPage();
    await waitFor(() => expect(screen.getByText("A passage that can be selected twice")).toBeInTheDocument());
    selectText(2, 9);
    fireEvent.change(screen.getByRole("textbox", { name: "Modification instruction 1" }), {
      target: { value: "Fix this passage" },
    });
    await saveCurrentWorkspace();

    first.unmount();
    resetWorkspaceStoreForTests();
    getDetailMock.mockReset().mockResolvedValue(currentDetail);
    render(
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/history/:id" element={<HistoryDetail recordId={currentDetail.id} />} />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(message));
    expect(screen.getByRole("textbox", { name: "Modification instruction 1" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Submit modifications" })).toBeDisabled();
    expect(useRecoveryStore.getState().pending).not.toBeNull();
  });

  it.each([401, 403, 404])("blocks an unauthorized base (%s) while keeping the snapshot", async (status) => {
    getDetailMock.mockResolvedValueOnce(historyPayload());
    setReleaseUpdateRequired();
    const first = renderPage();
    await waitFor(() => expect(screen.getByText("A passage that can be selected twice")).toBeInTheDocument());
    selectText(2, 9);
    fireEvent.change(screen.getByRole("textbox", { name: "Modification instruction 1" }), {
      target: { value: "Fix this passage" },
    });
    await saveCurrentWorkspace();

    first.unmount();
    resetWorkspaceStoreForTests();
    getDetailMock.mockReset().mockRejectedValue(new ApiError(status, "Forbidden"));
    render(
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/history/:id" element={<HistoryDetail recordId="record-1" />} />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("This History record is unavailable or you are no longer authorized to access it."));
    expect(loadTabPointer()).not.toBeNull();
    expect(useRecoveryStore.getState().pending).not.toBeNull();
  });

  it("keeps the live History workspace and snapshot when storage rejects the save", async () => {
    getDetailMock.mockResolvedValueOnce(historyPayload());
    setReleaseUpdateRequired();
    renderPage();
    await waitFor(() => expect(screen.getByText("A passage that can be selected twice")).toBeInTheDocument());
    selectText(2, 9);
    fireEvent.change(screen.getByRole("textbox", { name: "Modification instruction 1" }), {
      target: { value: "Fix this passage" },
    });
    vi.spyOn(localStorage, "setItem").mockImplementationOnce(() => {
      throw new DOMException("quota", "QuotaExceededError");
    });

    let result: Awaited<ReturnType<typeof runSaveAndUpdate>>;
    await act(async () => {
      result = await runSaveAndUpdate({ navigate: vi.fn(), origin: window.location.origin, environment: "production", buildId: "build-A" });
    });
    expect(result).toMatchObject({ ok: false, reason: "quota" });
    expect(screen.getByRole("textbox", { name: "Modification instruction 1" })).toHaveValue("Fix this passage");
    expect(loadTabPointer()).toBeNull();
  });

  it("keeps the snapshot when History restore fails and retries without replay", async () => {
    getDetailMock.mockResolvedValueOnce(historyPayload());
    setReleaseUpdateRequired();
    const first = renderPage();
    await waitFor(() => expect(screen.getByText("A passage that can be selected twice")).toBeInTheDocument());
    selectText(2, 9);
    fireEvent.change(screen.getByRole("textbox", { name: "Modification instruction 1" }), {
      target: { value: "Fix this passage" },
    });
    await saveCurrentWorkspace();

    first.unmount();
    resetWorkspaceStoreForTests();
    getDetailMock.mockReset()
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValueOnce(historyPayload());
    render(
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/history/:id" element={<HistoryDetail recordId="record-1" />} />
        </Routes>
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("The saved History version could not be checked. Your draft is kept; retry when the History service is available."));
    expect(loadTabPointer()).not.toBeNull();
    expect(useRecoveryStore.getState().pending).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry check" }));
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Modification instruction 1" })).toHaveValue("Fix this passage"));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(fetchEventSourceMock).not.toHaveBeenCalled();
    expect(useRecoveryStore.getState().pending).not.toBeNull();
  });
});

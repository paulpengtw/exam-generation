import type { FetchEventSourceInit } from "@microsoft/fetch-event-source";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter, Outlet, RouteObject, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ExamQuestion, GeneratedQuestion } from "../hooks/useGenerate";
import { useAuthStore } from "../store/authStore";
import { ReleaseState, useReleaseStore } from "../lib/release/releaseStore";
import { RECOVERY_FORMAT_V1 } from "../lib/recovery/format";
import {
  initRecoveryStore,
  resetRecoveryStoreForTests,
  useRecoveryStore,
} from "../lib/recovery/recoveryStore";
import {
  getOrCreateTabId,
  loadSnapshot,
  loadTabPointer,
  persistTabPointer,
  saveSnapshotTransactionally,
} from "../lib/recovery/storage";
import { resetWorkspaceStoreForTests, useWorkspaceStore } from "../lib/workspace/workspaceStore";
import type {
  FormWorkspaceSnapshot,
  ResultsWorkspaceSnapshot,
} from "../lib/workspace/adapters/types";
import ReleaseNotice from "../components/ReleaseNotice";
import QuestionCard from "../components/QuestionCard";
import GeneratePage from "./GeneratePage";

const fetchEventSourceMock = vi.hoisted(() =>
  vi.fn<(input: RequestInfo, init: FetchEventSourceInit) => Promise<void>>(),
);
const buildExamOdtMock = vi.hoisted(() => vi.fn<(title: string, questions: ExamQuestion[]) => Promise<Blob>>());

vi.mock("@microsoft/fetch-event-source", () => ({
  fetchEventSource: fetchEventSourceMock,
}));
vi.mock("../utils/odt", () => ({
  buildExamOdt: buildExamOdtMock,
  formatTimestamp: () => "recovery-test",
}));

// Keep the form surface real to the save-and-update controller while giving the
// active-generation scenario a deterministic UI action that starts the real
// useGenerate hook. Results and QuestionCard are intentionally not mocked.
vi.mock("../components/ParamForm", async () => {
  const { useSurfaceParticipation } = await vi.importActual<typeof import("../lib/workspace/useSurfaceParticipation")>(
    "../lib/workspace/useSurfaceParticipation",
  );
  const formSnapshot: FormWorkspaceSnapshot = {
    kind: "form",
    version: 1,
    fields: {} as FormWorkspaceSnapshot["fields"],
  };

  function RecoveryTestForm({
    onSubmit,
  }: {
    onSubmit: (params: Record<string, unknown>) => Promise<unknown> | undefined;
  }) {
    useSurfaceParticipation("generate.form", {
      readiness: "ready",
      hasEditableState: false,
      hasReceivedResults: false,
      exportWorkspace: () => formSnapshot,
    });
    return (
      <button
        type="button"
        onClick={() => {
          void onSubmit({
            grade: 7,
            count: 1,
            context: [],
            q_type: [],
            set_type: "單一題",
            image_generation_mode: "html",
            skip_verify: false,
          });
        }}
      >
        Start generation
      </button>
    );
  }

  return { default: RecoveryTestForm };
});

vi.stubGlobal("__BUILD_ID__", "build-B");
vi.stubGlobal("__BUILD_ENVIRONMENT__", "production");

const USER = { id: "u1", email: "u@test.com", created_at: "2024-01-01T00:00:00Z" };
const ROUTE = "/generate/math";
const PNG_BYTES = "aW1hZ2UtYnl0ZXM=";

const FORM: FormWorkspaceSnapshot = {
  kind: "form",
  version: 1,
  fields: {} as FormWorkspaceSnapshot["fields"],
};

function finalQuestion(id?: string): ExamQuestion {
  return {
    ...(id ? { id } : {}),
    情境: [],
    題型種類: "single",
    題型: "choice",
    題目: ["restored final question"],
    正確解題分析: ["restored answer"],
    verification: { passed: true },
    image_base64: PNG_BYTES,
  };
}

function partialQuestion(id?: string): ExamQuestion {
  return {
    ...(id ? { id } : {}),
    情境: [],
    題型種類: "single",
    題型: "choice",
    題目: ["restored partial question"],
    正確解題分析: ["partial answer"],
    image_base64: PNG_BYTES,
  };
}

function resultsFixture(withIds = true): ResultsWorkspaceSnapshot {
  const final = finalQuestion(withIds ? "final-question" : undefined);
  const partial = partialQuestion(withIds ? "partial-question" : undefined);
  const displayResults: GeneratedQuestion[] = [
    { index: 0, question: final, phase: "verified", isFinal: true },
    { index: 1, question: partial, phase: "draft", isFinal: false },
  ];
  return {
    kind: "results",
    version: 1,
    results: [final],
    displayResults,
    progressLines: ["received final", "received partial"],
    errorMessage: null,
    startedAt: 10,
    finishedAt: 20,
    subQuestionTotal: null,
    requestedTotal: 2,
    submittedSubQuestionCount: null,
    completion: "unknown",
    processing: "unknown",
    terminalEvidence: false,
    runId: "received-run",
    evidence: [
      {
        stableId: withIds ? "final-question" : "index-0",
        index: 0,
        receipt: "final",
        processing: "unknown",
        contentRevision: null,
        terminal: "unknown",
        review: { status: "passed", contentRevision: null },
      },
      {
        stableId: withIds ? "partial-question" : "index-1",
        index: 1,
        receipt: "draft",
        processing: "unknown",
        contentRevision: null,
        terminal: "unknown",
        review: { status: "unknown", contentRevision: null },
      },
    ],
    images: {
      [withIds ? "final-question" : "index-0"]: {
        base64: PNG_BYTES,
        mimeType: "image/png",
        location: "question",
      },
      [withIds ? "partial-question" : "index-1"]: {
        base64: PNG_BYTES,
        mimeType: "image/png",
        location: "question",
      },
    },
  };
}

function setRelease(status: "current" | "update-required") {
  useReleaseStore.setState({
    status,
    requiredBuildId: status === "update-required" ? "build-C" : null,
    releaseRevision: status === "update-required" ? 3 : 2,
    supportedRecoveryFormats: [RECOVERY_FORMAT_V1],
    lastCheckedAt: Date.now(),
    lastFailure: null,
    checkNow: async () => {},
  } as ReleaseState);
}

async function saveResultsRecovery(
  snapshotId: string,
  results: ResultsWorkspaceSnapshot,
): Promise<void> {
  const tabId = getOrCreateTabId();
  const saved = await saveSnapshotTransactionally({
    schema: RECOVERY_FORMAT_V1,
    snapshot_id: snapshotId,
    tab_id: tabId,
    route: ROUTE,
    subject: "math",
    account_id: USER.id,
    origin: window.location.origin,
    environment: "production",
    source_build_id: "build-A",
    target_build_id: "build-B",
    source_release_revision: 1,
    target_release_revision: 2,
    saved_at: new Date(0).toISOString(),
    workspace_revision: 4,
    form: FORM,
    results,
  });
  expect(saved).toEqual({ ok: true });
  const pointer = await persistTabPointer({
    tab_id: tabId,
    snapshot_id: snapshotId,
    account_id: USER.id,
    route: ROUTE,
    attempted_target_build_id: "build-B",
    attempted_target_release_revision: 2,
  });
  expect(pointer).toEqual({ ok: true });
}

function renderRecoveryPage() {
  window.history.replaceState({}, "", ROUTE);
  const routes: RouteObject[] = [
    {
      element: (
        <>
          <ReleaseNotice />
          <Outlet />
        </>
      ),
      children: [{ path: ROUTE, element: <GeneratePage subject="math" /> }],
    },
  ];
  const router = createMemoryRouter(routes, { initialEntries: [ROUTE] });
  const rendered = render(<RouterProvider router={router} />);
  return { ...rendered, router };
}

function bootRecovery(snapshotId: string) {
  setRelease("current");
  initRecoveryStore({
    currentRoute: ROUTE,
    origin: window.location.origin,
    environment: "production",
  });
  expect(useRecoveryStore.getState().pending?.snapshot_id).toBe(snapshotId);
}

function selectRestoredQuestionText(): void {
  const text = screen.getByText("restored final question", { exact: true });
  const textNode = text.firstChild;
  if (!(textNode instanceof Text)) throw new Error("Expected restored question text node");
  const range = document.createRange();
  range.setStart(textNode, 0);
  range.setEnd(textNode, 8);
  const selection = window.getSelection();
  if (!selection) throw new Error("Expected a browser selection");
  selection.removeAllRanges();
  selection.addRange(range);
  fireEvent.mouseUp(text);
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  resetRecoveryStoreForTests();
  resetWorkspaceStoreForTests();
  useAuthStore.setState({ token: "token", user: USER });
  setRelease("current");
  buildExamOdtMock.mockReset().mockResolvedValue(new Blob(["odt"]));
  fetchEventSourceMock.mockReset().mockResolvedValue(undefined);
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:recovery-test");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
});

afterEach(() => {
  window.getSelection()?.removeAllRanges();
  vi.restoreAllMocks();
  resetRecoveryStoreForTests();
  resetWorkspaceStoreForTests();
});

describe("GeneratePage restored results acceptance boundaries", () => {
  it("exports restored final results to JSON and ODT, and keeps the final-card PNG download", async () => {
    const results = resultsFixture();
    await saveResultsRecovery("exports", results);
    bootRecovery("exports");
    const downloaded: Blob[] = [];
    vi.mocked(URL.createObjectURL).mockImplementation((blob) => {
      downloaded.push(blob);
      return "blob:recovery-test";
    });

    const { unmount } = renderRecoveryPage();
    await screen.findByText("restored final question", { exact: true });

    const jsonButton = screen.getByRole("button", { name: /Download all as JSON|下載全部 JSON/i });
    expect(jsonButton).not.toBeDisabled();
    fireEvent.click(jsonButton);
    expect(await downloaded[0].text()).toContain("restored final question");
    expect(await downloaded[0].text()).toContain(PNG_BYTES);

    const odtButton = screen.getByRole("button", { name: /Download all as ODT|下載全部 ODT/i });
    fireEvent.click(odtButton);
    await waitFor(() => expect(buildExamOdtMock).toHaveBeenCalledOnce());
    expect(buildExamOdtMock).toHaveBeenCalledWith("exam_recovery-test", [
      expect.objectContaining({
        題目: ["restored final question"],
        image_base64: PNG_BYTES,
      }),
    ]);

    const pngButtons = screen.getAllByRole("button", { name: /Download PNG|下載 PNG/i });
    expect(pngButtons).toHaveLength(2);
    expect(pngButtons[0]).not.toBeDisabled();
    expect(pngButtons[1]).toBeDisabled();
    fireEvent.click(pngButtons[0]);
    const pngBlob = downloaded.at(-1);
    expect(pngBlob?.type).toBe("image/png");
    expect(new Uint8Array(await pngBlob!.arrayBuffer())).toEqual(
      new Uint8Array([105, 109, 97, 103, 101, 45, 98, 121, 116, 101, 115]),
    );
    unmount();
  });

  it("does not expose History-only modification controls for restored generated cards, while recordId still enables them", async () => {
    await saveResultsRecovery("eligibility", resultsFixture());
    bootRecovery("eligibility");
    const { unmount } = renderRecoveryPage();
    await screen.findByText("restored final question", { exact: true });

    expect(screen.queryByRole("button", { name: /Submit modifications|提交修改/i })).not.toBeInTheDocument();
    expect(useWorkspaceStore.getState().surfaces["history.modification"]).toBeUndefined();
    selectRestoredQuestionText();
    expect(screen.queryByRole("textbox", { name: /Modification instruction|修改指示/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Submit modifications|提交修改/i })).not.toBeInTheDocument();
    unmount();

    render(
      <QuestionCard
        question={finalQuestion("history-question")}
        recordId="history-record"
        isFinal
      />,
    );
    selectRestoredQuestionText();
    expect(screen.getByRole("button", { name: /Submit modifications|提交修改/i })).toBeInTheDocument();
    expect(useWorkspaceStore.getState().surfaces["history.modification"]).toMatchObject({
      id: "history.modification",
      hasReceivedResults: false,
    });
  });

  it("leaves the live mixed image batch and the previously saved complete copy intact after a quota failure", async () => {
    const results = resultsFixture();
    await saveResultsRecovery("previous-copy", results);
    bootRecovery("previous-copy");
    const { unmount } = renderRecoveryPage();
    await screen.findByText("restored final question", { exact: true });

    setRelease("update-required");
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Save Draft & Update|儲存草稿並更新/i })).not.toBeDisabled();
    });
    vi.spyOn(localStorage, "setItem").mockImplementationOnce(() => {
      throw new DOMException("QuotaExceededError", "QuotaExceededError");
    });

    const saveButton = screen.getByRole("button", { name: /Save Draft & Update|儲存草稿並更新/i });
    await act(async () => { fireEvent.click(saveButton); });
    await waitFor(() => expect(screen.getByRole("button", { name: /Retry|重試/i })).toBeInTheDocument());

    const stored = loadSnapshot(USER.id, "previous-copy");
    expect(stored?.results).toEqual(results);
    expect(stored?.results?.images).toEqual(results.images);
    expect(stored?.results?.displayResults).toHaveLength(2);
    expect(loadTabPointer()?.snapshot_id).toBe("previous-copy");
    expect(screen.getAllByRole("img")).toHaveLength(2);
    expect(screen.getByText("restored final question", { exact: true })).toBeInTheDocument();
    expect(screen.getByText("restored partial question", { exact: true })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Download all as JSON|下載全部 JSON/i })).not.toBeDisabled();
    expect(screen.getByRole("button", { name: /Download all as ODT|下載全部 ODT/i })).not.toBeDisabled();
    const downloaded: Blob[] = [];
    vi.mocked(URL.createObjectURL).mockImplementation((blob) => {
      downloaded.push(blob);
      return "blob:recovery-test";
    });
    const pointerBeforeExports = loadTabPointer();
    fireEvent.click(screen.getByRole("button", { name: /Download all as JSON|下載全部 JSON/i }));
    fireEvent.click(screen.getByRole("button", { name: /Download all as ODT|下載全部 ODT/i }));
    await waitFor(() => expect(buildExamOdtMock).toHaveBeenCalledOnce());
    await waitFor(() => expect(downloaded).toHaveLength(2));
    expect(await downloaded[0].text()).toContain("restored final question");
    expect(await downloaded[0].text()).toContain(PNG_BYTES);
    expect(buildExamOdtMock).toHaveBeenCalledWith(
      "exam_recovery-test",
      [expect.objectContaining({ image_base64: PNG_BYTES })],
    );
    expect(loadTabPointer()).toEqual(pointerBeforeExports);
    expect(loadSnapshot(USER.id, "previous-copy")).toEqual(stored);
    expect(useRecoveryStore.getState().pending).not.toBeNull();
    unmount();
  });

  it("captures and restores a mixed batch even when no History IDs ever existed", async () => {
    const results = resultsFixture(false);
    await saveResultsRecovery("no-history-id", results);
    const storedBeforeBoot = loadSnapshot(USER.id, "no-history-id");
    expect(storedBeforeBoot?.results?.results[0]).not.toHaveProperty("recordId");
    expect(storedBeforeBoot?.results?.displayResults).toHaveLength(2);
    bootRecovery("no-history-id");

    const { unmount } = renderRecoveryPage();
    await screen.findByText("restored final question", { exact: true });
    expect(screen.getByText("restored partial question", { exact: true })).toBeInTheDocument();
    expect(screen.getAllByRole("img")).toHaveLength(2);
    expect(useWorkspaceStore.getState().surfaces["history.modification"]).toBeUndefined();
    expect(screen.getByRole("button", { name: /Download all as JSON|下載全部 JSON/i })).not.toBeDisabled();
    expect(screen.getByRole("button", { name: /Download all as ODT|下載全部 ODT/i })).not.toBeDisabled();
    unmount();
  });

  it("disables save-and-update in the real page while generation is active", async () => {
    setRelease("update-required");
    const { unmount } = renderRecoveryPage();
    fireEvent.click(await screen.findByRole("button", { name: "Start generation" }));
    await waitFor(() => {
      expect(useWorkspaceStore.getState().operations).toEqual([
        expect.objectContaining({ kind: "generation", surface: "generate.results" }),
      ]);
    });
    const saveButton = screen.getByRole("button", { name: /Save Draft & Update|儲存草稿並更新/i });
    expect(saveButton).toBeDisabled();
    expect(saveButton).toHaveAttribute("title", "Cannot update while generating");
    fireEvent.click(saveButton);
    expect(loadTabPointer()).toBeNull();
    unmount();
  });
});

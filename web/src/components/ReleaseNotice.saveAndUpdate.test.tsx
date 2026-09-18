/**
 * Tests for Save Draft & Update button in ReleaseNotice — issue #772.
 * Written BEFORE the implementation (red phase).
 */
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, beforeEach, vi } from "vitest";
import ReleaseNotice from "./ReleaseNotice";
import { useReleaseStore } from "../lib/release/releaseStore";
import { useWorkspaceStore, resetWorkspaceStoreForTests } from "../lib/workspace/workspaceStore";
import { useAuthStore } from "../store/authStore";
import type { FormWorkspaceSnapshot } from "../lib/workspace/adapters/types";

vi.stubGlobal("__BUILD_ID__", "build-A");
vi.stubGlobal("__BUILD_ENVIRONMENT__", "production");

// Mock saveAndUpdate to control outcomes
vi.mock("../lib/recovery/saveAndUpdate", async (importOriginal) => {
  const real = await importOriginal<typeof import("../lib/recovery/saveAndUpdate")>();
  return {
    ...real,
    runSaveAndUpdate: vi.fn().mockResolvedValue({ ok: true }),
  };
});

function makeFormExport(): FormWorkspaceSnapshot {
  return { kind: "form", version: 1, fields: {} as never };
}

function setupUpdateRequiredState() {
  useReleaseStore.setState({
    status: "update-required",
    requiredBuildId: "build-B",
    releaseRevision: 2,
    supportedRecoveryFormats: ["exam-generation.recovery/1"],
  });
  useAuthStore.setState({
    token: "tok",
    user: { id: "u1", email: "u@test.com", created_at: "2024-01-01T00:00:00Z" },
  });
  const exportWorkspace = vi.fn().mockReturnValue(makeFormExport());
  useWorkspaceStore.getState().registerSurface({
    id: "generate.form",
    readiness: "ready",
    hasEditableState: true,
    hasReceivedResults: false,
    exportWorkspace,
  });
}

beforeEach(() => {
  resetWorkspaceStoreForTests();
  useReleaseStore.setState({
    status: "checking",
    requiredBuildId: null,
    releaseRevision: null,
    supportedRecoveryFormats: [],
    lastCheckedAt: null,
    lastFailure: null,
  });
  useAuthStore.setState({ token: null, user: null });
  localStorage.clear();
  sessionStorage.clear();
});

describe("ReleaseNotice — Save Draft & Update button", () => {
  it("shows the Save Draft & Update button when update is required and conditions met", () => {
    setupUpdateRequiredState();
    render(<ReleaseNotice />);
    expect(screen.getByRole("button", { name: /儲存草稿並更新|Save Draft/i })).toBeInTheDocument();
  });

  it("does not show the button when status is current", () => {
    useReleaseStore.setState({ status: "current", requiredBuildId: null, releaseRevision: 1 });
    render(<ReleaseNotice />);
    expect(screen.queryByRole("button", { name: /儲存草稿並更新|Save Draft/i })).not.toBeInTheDocument();
  });

  it("shows the button disabled with a reason when user is not signed in", () => {
    useReleaseStore.setState({
      status: "update-required",
      requiredBuildId: "build-B",
      releaseRevision: 2,
      supportedRecoveryFormats: ["exam-generation.recovery/1"],
    });
    // Don't set user
    useWorkspaceStore.getState().registerSurface({
      id: "generate.form",
      readiness: "ready",
      hasEditableState: true,
      hasReceivedResults: false,
      exportWorkspace: () => makeFormExport(),
    });
    render(<ReleaseNotice />);
    const btn = screen.getByRole("button", { name: /儲存草稿並更新|Save Draft/i });
    expect(btn).toBeDisabled();
  });

  it("calls runSaveAndUpdate on click", async () => {
    setupUpdateRequiredState();
    const { runSaveAndUpdate } = await import("../lib/recovery/saveAndUpdate");
    render(<ReleaseNotice />);
    const btn = screen.getByRole("button", { name: /儲存草稿並更新|Save Draft/i });
    fireEvent.click(btn);
    await waitFor(() => {
      expect(runSaveAndUpdate).toHaveBeenCalled();
    });
  });

  it("shows saving state during save", async () => {
    setupUpdateRequiredState();
    const { runSaveAndUpdate } = await import("../lib/recovery/saveAndUpdate");
    let resolve!: (v: { ok: boolean }) => void;
    vi.mocked(runSaveAndUpdate).mockReturnValueOnce(
      new Promise((r) => { resolve = r; }),
    );
    render(<ReleaseNotice />);
    const btn = screen.getByRole("button", { name: /儲存草稿並更新|Save Draft/i });
    fireEvent.click(btn);
    // Button should show saving state
    await waitFor(() => {
      expect(btn).toBeDisabled();
    });
    resolve({ ok: true });
  });
});

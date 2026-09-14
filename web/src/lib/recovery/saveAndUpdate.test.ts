/**
 * Tests for save-and-update eligibility — issue #772.
 * Written BEFORE the implementation (red phase).
 */
import { describe, it, expect, beforeEach } from "vitest";
import { evaluateSaveAndUpdate, type EvaluateInput } from "./saveAndUpdate";
import type { SurfaceParticipation } from "../workspace/workspaceStore";
import type { FormWorkspaceSnapshot } from "../workspace/adapters/types";

function makeFormSurface(
  overrides: Partial<SurfaceParticipation> = {},
): SurfaceParticipation {
  const exportWorkspace = (): FormWorkspaceSnapshot => ({
    kind: "form",
    version: 1,
    fields: {} as never,
  });
  return {
    id: "generate.form",
    readiness: "ready",
    hasEditableState: true,
    hasReceivedResults: false,
    exportWorkspace,
    ...overrides,
  };
}

function makeValidInput(overrides: Partial<EvaluateInput> = {}): EvaluateInput {
  return {
    surfaces: {
      "generate.form": makeFormSurface(),
    },
    operations: [],
    releaseStatus: "update-required",
    requiredBuildId: "build-B",
    releaseRevision: 2,
    supportedRecoveryFormats: ["exam-generation.recovery/1"],
    user: { id: "user-1", email: "u@test.com", created_at: "2024-01-01T00:00:00Z" },
    ...overrides,
  };
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

describe("evaluateSaveAndUpdate", () => {
  it("returns allowed:true for a valid state", () => {
    const result = evaluateSaveAndUpdate(makeValidInput());
    expect(result.allowed).toBe(true);
  });

  it("rejects when no surfaces registered", () => {
    const result = evaluateSaveAndUpdate(makeValidInput({ surfaces: {} }));
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("no_surface");
  });

  it("rejects when a surface is hydrating", () => {
    const result = evaluateSaveAndUpdate(
      makeValidInput({
        surfaces: {
          "generate.form": makeFormSurface({ readiness: "hydrating" }),
        },
      }),
    );
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("hydrating");
  });

  it("rejects when a surface is restoring", () => {
    const result = evaluateSaveAndUpdate(
      makeValidInput({
        surfaces: {
          "generate.form": makeFormSurface({ readiness: "restoring" }),
        },
      }),
    );
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("restoring");
  });

  it("rejects when an operation is active", () => {
    const result = evaluateSaveAndUpdate(
      makeValidInput({
        operations: [
          { id: 1, kind: "generation", surface: "generate.form", startedAt: Date.now() },
        ],
      }),
    );
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("operation_active");
  });

  it("rejects when a surface has received results", () => {
    const result = evaluateSaveAndUpdate(
      makeValidInput({
        surfaces: {
          "generate.form": makeFormSurface({ hasReceivedResults: true }),
        },
      }),
    );
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("results_present");
  });

  it("rejects when generate.confirmation is registered", () => {
    const result = evaluateSaveAndUpdate(
      makeValidInput({
        surfaces: {
          "generate.form": makeFormSurface(),
          "generate.confirmation": {
            id: "generate.confirmation",
            readiness: "ready",
            hasEditableState: true,
            hasReceivedResults: false,
          },
        },
      }),
    );
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("confirmation_open");
  });

  it("rejects when history.modification is registered", () => {
    const result = evaluateSaveAndUpdate(
      makeValidInput({
        surfaces: {
          "generate.form": makeFormSurface(),
          "history.modification": {
            id: "history.modification",
            readiness: "ready",
            hasEditableState: true,
            hasReceivedResults: false,
          },
        },
      }),
    );
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("modification_draft");
  });

  it("rejects when user is not signed in", () => {
    const result = evaluateSaveAndUpdate(makeValidInput({ user: null }));
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("not_signed_in");
  });

  it("rejects when release status is not update-required", () => {
    const result = evaluateSaveAndUpdate(makeValidInput({ releaseStatus: "current" }));
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("no_update");
  });

  it("rejects when requiredBuildId is null", () => {
    const result = evaluateSaveAndUpdate(makeValidInput({ requiredBuildId: null }));
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("no_update");
  });

  it("rejects when releaseRevision is null", () => {
    const result = evaluateSaveAndUpdate(makeValidInput({ releaseRevision: null }));
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("no_update");
  });

  it("rejects when recovery format is not supported", () => {
    const result = evaluateSaveAndUpdate(
      makeValidInput({ supportedRecoveryFormats: ["other-format/1"] }),
    );
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("unsupported_target_reader");
  });

  it("rejects when form surface has no exportWorkspace seam", () => {
    const result = evaluateSaveAndUpdate(
      makeValidInput({
        surfaces: {
          "generate.form": makeFormSurface({ exportWorkspace: undefined }),
        },
      }),
    );
    expect(result.allowed).toBe(false);
    if (!result.allowed) expect(result.reason).toBe("unsupported_target_reader");
  });
});

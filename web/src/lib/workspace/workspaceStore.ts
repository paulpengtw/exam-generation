import { create } from "zustand";
import type { WorkspaceSnapshot } from "./adapters/types";

export type SurfaceId =
  | "generate.form"
  | "generate.confirmation"
  | "generate.results"
  | "history.list"
  | "history.detail"
  | "history.modification";
export type SurfaceReadiness = "hydrating" | "restoring" | "ready";

export interface SurfaceParticipation {
  id: SurfaceId;
  readiness: SurfaceReadiness;
  hasEditableState: boolean;
  hasReceivedResults: boolean;
  exportWorkspace?: () => WorkspaceSnapshot | null;
}

export type OperationKind =
  | "generation"
  | "modification"
  | "core_question_planning"
  | "resolve"
  | "prompt_preview"
  | "export_odt"
  | "export_image"
  | "export_json";
export type OperationOutcome = "completed" | "failed" | "aborted" | "superseded";

export interface ActiveOperation {
  id: number;
  kind: OperationKind;
  surface: SurfaceId;
  startedAt: number;
}

export interface OperationHandle {
  readonly id: number;
  end(outcome: OperationOutcome): void;
}

export interface WorkspaceState {
  surfaces: Partial<Record<SurfaceId, SurfaceParticipation>>;
  operations: ActiveOperation[];
  registerSurface(participation: SurfaceParticipation): () => void;
  updateSurface(id: SurfaceId, patch: Partial<Omit<SurfaceParticipation, "id">>): void;
  beginOperation(kind: OperationKind, surface: SurfaceId): OperationHandle;
}

export type RefreshBlocker =
  | { kind: "no_surface" }
  | { kind: "hydrating" | "restoring" | "editable" | "results"; surface: SurfaceId }
  | { kind: "operation"; operation: OperationKind; surface: SurfaceId };

let nextOperationId = 1;
const registrationTokens = new Map<SurfaceId, symbol>();

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  surfaces: {},
  operations: [],
  registerSurface(participation) {
    const entry = { ...participation };
    const token = Symbol(entry.id);
    registrationTokens.set(entry.id, token);
    set((state) => ({ surfaces: { ...state.surfaces, [entry.id]: entry } }));
    return () => {
      if (registrationTokens.get(entry.id) !== token) return;
      registrationTokens.delete(entry.id);
      set((state) => {
        const surfaces = { ...state.surfaces };
        delete surfaces[entry.id];
        return { surfaces };
      });
    };
  },
  updateSurface(id, patch) {
    set((state) => {
      const current = state.surfaces[id];
      if (!current) return state;
      return { surfaces: { ...state.surfaces, [id]: { ...current, ...patch } } };
    });
  },
  beginOperation(kind, surface) {
    const id = nextOperationId++;
    set((state) => ({ operations: [...state.operations, { id, kind, surface, startedAt: Date.now() }] }));
    let ended = false;
    return {
      id,
      // Outcomes are explicit at call sites; this registry retains only active work.
      end() {
        if (ended) return;
        ended = true;
        set((state) => ({ operations: state.operations.filter((op) => op.id !== id) }));
      },
    };
  },
}));

export function isRefreshSafe(
  state: Pick<WorkspaceState, "surfaces" | "operations">,
): { safe: boolean; blockers: RefreshBlocker[] } {
  const blockers: RefreshBlocker[] = [];
  const surfaces = Object.values(state.surfaces);
  if (surfaces.length === 0) blockers.push({ kind: "no_surface" });
  for (const surface of surfaces) {
    if (surface.readiness !== "ready") {
      blockers.push({ kind: surface.readiness, surface: surface.id });
    }
    if (surface.hasEditableState) blockers.push({ kind: "editable", surface: surface.id });
    if (surface.hasReceivedResults) blockers.push({ kind: "results", surface: surface.id });
  }
  for (const operation of state.operations) {
    blockers.push({ kind: "operation", operation: operation.kind, surface: operation.surface });
  }
  return { safe: blockers.length === 0, blockers };
}

export function resetWorkspaceStoreForTests(): void {
  registrationTokens.clear();
  useWorkspaceStore.setState({ surfaces: {}, operations: [] });
}

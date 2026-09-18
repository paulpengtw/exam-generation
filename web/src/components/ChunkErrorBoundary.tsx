/**
 * Error boundary for chunk-load and preload failures — issue #777.
 *
 * Catches runtime errors thrown by failed dynamic imports or preload failures
 * and routes them through the auto-refresh safety decision rather than
 * crashing the page silently or entering a reload loop.
 */
import { Component, type ReactNode } from "react";
import {
  classifyChunkError,
  decideOnChunkError,
  type ChunkErrorDecision,
} from "../lib/recovery/chunkErrorGuard";
import {
  checkAutoRefreshEligible,
  markAutoReloadAttempted,
} from "../lib/recovery/autoRefresh";
import { useWorkspaceStore } from "../lib/workspace/workspaceStore";
import { useReleaseStore } from "../lib/release/releaseStore";
import { useRecoveryStore } from "../lib/recovery/recoveryStore";

interface Props {
  children: ReactNode;
}

interface State {
  decision: ChunkErrorDecision | null;
}

export class ChunkErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { decision: null };
  }

  static getDerivedStateFromError(error: unknown): State {
    if (classifyChunkError(error) === null) {
      // Not a chunk error — let it propagate via componentDidCatch
      return { decision: null };
    }

    const wsState = useWorkspaceStore.getState();
    const releaseState = useReleaseStore.getState();
    const recoveryState = useRecoveryStore.getState();

    const currentBuildId =
      typeof __BUILD_ID__ === "undefined" ? "" : __BUILD_ID__;
    const releasedBuildId = releaseState.requiredBuildId;

    const eligibility = checkAutoRefreshEligible({
      workspaceState: wsState,
      recoveryPending: recoveryState.pending !== null,
      pageVisible:
        typeof document !== "undefined"
          ? document.visibilityState === "visible"
          : true,
      targetBuildId: releaseState.requiredBuildId,
      releaseRevision: releaseState.releaseRevision,
      releaseStatus: releaseState.status,
    });

    const decision = decideOnChunkError({
      error,
      currentBuildId,
      releasedBuildId,
      autoRefreshEligibility: eligibility,
    });

    if (decision.action === "reload") {
      const canMark =
        releaseState.requiredBuildId !== null &&
        releaseState.releaseRevision !== null
          ? markAutoReloadAttempted(
              releaseState.requiredBuildId,
              releaseState.releaseRevision,
            )
          : false;
      if (canMark) {
        window.location.reload();
        // Return pending state while reload is in flight
        return { decision: { action: "reload", kind: decision.kind } };
      }
      // Could not mark — show error instead
      return {
        decision: {
          action: "show_error",
          kind: decision.kind,
          reason: "marker_storage_denied",
        },
      };
    }

    return { decision };
  }

  componentDidCatch(error: unknown): void {
    if (classifyChunkError(error) === null) {
      // Re-throw so outer error boundaries or the default handler can catch it
      throw error;
    }
    // Chunk error already handled in getDerivedStateFromError
  }

  render(): ReactNode {
    const { decision } = this.state;
    if (decision === null) return this.props.children;
    if (decision.action === "reload") {
      // Reloading — render nothing while the navigation is in flight
      return null;
    }

    const message =
      decision.kind === "old_html"
        ? "此頁面已過期，請手動重新整理以取得最新版本。"
        : "必要的資源載入失敗，請先儲存工作後再手動重新整理。";

    return (
      <div role="alert" style={{ padding: "1rem" }}>
        <p>{message}</p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          style={{ marginTop: "0.5rem" }}
        >
          重新整理
        </button>
      </div>
    );
  }
}

export default ChunkErrorBoundary;

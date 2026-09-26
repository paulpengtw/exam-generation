import { describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import {
  ActionButton,
  ActionFeedbackProvider,
  firstFailure,
  InlineFailureNotice,
  useActionFeedback,
} from "./actionFeedback";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function ActionFixture({
  action,
  genericError = "Unable to download the file.",
  timeoutMs,
  successState,
  failureState,
}: {
  action: (signal: AbortSignal) => Promise<string>;
  genericError?: string;
  timeoutMs?: number;
  successState?: "idle" | "done";
  failureState?: "idle" | "failed";
}) {
  const feedback = useActionFeedback({
    action,
    genericError,
    timeoutMs,
    successState,
    failureState,
    getFilename: (result) => result,
  });
  const otherFeedback = useActionFeedback({
    action: async () => "other.json",
    genericError: "Unable to complete the other action.",
  });
  return (
    <>
      <div data-testid="controls">
        <ActionButton
          feedback={feedback}
          label="Download JSON"
          pendingLabel="Downloading…"
          doneLabel="Downloaded"
        />
        <ActionButton
          feedback={otherFeedback}
          label="Unrelated control"
          pendingLabel="Doing unrelated work…"
          doneLabel="Unrelated work done"
        />
      </div>
      <InlineFailureNotice
        reason={feedback.reason}
        onRetry={feedback.retry}
        onDismiss={feedback.dismiss}
      />
    </>
  );
}

function RouteHarness() {
  const navigate = useNavigate();
  const location = useLocation();
  useEffect(() => {
    routeNavigateRef.current = navigate;
    return () => {
      if (routeNavigateRef.current === navigate) routeNavigateRef.current = null;
    };
  }, [navigate]);
  return (
    <>
      <span data-testid="location">{location.pathname}</span>
      <button type="button" onClick={() => navigate("/next")}>Navigate</button>
    </>
  );
}

const routeNavigateRef: { current: ((to: string) => void) | null } = { current: null };

function renderFixture(
  action: (signal: AbortSignal) => Promise<string>,
  options?: {
    genericError?: string;
    timeoutMs?: number;
    successState?: "idle" | "done";
    failureState?: "idle" | "failed";
  },
) {
  return render(
    <MemoryRouter initialEntries={["/current"]}>
      <ActionFeedbackProvider>
        <ActionFixture action={action} {...options} />
        <RouteHarness />
      </ActionFeedbackProvider>
    </MemoryRouter>,
  );
}

describe("useActionFeedback and ActionButton", () => {
  it("selects the first failed feedback and ignores later failures", () => {
    const firstRetry = vi.fn();
    const firstDismiss = vi.fn();
    const laterRetry = vi.fn();
    const laterDismiss = vi.fn();

    const failure = firstFailure(
      { reason: null, retry: vi.fn(), dismiss: vi.fn() },
      { reason: "first failure", retry: firstRetry, dismiss: firstDismiss },
      { reason: "later failure", retry: laterRetry, dismiss: laterDismiss },
    );

    expect(failure?.reason).toBe("first failure");
    failure?.retry();
    failure?.dismiss();
    expect(firstRetry).toHaveBeenCalledOnce();
    expect(firstDismiss).toHaveBeenCalledOnce();
    expect(laterRetry).not.toHaveBeenCalled();
    expect(laterDismiss).not.toHaveBeenCalled();
    expect(firstFailure({ reason: null, retry: vi.fn(), dismiss: vi.fn() })).toBeNull();
  });

  it("moves from idle to pending to done and attaches the produced filename", async () => {
    const operation = deferred<string>();
    const action = vi.fn(() => operation.promise);
    const user = userEvent.setup();
    renderFixture(action);

    const button = screen.getByRole("button", { name: "Download JSON" });
    expect(button).toHaveAttribute("data-action-state", "idle");

    await user.click(button);
    expect(action).toHaveBeenCalledTimes(1);
    expect(action.mock.calls[0][0]).toBeInstanceOf(AbortSignal);
    expect(screen.getByRole("status")).toHaveTextContent("Downloading…");
    expect(screen.getByRole("status")).toHaveClass("sentry-unmask");
    expect(button).toBeDisabled();

    await user.click(button);
    expect(action).toHaveBeenCalledTimes(1);

    await act(async () => operation.resolve("question-1.json"));
    expect(screen.getByRole("status")).toHaveTextContent("Downloaded");
    expect(screen.getByRole("status")).toHaveClass("sentry-unmask");
    expect(screen.getByTestId("action-filename")).toHaveTextContent("question-1.json");
    expect(button).toHaveAttribute("data-action-state", "done");
  });

  it("keeps a failed label, marks only the pressed control, and uses ApiError.detail", async () => {
    const action = vi.fn(async () => {
      throw new ApiError(503, "The export service is unavailable.");
    });
    const user = userEvent.setup();
    renderFixture(action);

    await user.click(screen.getByRole("button", { name: "Download JSON" }));

    const failedButton = screen.getByRole("button", { name: "Download JSON" });
    expect(failedButton).toHaveAttribute("data-action-state", "failed");
    expect(failedButton).toHaveTextContent("Download JSON");
    expect(failedButton).toHaveTextContent("!");
    expect(screen.getByRole("button", { name: "Unrelated control" })).toHaveAttribute(
      "data-action-state",
      "idle",
    );
    expect(screen.getByRole("alert")).toHaveTextContent("The export service is unavailable.");
    expect(screen.getByRole("alert").querySelector(".sentry-unmask")).toHaveTextContent("Failed");
    expect(screen.getByRole("alert").querySelector("[data-testid=action-reason]")).not.toHaveClass(
      "sentry-unmask",
    );
  });

  it("uses the generic reason for non-ApiError failures", async () => {
    const action = vi.fn(async () => {
      throw new Error("transport internals");
    });
    const user = userEvent.setup();
    renderFixture(action, { genericError: "Unable to download JSON." });

    await user.click(screen.getByRole("button", { name: "Download JSON" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Unable to download JSON.");
    expect(screen.getByRole("alert")).not.toHaveTextContent("transport internals");
  });

  it("dismisses failures, retries successfully, and clears a failure on re-press", async () => {
    const action = vi
      .fn<(signal: AbortSignal) => Promise<string>>()
      .mockRejectedValueOnce(new Error("first failure"))
      .mockResolvedValueOnce("retry.json")
      .mockImplementationOnce(() => new Promise<string>(() => {}));
    const user = userEvent.setup();
    renderFixture(action);
    const button = screen.getByRole("button", { name: "Download JSON" });

    await user.click(button);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    await user.click(button);
    expect(await screen.findByRole("status")).toHaveTextContent("Downloaded");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    await user.click(button);
    expect(screen.getByRole("status")).toHaveTextContent("Downloading…");
    expect(button).toBeDisabled();
  });

  it("clears the failure notice immediately when the failed control is pressed again", async () => {
    const operation = deferred<string>();
    const action = vi
      .fn<(signal: AbortSignal) => Promise<string>>()
      .mockRejectedValueOnce(new Error("first failure"))
      .mockReturnValueOnce(operation.promise);
    const user = userEvent.setup();
    renderFixture(action);
    const button = screen.getByRole("button", { name: "Download JSON" });

    await user.click(button);
    expect(screen.getByRole("alert")).toBeInTheDocument();
    await user.click(button);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Downloading…");
    expect(action).toHaveBeenCalledTimes(2);

    await act(async () => operation.resolve("retry.json"));
  });

  it("does not clear done on inert clicks, but clears it on any control press", async () => {
    const action = vi.fn(async () => "question-1.json");
    const user = userEvent.setup();
    renderFixture(action);
    const button = screen.getByRole("button", { name: "Download JSON" });

    await user.click(button);
    expect(await screen.findByRole("status")).toHaveTextContent("Downloaded");

    await user.click(screen.getByTestId("controls"));
    expect(screen.getByRole("status")).toHaveTextContent("Downloaded");

    await user.click(screen.getByRole("button", { name: "Unrelated control" }));
    expect(button).not.toHaveAttribute("data-action-state", "done");
  });

  it("clears done on a route change", async () => {
    const action = vi.fn(async () => "question-1.json");
    const user = userEvent.setup();
    renderFixture(action);
    await user.click(screen.getByRole("button", { name: "Download JSON" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Downloaded");

    act(() => routeNavigateRef.current?.("/next"));
    expect(screen.getByTestId("location")).toHaveTextContent("/next");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("fails with the generic reason when the AbortSignal timeout fires", async () => {
    const action = vi.fn((signal: AbortSignal) => {
      void signal;
      return new Promise<string>(() => {});
    });
    const user = userEvent.setup();
    renderFixture(action, { timeoutMs: 10, genericError: "The request timed out." });

    await user.click(screen.getByRole("button", { name: "Download JSON" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The request timed out.");
    expect(action.mock.calls[0][0]).toBeInstanceOf(AbortSignal);
    expect(action.mock.calls[0][0].aborted).toBe(true);
  });

  it("can settle a stream starter back to idle without showing a terminal outcome", async () => {
    const action = vi.fn(async () => "admitted");
    const user = userEvent.setup();
    renderFixture(action, { successState: "idle", failureState: "idle" });

    const button = screen.getByRole("button", { name: "Download JSON" });
    await user.click(button);

    expect(button).toHaveAttribute("data-action-state", "idle");
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

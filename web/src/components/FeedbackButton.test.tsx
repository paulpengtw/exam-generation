import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const sentryState = vi.hoisted(() => ({ enabled: true }));
const formMock = vi.hoisted(() => ({
  appendToDom: vi.fn(),
  open: vi.fn(),
  removeFromDom: vi.fn(),
}));
const createFormMock = vi.hoisted(() =>
  vi.fn(() => Promise.resolve(formMock)),
);
const getFeedbackMock = vi.hoisted(() =>
  vi.fn(() => ({ createForm: createFormMock })),
);

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

vi.mock("../sentry", () => ({
  isSentryEnabled: () => sentryState.enabled,
}));

vi.mock("@sentry/react", () => ({
  getFeedback: getFeedbackMock,
}));

import FeedbackButton from "./FeedbackButton";

describe("FeedbackButton", () => {
  beforeEach(() => {
    sentryState.enabled = true;
    vi.clearAllMocks();
    getFeedbackMock.mockReturnValue({ createForm: createFormMock });
  });

  it("renders nothing when Sentry is not configured", () => {
    sentryState.enabled = false;
    const { container } = render(<FeedbackButton />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a ? button and opens the localized feedback form on click", async () => {
    render(<FeedbackButton />);
    const btn = screen.getByRole("button", { name: "Report a problem" });
    expect(btn).toHaveTextContent("?");

    fireEvent.click(btn);

    await waitFor(() => expect(formMock.open).toHaveBeenCalled());
    expect(createFormMock).toHaveBeenCalledWith(
      expect.objectContaining({
        formTitle: "Report a problem",
        submitButtonLabel: "Send report",
      }),
    );
    expect(formMock.appendToDom).toHaveBeenCalled();
  });

  it("does nothing when Sentry.getFeedback() returns undefined", () => {
    getFeedbackMock.mockReturnValueOnce(undefined);
    render(<FeedbackButton />);
    const btn = screen.getByRole("button", { name: "Report a problem" });

    expect(() => fireEvent.click(btn)).not.toThrow();
    expect(createFormMock).not.toHaveBeenCalled();
  });

  it("ignores a second click while the form is still being created", async () => {
    let resolveForm: (value: typeof formMock) => void;
    const pending = new Promise<typeof formMock>((resolve) => {
      resolveForm = resolve;
    });
    createFormMock.mockReturnValueOnce(pending);

    render(<FeedbackButton />);
    const btn = screen.getByRole("button", { name: "Report a problem" });

    fireEvent.click(btn);
    fireEvent.click(btn);
    resolveForm!(formMock);

    await waitFor(() => expect(formMock.open).toHaveBeenCalled());
    expect(createFormMock).toHaveBeenCalledTimes(1);
  });
});

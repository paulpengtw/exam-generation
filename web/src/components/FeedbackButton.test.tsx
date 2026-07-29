import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

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

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <FeedbackButton />
    </MemoryRouter>,
  );
}

describe("FeedbackButton", () => {
  beforeEach(() => {
    sentryState.enabled = true;
    vi.clearAllMocks();
    getFeedbackMock.mockReturnValue({ createForm: createFormMock });
  });

  it("renders nothing when Sentry is not configured", () => {
    sentryState.enabled = false;
    const { container } = renderAt("/history");
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a ? button and opens the localized feedback form on click", async () => {
    renderAt("/history");
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
    renderAt("/history");
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

    renderAt("/history");
    const btn = screen.getByRole("button", { name: "Report a problem" });

    fireEvent.click(btn);
    fireEvent.click(btn);
    resolveForm!(formMock);

    await waitFor(() => expect(formMock.open).toHaveBeenCalled());
    expect(createFormMock).toHaveBeenCalledTimes(1);
  });
});

describe("FeedbackButton — where it floats", () => {
  it.each([
    "/generate/math",
    "/generate/social_studies",
    "/generate/natural_sciences",
  ])("does not float on 生成頁面 (%s)", (path) => {
    const { container } = renderAt(path);
    expect(container).toBeEmptyDOMElement();
  });

  it.each(["/", "/generate", "/history"])(
    "still floats on %s",
    (path) => {
      renderAt(path);
      expect(
        screen.getByRole("button", { name: "Report a problem" }),
      ).toBeInTheDocument();
    },
  );
});

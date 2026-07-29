import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

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

vi.mock("@sentry/react", () => ({
  getFeedback: getFeedbackMock,
}));

vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) => key,
}));

vi.mock("../sentry", () => ({
  isSentryEnabled: () => true,
}));

import { useFeedbackDialog } from "./useFeedbackDialog";

describe("useFeedbackDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getFeedbackMock.mockReturnValue({ createForm: createFormMock });
  });

  it("hides the name field without passing a name label", async () => {
    const { result } = renderHook(() => useFeedbackDialog());

    await act(async () => {
      await result.current.open();
    });

    expect(createFormMock).toHaveBeenCalledTimes(1);
    const options = createFormMock.mock.calls[0][0];
    expect(options).toEqual(expect.objectContaining({ showName: false }));
    expect(options).not.toHaveProperty("nameLabel");
  });
});

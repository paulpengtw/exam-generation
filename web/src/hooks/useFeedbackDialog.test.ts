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
const replayFlushMock = vi.hoisted(() =>
  vi.fn(() => Promise.resolve()),
);
const getReplayMock = vi.hoisted(() =>
  vi.fn(() => ({ flush: replayFlushMock })),
);

vi.mock("@sentry/react", () => ({
  getFeedback: getFeedbackMock,
  getReplay: getReplayMock,
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
    createFormMock.mockReset();
    createFormMock.mockResolvedValue(formMock);
    getFeedbackMock.mockReturnValue({ createForm: createFormMock });
    replayFlushMock.mockReset();
    replayFlushMock.mockResolvedValue();
    getReplayMock.mockReset();
    getReplayMock.mockReturnValue({ flush: replayFlushMock });
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

  it("flushes and creates one form for two rapid open calls", async () => {
    let resolveFlush: () => void;
    replayFlushMock.mockReturnValueOnce(
      new Promise<void>((resolve) => {
        resolveFlush = resolve;
      }),
    );
    const { result } = renderHook(() => useFeedbackDialog());

    await act(async () => {
      const firstOpen = result.current.open();
      const secondOpen = result.current.open();
      await Promise.resolve();
      resolveFlush!();
      await Promise.all([firstOpen, secondOpen]);
    });

    expect(replayFlushMock).toHaveBeenCalledTimes(1);
    expect(createFormMock).toHaveBeenCalledTimes(1);
  });

  it("flushes the buffered replay before creating the feedback form", async () => {
    const calls: string[] = [];
    replayFlushMock.mockImplementationOnce(async () => {
      calls.push("flush");
    });
    createFormMock.mockImplementationOnce(async () => {
      calls.push("createForm");
      return formMock;
    });
    const { result } = renderHook(() => useFeedbackDialog());

    await act(async () => {
      await result.current.open();
    });

    expect(calls).toEqual(["flush", "createForm"]);
  });

  it("opens the form when no replay integration is available", async () => {
    getReplayMock.mockReturnValueOnce(undefined);
    const { result } = renderHook(() => useFeedbackDialog());

    await act(async () => {
      await result.current.open();
    });

    expect(replayFlushMock).not.toHaveBeenCalled();
    expect(createFormMock).toHaveBeenCalledTimes(1);
  });

  it("opens the form and remains usable when replay flushing fails", async () => {
    replayFlushMock.mockRejectedValueOnce(new Error("flush failed"));
    const { result } = renderHook(() => useFeedbackDialog());

    await act(async () => {
      await result.current.open();
    });
    expect(createFormMock).toHaveBeenCalledTimes(1);

    act(() => {
      createFormMock.mock.calls[0][0].onFormClose();
    });
    await act(async () => {
      await result.current.open();
    });

    expect(replayFlushMock).toHaveBeenCalledTimes(2);
    expect(createFormMock).toHaveBeenCalledTimes(2);
  });
});

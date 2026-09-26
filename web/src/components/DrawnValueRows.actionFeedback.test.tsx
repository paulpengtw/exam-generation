import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useState } from "react";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (state: { lang: string }) => unknown) =>
    selector({ lang: "zh-TW" }),
}));

import DrawnValueRows, { type RedrawResult } from "./DrawnValueRows";

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function RedrawFixture({
  onRedraw,
}: {
  onRedraw: () => Promise<RedrawResult | void>;
}) {
  const [value, setValue] = useState("原值");
  return (
    <DrawnValueRows
      drawnPaths={["field"]}
      fieldLabels={{ field: "欄位" }}
      valueForPath={() => value}
      onRedraw={async () => {
        const result = await onRedraw();
        if (result && "value" in result && typeof result.value === "string") {
          setValue(result.value);
        }
        return result;
      }}
      redrawLabel="重抽"
    />
  );
}

describe("DrawnValueRows redraw feedback", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("disables redraw re-entry, dims the value, and keeps the old value on failure", async () => {
    const request = deferred<void>();
    const onRedraw = vi.fn(() => request.promise);
    render(<RedrawFixture onRedraw={onRedraw} />);

    const button = screen.getByRole("button", { name: "重抽" });
    await act(async () => { fireEvent.click(button); });

    expect(onRedraw).toHaveBeenCalledTimes(1);
    expect(button).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("重抽中…");
    expect(screen.getByText("原值").closest("[data-drawn-value-path]")).toHaveClass(
      "opacity-50",
      "transition-opacity",
      "duration-quick",
      "ease-signature",
    );

    fireEvent.click(button);
    expect(onRedraw).toHaveBeenCalledTimes(1);

    await act(async () => { request.reject(new Error("temporary failure")); });
    await waitFor(() => expect(button).toHaveAttribute("data-action-state", "failed"));
    expect(button).toHaveTextContent("重抽");
    expect(button).toHaveTextContent("!");
    expect(screen.getByText("原值")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("retries the failed redraw and flashes with a same-value hint", async () => {
    const first = deferred<void>();
    const second = deferred<RedrawResult>();
    const onRedraw = vi
      .fn<() => Promise<RedrawResult | void>>()
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    render(<RedrawFixture onRedraw={onRedraw} />);

    const button = screen.getByRole("button", { name: "重抽" });
    fireEvent.click(button);
    await act(async () => { first.reject(new Error("temporary failure")); });
    await waitFor(() => expect(button).toHaveAttribute("data-action-state", "failed"));

    fireEvent.click(button);
    expect(onRedraw).toHaveBeenCalledTimes(2);
    expect(button).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("重抽中…");

    await act(async () => { second.resolve({ sameValue: true }); });
    await waitFor(() => expect(button).toHaveAttribute("data-action-state", "done"));
    expect(screen.getByText("重抽結果與原值相同")).toBeInTheDocument();
    expect(screen.getByTestId("redraw-control")).toHaveAttribute("data-redraw-flash", "1");
    expect(screen.getByText("原值").closest("[data-drawn-value-path]")).toHaveAttribute(
      "data-redraw-flash",
      "1",
    );
    expect(screen.getByText("原值").closest("[data-drawn-value-path]")).toHaveClass("redraw-flash");
    expect(screen.getByText("原值")).toBeInTheDocument();
  });
});

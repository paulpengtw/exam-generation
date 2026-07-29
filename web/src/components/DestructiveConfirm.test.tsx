import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

vi.mock("../i18n/useT", () => ({
  useT: () => (key: string) => key,
}));

import DestructiveConfirm from "./DestructiveConfirm";

const defaultProps = {
  open: true,
  titleKey: "x.title",
  bodyKeys: ["x.body_one", "x.body_two"],
  confirmKey: "x.confirm",
  onConfirm: vi.fn(),
  onCancel: vi.fn(),
};

describe("DestructiveConfirm", () => {
  it("renders nothing visible when closed", () => {
    const { container } = render(
      <DestructiveConfirm {...defaultProps} open={false} />,
    );

    const dialog = container.querySelector("dialog");
    expect(dialog).not.toBeNull();
    expect(dialog!.open).toBe(false);
    expect(dialog).not.toHaveAttribute("open");
    expect(screen.queryByRole("button", { name: "x.confirm" })).not.toBeInTheDocument();
  });

  it("shows the title, body paragraphs and buttons when open", () => {
    render(<DestructiveConfirm {...defaultProps} />);

    expect(screen.getByText("x.title")).toBeInTheDocument();
    expect(screen.getByText("x.body_one").tagName).toBe("P");
    expect(screen.getByText("x.body_two").tagName).toBe("P");
    expect(screen.getByRole("button", { name: "x.confirm" })).toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(2);
  });

  it("calls onConfirm exactly once when the confirm button is clicked", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <DestructiveConfirm
        {...defaultProps}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "x.confirm" }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("calls onCancel when the cancel button is clicked", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <DestructiveConfirm
        {...defaultProps}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );

    const cancelButton = screen
      .getAllByRole("button")
      .find((button) => button.textContent !== "x.confirm");
    expect(cancelButton).toBeDefined();
    fireEvent.click(cancelButton!);

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("treats Esc as a cancel", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(
      <DestructiveConfirm
        {...defaultProps}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    );

    fireEvent.keyDown(document, { key: "Escape" });

    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("opens and closes as the open prop changes", () => {
    const { container, rerender } = render(
      <DestructiveConfirm {...defaultProps} open={false} />,
    );
    const dialog = container.querySelector("dialog");
    expect(dialog).not.toBeNull();
    expect(dialog!.open).toBe(false);

    rerender(<DestructiveConfirm {...defaultProps} open />);
    expect(dialog!.open).toBe(true);
    expect(dialog).toHaveAttribute("open");

    rerender(<DestructiveConfirm {...defaultProps} open={false} />);
    expect(dialog!.open).toBe(false);
    expect(dialog).not.toHaveAttribute("open");
  });
});

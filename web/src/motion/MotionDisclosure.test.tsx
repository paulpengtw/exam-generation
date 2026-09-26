import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { MotionDisclosure } from "./MotionDisclosure";

let reducedMotionListener: ((event: { matches: boolean }) => void) | null = null;

function DisclosureFixture() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((current) => !current)}
      >
        toggle
      </button>
      <MotionDisclosure open={open}>
        <div data-testid="disclosure-content">content</div>
      </MotionDisclosure>
    </>
  );
}

function setReducedMotion(matches: boolean) {
  reducedMotionListener?.({ matches });
  const matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: matches && query === "(prefers-reduced-motion: reduce)",
    media: query,
    onchange: null,
    addEventListener: vi.fn((_event: string, listener: (event: { matches: boolean }) => void) => {
      if (query === "(prefers-reduced-motion: reduce)") reducedMotionListener = listener;
    }),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));

  vi.stubGlobal("matchMedia", matchMedia);
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: matchMedia,
  });
}

describe("MotionDisclosure", () => {
  it("keeps expanded content present and removes it after a real-timer collapse", async () => {
    setReducedMotion(false);
    render(<DisclosureFixture />);

    const toggle = screen.getByRole("button", { name: "toggle" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("disclosure-content")).toBeInTheDocument();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByTestId("disclosure-content")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByTestId("disclosure-content")).not.toBeInTheDocument(),
    );
  });

  it("changes state immediately when reduced motion is enabled", async () => {
    setReducedMotion(true);
    render(<DisclosureFixture />);

    const toggle = screen.getByRole("button", { name: "toggle" });
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("disclosure-content")).toBeInTheDocument();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await waitFor(() =>
      expect(screen.queryByTestId("disclosure-content")).not.toBeInTheDocument(),
    );
  });
});

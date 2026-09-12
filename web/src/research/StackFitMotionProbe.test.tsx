import { act, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AnimatePresence, motion } from "motion/react";

import { StackFitMotionProbe } from "./StackFitMotionProbe";

describe("Motion React probe", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders the state, list, and disclosure surfaces", () => {
    render(<StackFitMotionProbe />);

    expect(screen.getByRole("button", { name: "status pending" })).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "streamed questions" })).toHaveTextContent("question-1");
    expect(screen.getByRole("button", { name: "Disclosure" })).toBeInTheDocument();
  });

  it("keeps an exiting item until Motion finishes the exit", async () => {
    const onExitComplete = vi.fn();
    function ExitProbe() {
      const [visible, setVisible] = useState(true);
      return (
        <>
          <button type="button" onClick={() => setVisible(false)}>hide</button>
          <AnimatePresence onExitComplete={onExitComplete}>
            {visible && (
              <motion.div
                data-testid="motion-exit"
                exit={{ opacity: 0 }}
                transition={{ duration: 0.05 }}
              />
            )}
          </AnimatePresence>
        </>
      );
    }

    render(<ExitProbe />);
    await act(async () => {
      screen.getByRole("button", { name: "hide" }).click();
    });

    expect(screen.getByTestId("motion-exit")).toBeInTheDocument();
    await waitFor(() => expect(onExitComplete).toHaveBeenCalledTimes(1), { timeout: 500 });
    expect(screen.queryByTestId("motion-exit")).not.toBeInTheDocument();
  });
});

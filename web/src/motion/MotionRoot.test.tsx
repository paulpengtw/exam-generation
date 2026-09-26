import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { useContext, useEffect } from "react";
import { m } from "motion/react";
import MotionRoot from "./MotionRoot";
import { MotionPlatformContext } from "./MotionPlatformContext";

describe("MotionRoot", () => {
  it("loads domAnimation features for m components", async () => {
    render(
      <MotionRoot>
        <m.div
          data-testid="animated"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
        />
      </MotionRoot>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("animated")).toHaveStyle({ opacity: 1 });
    });
  });

  it("reuses the existing motion platform for nested roots", async () => {
    const contexts: unknown[] = [];

    function ContextCapture() {
      const context = useContext(MotionPlatformContext);
      useEffect(() => {
        contexts.push(context);
      }, [context]);
      return null;
    }

    render(
      <MotionRoot>
        <ContextCapture />
        <MotionRoot>
          <ContextCapture />
        </MotionRoot>
      </MotionRoot>,
    );

    await waitFor(() => expect(contexts).toHaveLength(2));
    expect(contexts[0]).toBe(contexts[1]);
  });
});

import { describe, expect, it } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { m } from "motion/react";
import MotionRoot from "./MotionRoot";

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
});

/**
 * issue #946 — ProgressLog renders pre-localized error messages (task 6.5).
 *
 * ProgressLog receives a pre-localized errorMessage string from useGenerate
 * and must render it in a visible accessible block (role="alert"), not a
 * raw <pre> monospace block.
 */

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import ProgressLog from "./ProgressLog";

vi.mock("../store/langStore", () => ({
  useLangStore: (selector: (s: { lang: string }) => unknown) =>
    selector({ lang: "en-US" }),
}));

describe("ProgressLog — failure_class localized message (issue #946, task 6.5)", () => {
  it("renders the pre-localized errorMessage in a role=alert block", () => {
    const localizedMessage =
      "Rate limited\nThe provider is rate-limiting requests. Please wait a moment and try again.";

    render(
      <ProgressLog
        lines={[]}
        status="error"
        errorMessage={localizedMessage}
      />,
    );

    const alertEl = screen.getByRole("alert");
    expect(alertEl).toBeInTheDocument();
    expect(alertEl).toHaveTextContent("Rate limited");
    expect(alertEl).toHaveTextContent("The provider is rate-limiting requests");
  });

  it("does NOT render error block when errorMessage is null", () => {
    render(
      <ProgressLog
        lines={[]}
        status="error"
        errorMessage={null}
      />,
    );

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("renders admin-only guidance for quota_billing_exhausted", () => {
    const localizedMessage =
      "Quota or billing exhausted\nPlease contact the administrator — the provider quota or billing limit has been reached.";

    render(
      <ProgressLog
        lines={[]}
        status="error"
        errorMessage={localizedMessage}
      />,
    );

    const alertEl = screen.getByRole("alert");
    expect(alertEl).toHaveTextContent("Quota or billing exhausted");
    expect(alertEl).toHaveTextContent("Please contact the administrator");
  });

  it("renders raw message when no failure_class (fallback path)", () => {
    render(
      <ProgressLog
        lines={[]}
        status="error"
        errorMessage="Something went wrong unexpectedly"
      />,
    );

    const alertEl = screen.getByRole("alert");
    expect(alertEl).toHaveTextContent("Something went wrong unexpectedly");
  });

  it("the error block is not a <pre> element (not monospace code)", () => {
    render(
      <ProgressLog
        lines={[]}
        status="error"
        errorMessage="An error occurred"
      />,
    );

    const alertEl = screen.getByRole("alert");
    expect(alertEl.tagName.toLowerCase()).not.toBe("pre");
  });
});

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { maybeTriggerE2eCrash } from "./e2eCrash";

let scheduledCallback: (() => void) | undefined;

beforeEach(() => {
  scheduledCallback = undefined;
  window.history.replaceState({}, "", "/");
  vi.stubGlobal(
    "setTimeout",
    vi.fn((callback: () => void) => {
      scheduledCallback = callback;
      return 0;
    }),
  );
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("maybeTriggerE2eCrash", () => {
  it("schedules the deliberate error in staging when the parameter is present", () => {
    vi.stubEnv("VITE_IS_STAGING", "true");
    window.history.replaceState({}, "", "/?e2e-crash");

    maybeTriggerE2eCrash();

    expect(scheduledCallback).toBeTypeOf("function");
    expect(() => scheduledCallback?.()).toThrow(
      "e2e-crash: deliberate staging test error",
    );
  });

  it("does not schedule an error in staging without the parameter", () => {
    vi.stubEnv("VITE_IS_STAGING", "true");

    maybeTriggerE2eCrash();

    expect(scheduledCallback).toBeUndefined();
  });

  it("does not schedule an error outside staging when the parameter is present", () => {
    vi.stubEnv("VITE_IS_STAGING", "");
    window.history.replaceState({}, "", "/?e2e-crash");

    maybeTriggerE2eCrash();

    expect(scheduledCallback).toBeUndefined();
  });
});

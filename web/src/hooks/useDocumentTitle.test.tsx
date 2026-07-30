import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Use the real langStore so locale-switch reactivity can be tested.
import { useLangStore } from "../store/langStore";
import { useDocumentTitle } from "./useDocumentTitle";

// Literal expected strings from the issue spec — not derived from messages.ts.
const TITLE_EN = "素養試題 AI Examgen";
const TITLE_STAGING_EN = "[Staging] 素養試題 AI Examgen";
const TITLE_STAGING_ZH = "【測試機】素養試題 AI Examgen";

describe("useDocumentTitle", () => {
  beforeEach(() => {
    // Reset to a known locale before each test.
    act(() => {
      useLangStore.getState().setLang("en-US");
    });
    document.title = "";
  });

  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("sets the staging title (zh-TW) when VITE_IS_STAGING is set and locale is zh-TW", () => {
    vi.stubEnv("VITE_IS_STAGING", "1");
    act(() => {
      useLangStore.getState().setLang("zh-TW");
    });

    renderHook(() => useDocumentTitle());

    expect(document.title).toBe(TITLE_STAGING_ZH);
  });

  it("sets the staging title (en-US) when VITE_IS_STAGING is set and locale is en-US", () => {
    vi.stubEnv("VITE_IS_STAGING", "1");
    act(() => {
      useLangStore.getState().setLang("en-US");
    });

    renderHook(() => useDocumentTitle());

    expect(document.title).toBe(TITLE_STAGING_EN);
  });

  it("sets the base title when VITE_IS_STAGING is unset (empty)", () => {
    vi.stubEnv("VITE_IS_STAGING", "");

    // Both locales should give the same base title.
    act(() => {
      useLangStore.getState().setLang("en-US");
    });
    renderHook(() => useDocumentTitle());
    expect(document.title).toBe(TITLE_EN);

    act(() => {
      useLangStore.getState().setLang("zh-TW");
    });
    renderHook(() => useDocumentTitle());
    expect(document.title).toBe(TITLE_EN);
  });

  it("updates the title when the locale changes after mount", () => {
    vi.stubEnv("VITE_IS_STAGING", "1");
    act(() => {
      useLangStore.getState().setLang("en-US");
    });

    renderHook(() => useDocumentTitle());
    expect(document.title).toBe(TITLE_STAGING_EN);

    act(() => {
      useLangStore.getState().setLang("zh-TW");
    });
    expect(document.title).toBe(TITLE_STAGING_ZH);
  });
});

import { describe, expect, it } from "vitest";
import { resolveSentryUpload } from "./sentryUpload";

describe("resolveSentryUpload", () => {
  it("disables source-map uploads when the auth token is missing or empty", () => {
    const configuredEnv = {
      SENTRY_ORG: "exam-org",
      SENTRY_PROJECT: "exam-web",
      VITE_SENTRY_RELEASE: "9cffb64",
    };

    expect(resolveSentryUpload(configuredEnv)).toEqual({ enabled: false });
    expect(
      resolveSentryUpload({
        ...configuredEnv,
        SENTRY_AUTH_TOKEN: "",
      }),
    ).toEqual({ enabled: false });
  });

  it("enables source-map uploads for a fully configured deploy build", () => {
    expect(
      resolveSentryUpload({
        SENTRY_AUTH_TOKEN: "tok",
        SENTRY_ORG: "exam-org",
        SENTRY_PROJECT: "exam-web",
        VITE_SENTRY_RELEASE: "9cffb64",
      }),
    ).toEqual({
      enabled: true,
      authToken: "tok",
      org: "exam-org",
      project: "exam-web",
      release: "9cffb64",
      sourcemap: "hidden",
      filesToDeleteAfterUpload: "./dist/**/*.map",
    });
  });

  it.each([
    [
      "VITE_SENTRY_RELEASE",
      {
        SENTRY_AUTH_TOKEN: "tok",
        SENTRY_ORG: "exam-org",
        SENTRY_PROJECT: "exam-web",
      },
    ],
    [
      "SENTRY_ORG",
      {
        SENTRY_AUTH_TOKEN: "tok",
        SENTRY_PROJECT: "exam-web",
        VITE_SENTRY_RELEASE: "9cffb64",
      },
    ],
    [
      "SENTRY_PROJECT",
      {
        SENTRY_AUTH_TOKEN: "tok",
        SENTRY_ORG: "exam-org",
        VITE_SENTRY_RELEASE: "9cffb64",
      },
    ],
  ])("disables source-map uploads when %s is missing", (_key, env) => {
    expect(resolveSentryUpload(env)).toEqual({ enabled: false });
  });
});

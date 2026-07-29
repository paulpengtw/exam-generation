export type SentryUploadConfig =
  | { enabled: false }
  | {
      enabled: true;
      authToken: string;
      org: string;
      project: string;
      release: string;
      sourcemap: "hidden";
      filesToDeleteAfterUpload: string;
    };

/**
 * Resolve Sentry source-map upload settings from the supplied build env.
 * Uploads require every symbolication value, including the same release
 * identifier stamped into browser events through VITE_SENTRY_RELEASE.
 */
export function resolveSentryUpload(
  env: Record<string, string | undefined>,
): SentryUploadConfig {
  const authToken = env.SENTRY_AUTH_TOKEN;
  const org = env.SENTRY_ORG;
  const project = env.SENTRY_PROJECT;
  const release = env.VITE_SENTRY_RELEASE;
  if (!authToken || !org || !project || !release) return { enabled: false };

  return {
    enabled: true,
    authToken,
    org,
    project,
    release,
    sourcemap: "hidden",
    filesToDeleteAfterUpload: "./dist/**/*.map",
  };
}

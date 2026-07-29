export function maybeTriggerE2eCrash(): void {
  if (!import.meta.env.VITE_IS_STAGING) {
    return;
  }

  const searchParams = new URLSearchParams(window.location.search);
  if (!searchParams.has("e2e-crash")) {
    return;
  }

  setTimeout(() => {
    function e2eCrashProbe(): never {
      throw new Error("e2e-crash: deliberate staging test error");
    }

    e2eCrashProbe();
  }, 0);
}

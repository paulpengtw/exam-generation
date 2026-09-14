// Injected through ego-browser Page.evaluate after authentication.
// Observe only parameter/history endpoints. Never copy request headers,
// cookies, storage, auth URLs, generated questions, or prompt contents.
export function installCapture() {
  if (window.__historyReplay756) return;
  const capture = window.__historyReplay756 = {
    startedAt: new Date().toISOString(),
    phase: "math-original",
    requests: [],
  };
  const originalFetch = window.fetch;
  window.fetch = async function(input, init) {
    const url = new URL(typeof input === "string" ? input : input.url, location.origin);
    const allowed = url.origin === location.origin && (
      url.pathname === "/api/generate/resolve" ||
      url.pathname === "/api/generate" ||
      /^\/api\/history(?:\/[^/]+)?$/.test(url.pathname)
    );
    if (!allowed) return originalFetch.call(this, input, init);
    const entry = {
      phase: capture.phase,
      at: new Date().toISOString(),
      path: url.pathname,
      method: init?.method || "GET",
      query: [...url.searchParams.entries()],
    };
    if (url.pathname === "/api/generate/resolve" && typeof init?.body === "string") {
      entry.request = JSON.parse(init.body);
    }
    capture.requests.push(entry);
    const response = await originalFetch.call(this, input, init);
    entry.status = response.status;
    if (url.pathname === "/api/generate") {
      entry.streamEvents = [];
      (async () => {
        const reader = response.clone().body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (true) {
          const {done, value} = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, {stream:true}).replace(/\r\n/g, "\n");
          let boundary;
          while ((boundary = buffer.indexOf("\n\n")) >= 0) {
            const chunk = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            const event = chunk.match(/^event: ?(.*)$/m)?.[1];
            if (!["started", "question", "verified", "complete", "done", "error", "record_saved"].includes(event)) continue;
            const raw = chunk.match(/^data: ?(.*)$/m)?.[1];
            let data;
            try { data = JSON.parse(raw); } catch { continue; }
            const safe = {};
            for (const key of ["run_id", "record_id", "generation_log_id", "question_id", "index", "count", "total", "status", "error", "message", "passed", "completed", "failed"]) {
              if (data?.[key] !== undefined) safe[key] = data[key];
            }
            entry.streamEvents.push({at:new Date().toISOString(), event, data:safe});
          }
        }
        entry.streamEndedAt = new Date().toISOString();
      })().catch(error => { entry.captureError = String(error); });
    } else {
      response.clone().json().then(data => {
        if (url.pathname === "/api/generate/resolve") entry.response = data;
        else if (url.pathname === "/api/history") {
          entry.response = {
            total: data.total,
            items: (data.items || data.records || []).map(row => Object.fromEntries(
              ["id", "subject", "question_id", "status", "created_at"].map(key => [key, row[key]])
            )),
          };
        } else {
          entry.response = Object.fromEntries(
            ["id", "subject", "question_id", "status", "created_at", "params_json", "error"].map(key => [key, data[key]])
          );
        }
      }).catch(error => { entry.captureError = String(error); });
    }
    return response;
  };
}

// Metadata-only observation: no credentials, prompts, answers, or generated text.
export function installCapture() {
  if (window.__accept789) return;
  const capture = window.__accept789 = { startedAt: new Date().toISOString(), requests: [] };
  const original = window.fetch;
  window.fetch = async function(input, init) {
    const url = new URL(typeof input === "string" ? input : input.url, location.origin);
    if (url.origin !== location.origin || url.pathname !== "/api/generate") return original.call(this, input, init);
    const entry = { at: new Date().toISOString(), method: init?.method || "GET", counts: {}, events: [] };
    capture.requests.push(entry);
    const response = await original.call(this, input, init);
    entry.status = response.status;
    if (!response.ok) return response;
    (async () => {
      const reader = response.clone().body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
        let end;
        while ((end = buffer.indexOf("\n\n")) >= 0) {
          const chunk = buffer.slice(0, end); buffer = buffer.slice(end + 2);
          const event = chunk.match(/^event: ?(.*)$/m)?.[1];
          if (!event) continue;
          entry.counts[event] = (entry.counts[event] || 0) + 1;
          if (!['started', 'result', 'done', 'error', 'llm_request', 'llm_response', 'stage'].includes(event)) continue;
          const raw = chunk.split("\n").filter(x => x.startsWith("data:")).map(x => x.slice(5).trimStart()).join("\n");
          let data = {}; try { data = JSON.parse(raw); } catch { continue; }
          const safe = {};
          for (const key of ['run_id', 'record_id', 'generation_log_id', 'question_id', 'index', 'count', 'total', 'status', 'passed', 'agent', 'purpose', 'stage'])
            if (data?.[key] !== undefined) safe[key] = data[key];
          entry.events.push({ at: new Date().toISOString(), event, ...safe });
        }
      }
      entry.endedAt = new Date().toISOString();
    })().catch(error => { entry.captureError = error.name; });
    return response;
  };
}

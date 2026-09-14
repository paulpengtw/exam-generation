// In-page observation only. Never exports authentication, prompt or question text.
export function installCapture() {
  if (window.__accept766) return;
  const cap = window.__accept766 = {startedAt: new Date().toISOString(), phase:"ss-original", requests:[], sentry:[]};
  const original = window.fetch;
  window.fetch = async function(input, init) {
    const url = new URL(typeof input === "string" ? input : input.url, location.origin);
    const api = url.origin === location.origin && (/^\/api\/generate(?:\/resolve|\/preview)?$/.test(url.pathname) || /^\/api\/history(?:\/[^/]+)?$/.test(url.pathname));
    if (!api) return original.call(this,input,init);
    const e = {phase:cap.phase, at:new Date().toISOString(), path:url.pathname, method:init?.method || "GET", targetBytes:new TextEncoder().encode(url.pathname+url.search).length};
    if (typeof init?.body === "string") {
      e.request = JSON.parse(init.body);
      e.bodyBytes = new TextEncoder().encode(init.body).length;
      const query = new URLSearchParams();
      for (const [k,v] of Object.entries(e.request)) {
        if (v == null) continue;
        if (Array.isArray(v)) v.forEach(x=>query.append(k,String(x)));
        else query.set(k,String(v));
      }
      e.equivalentGetTargetBytes = new TextEncoder().encode(url.pathname+"?"+query).length;
    }
    cap.requests.push(e);
    let response;
    try { response = await original.call(this,input,init); }
    catch(error) {e.fetchError=error.name; throw error;}
    e.status=response.status;
    e.contentType=response.headers.get("content-type");
    if(url.pathname === "/api/generate" && response.ok) {
      e.events=[]; e.eventCounts={};
      (async()=>{
        const reader=response.clone().body.getReader(); const decoder=new TextDecoder(); let buffer="";
        while(true) {
          const {done,value}=await reader.read(); if(done)break;
          buffer+=decoder.decode(value,{stream:true}).replace(/\r\n/g,"\n");
          let boundary;
          while((boundary=buffer.indexOf("\n\n"))>=0) {
            const chunk=buffer.slice(0,boundary); buffer=buffer.slice(boundary+2);
            const event=chunk.match(/^event: ?(.*)$/m)?.[1]; if(!event)continue;
            e.eventCounts[event]=(e.eventCounts[event]||0)+1;
            if(!["started","result","question","verified","complete","done","error","record_saved"].includes(event))continue;
            const raw=chunk.split("\n").filter(x=>x.startsWith("data:")).map(x=>x.slice(5).trimStart()).join("\n");
            let data={};try {if(raw)data=JSON.parse(raw);}catch{e.parseErrors=(e.parseErrors||0)+1;continue;}
            const safe={};
            for(const k of ["run_id","record_id","generation_log_id","question_id","index","count","total","status","passed","completed","failed"])
              if(data?.[k]!==undefined)safe[k]=data[k];
            if(event==="error") safe.error=String(data?.error||data?.message||"").slice(0,400);
            e.events.push({at:new Date().toISOString(),event,data:safe});
          }
        }
        e.streamEndedAt=new Date().toISOString();
      })().catch(error=>{e.streamCaptureError=error.name;});
    } else response.clone().json().then(data=>{
      if(url.pathname==="/api/generate/resolve")e.response=data;
      else if(!response.ok) e.rejection={detail:data.detail};
      else if(url.pathname==="/api/generate/preview")e.previewKeys=Object.keys(data);
      else if(url.pathname==="/api/history")e.response={total:data.total,items:(data.items||data.records||[]).map(r=>Object.fromEntries(["id","subject","question_id","status","created_at"].map(k=>[k,r[k]])))};
      else e.response=Object.fromEntries(["id","subject","question_id","status","created_at","params_json"].map(k=>[k,data[k]]));
    }).catch(error=>{e.captureError=error.name;});
    return response;
  };
}

export function observeSentry() {
  const cap = window.__accept766;
  const client=window.__SENTRY__?.[window.__SENTRY__.version]?.defaultCurrentScope?.getClient();
  if(!client || cap.sentryObserved)return;
  cap.sentryObserved=true;
  cap.sentryOptions={release:client.getOptions().release,dataCollection:client.getOptions().dataCollection};
  const transport=client.getTransport(), send=transport.send;
  transport.send=function(envelope){
    const serialized=JSON.stringify(envelope);
    const items=envelope[1]||[];
    cap.sentry.push({at:new Date().toISOString(),types:items.map(x=>x[0]?.type),containsInstructionMarker:serialized.includes("驗收標記七六六"),requestBodyFields:items.filter(x=>x[1]?.request?.data!=null).length});
    return send.call(this,envelope);
  };
}

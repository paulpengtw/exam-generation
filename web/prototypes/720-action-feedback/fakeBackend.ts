import { readFileSync } from "node:fs";
import type { IncomingMessage, ServerResponse } from "node:http";
import type { Plugin } from "vite";

/** Throwaway #727 backend. No Python, network calls, database, or LLM credentials. */
type Data = Record<string, unknown>;
interface Entry {
  value: string;
  instruction: string;
  科目?: string;
  admitted_by?: Record<string, string[]>;
}
interface Schema {
  情境: Entry[];
  題型: Entry[];
  科目: Entry[];
  內容領域: Entry[];
  認知歷程: Entry[];
  核心素養: Entry[];
  學習內容: Entry[];
  學習表現: Entry[];
  題目內容類型: Entry[];
}
interface Resolution { payload: Data; drawn: string[]; cleared: string[] }
interface HistoryRecord {
  id: string;
  subject: string;
  question_id: string;
  created_at: string;
  status: "completed";
  error: null;
  params_json: Data;
  question_json: Data;
  verification_trail: Data[];
  figure_policy_trail: Data[];
  reference_example_record: { disabled: boolean; entries: Data[] };
}

const schema = JSON.parse(readFileSync(new URL("./socialSchema.json", import.meta.url), "utf8")) as Schema;
const chartPng = readFileSync(new URL("./community-budget.png", import.meta.url)).toString("base64");
const delay = (ms: number) => new Promise<void>((done) => setTimeout(done, ms));
const record = (value: unknown): Data => value !== null && typeof value === "object" && !Array.isArray(value)
  ? value as Data : {};
const strings = (value: unknown): string[] => Array.isArray(value)
  ? value.filter((item): item is string => typeof item === "string")
  : typeof value === "string" && value.length > 0 ? [value] : [];
const blank = (value: unknown) => value == null || value === "" || (Array.isArray(value) && value.length === 0);
const numeric = (value: unknown, fallback: number) => Number.isFinite(Number(value)) && !blank(value)
  ? Number(value) : fallback;
const values = (entries: Entry[]) => entries.map((entry) => entry.value);

function rows(value: unknown): Data[] {
  if (typeof value === "string") {
    try { return rows(JSON.parse(value) as unknown); } catch { return []; }
  }
  return Array.isArray(value) ? value.map(record) : [];
}

function hash(value: string): number {
  return Array.from(value).reduce((n, char) => ((n * 31) + char.charCodeAt(0)) >>> 0, 0);
}

function resolve(body: Data): Resolution {
  const payload = { ...(body.payload ? record(body.payload) : body) };
  const redraws = record(body.redraws ?? payload.redraws);
  delete payload.redraws;
  const drawn: string[] = [];
  const cleared: string[] = [];
  const seed = numeric(payload.seed, 720);
  if (blank(payload.seed)) drawn.push("seed");
  payload.seed = seed;
  payload.subject = "social_studies";
  payload.count = Math.max(1, Math.min(100, Math.floor(numeric(payload.count, 1))));

  function complete(source: Data, prefix: string, index: number): Data {
    const completed = { ...source };
    const localSeed = numeric(completed.seed, seed + index);
    if (blank(completed.seed)) {
      completed.seed = localSeed;
      drawn.push(`${prefix}seed`);
    }
    // ceil(counter / 2) gives 0,1,1,2,2…: odd redraws change; even redraws repeat.
    // Stable keyed streams keep a sibling redraw from consuming another field's draw.
    function draw<T>(field: string, pool: T[], initialOffset?: number): T {
      const counter = Math.max(0, numeric(redraws[`${prefix}${field}`], 0));
      const offset = initialOffset ?? hash(`${localSeed}:${field}`);
      return pool[(offset + Math.ceil(counter / 2)) % pool.length];
    }
    function fill(field: string, canonical: string, pool: unknown[], list = false, initialOffset?: number) {
      if (blank(completed[field])) {
        const value = draw(canonical, pool, initialOffset);
        completed[field] = list ? [value] : value;
        drawn.push(`${prefix}${canonical}`);
      } else if (list) completed[field] = strings(completed[field]);
    }
    fill("grade", "grade", [7, 8, 9]);
    fill("context", "情境", values(schema.情境), true, 1);
    completed.set_type = "題組題";
    fill("subject_filter", "科目", ["公民與社會", "跨科", "歷史", "地理"], true, 0);
    fill("content_domain", "內容領域", values(schema.內容領域), false, 2);
    fill("content_type", "題目內容類型", values(schema.題目內容類型).filter((value) => value !== "customized"));
    fill("core_competency", "核心素養", values(schema.核心素養), true);
    fill("sub_question_count", "sub_question_count", [3, 4, 5, 6, 7], false, 0);
    completed.sub_question_count = Math.max(3, Math.min(7, Math.floor(numeric(completed.sub_question_count, 3))));
    completed.difficulty ??= "medium";
    completed.target_surface ??= "紙本";
    const selectedSubjects = strings(completed.subject_filter);
    const domainLimited = selectedSubjects.some((subject) => subject === "公民與社會" || subject === "跨科");
    const admitted = (entry: Entry, content: boolean) => {
      const subjects = entry.admitted_by?.科目;
      if (subjects && !selectedSubjects.some((subject) => subjects.includes(subject))) return false;
      const domains = entry.admitted_by?.內容領域;
      return !content || !domainLimited || (domains?.includes(String(completed.content_domain)) ?? false);
    };
    const contentPool = values(schema.學習內容.filter((entry) => admitted(entry, true)));
    const performancePool = values(schema.學習表現.filter((entry) => admitted(entry, false)));
    function curriculum(target: Data, field: string, path: string, pool: string[]) {
      const current = strings(target[field]);
      if (current.length && current.every((code) => pool.includes(code))) return;
      if (current.length) cleared.push(`${prefix}${path}`);
      target[field] = [draw(path, pool)];
      drawn.push(`${prefix}${path}`);
    }
    curriculum(completed, "learning_content", "學習內容", contentPool);
    curriculum(completed, "learning_performance", "學習表現", performancePool);
    const configs = rows(completed.subquestion_configs);
    const questionTypes = values(schema.題型).filter((type) => completed.target_surface === "數位" || !["拖放題", "滑桿題"].includes(type));
    completed.subquestion_configs = JSON.stringify(Array.from({ length: Number(completed.sub_question_count) }, (_, slot) => {
      const config = { ...configs[slot] };
      const path = `subquestion_configs[${slot}].`;
      if (blank(config.question_type)) {
        config.question_type = draw(`${path}question_type`, questionTypes, slot === 2 ? 1 : 0);
        drawn.push(`${prefix}${path}question_type`);
      }
      if (blank(config.cognitive_process ?? config.認知歷程)) {
        config.cognitive_process = draw(`${path}認知歷程`, values(schema.認知歷程), slot);
        drawn.push(`${prefix}${path}認知歷程`);
      }
      curriculum(config, "learning_content", `${path}learning_content`, contentPool);
      curriculum(config, "learning_performance", `${path}learning_performance`, performancePool);
      config.instruction ??= "";
      config.question_word_limit ??= numeric(completed.question_word_limit, 120);
      config.option_word_limit ??= numeric(completed.option_word_limit, 35);
      config.content_type ??= completed.content_type;
      config.difficulty ??= completed.difficulty;
      return config;
    }));
    // Social group types live on the individual slots, as on the production resolver.
    completed.q_type = [];
    return completed;
  }

  if (payload.per_question_params !== undefined || Number(payload.count) > 1) {
    const existing = rows(payload.per_question_params);
    const inherited = Object.fromEntries(Object.entries(payload).filter(([key]) => ![
      "subject", "count", "per_question_params", "drawn", "seed",
    ].includes(key)));
    payload.per_question_params = JSON.stringify(Array.from({ length: Number(payload.count) }, (_, index) =>
      complete({ ...inherited, ...existing[index] }, `per_question_params[${index}].`, index)));
  } else Object.assign(payload, complete(payload, "", 0));
  return { payload, drawn: [...new Set(drawn)], cleared: [...new Set(cleared)] };
}

const topics = ["社區預算應如何回應不同居民的需求？", "圖書館延長開放時間，應如何取得共識？", "校園公共空間應如何分配？"];

function makeQuestion(id: string, index: number, params: Data): Data {
  const configs = rows(params.subquestion_configs);
  const learningItems = (codes: unknown, pool: Entry[]) => strings(codes).map((code) => ({
    編碼: code, 說明: pool.find((entry) => entry.value === code)?.instruction ?? code,
  }));
  const subquestions = Array.from({ length: numeric(params.sub_question_count, 3) }, (_, slot) => {
    const config = configs[slot] ?? {};
    const kind = String(config.question_type ?? (slot === 2 ? "開放式建構反應題" : "選擇題"));
    const open = kind === "開放式建構反應題";
    const sub: Data = {
      id: `${id}-sub-${slot + 1}`, 序號: slot + 1, 年級: numeric(params.grade, 7),
      科目: strings(params.subject_filter).length ? strings(params.subject_filter) : ["公民與社會"],
      核心素養: strings(params.core_competency),
      學習內容: learningItems(config.learning_content ?? params.learning_content, schema.學習內容),
      學習表現: learningItems(config.learning_performance ?? params.learning_performance, schema.學習表現),
      認知歷程: config.cognitive_process ?? schema.認知歷程[slot % schema.認知歷程.length].value,
      出題概念: open ? "整合資料與公共參與原則，提出具體建議。" : "由調查資料判讀居民需求，辨識公共參與的意義。",
      題型: kind,
      題目: open
        ? "請結合調查結果與說明會意見，提出一項兼顧多數與少數居民需求的預算分配建議，並說明理由。"
        : slot % 2 === 0
          ? "下列哪一項最能說明召開居民說明會的目的？\n(A) 讓居民表達意見並討論公共需求\n(B) 保證每位居民得到相同金額\n(C) 由少數人直接決定所有支出\n(D) 取消原有的預算審議程序"
          : "依據調查結果，下列敘述何者正確？\n(A) 公園方案獲得過半數支持\n(B) 圖書館方案的支持者最少\n(C) 公園方案獲得的支持最多\n(D) 三項方案的支持人數相同",
      答案: open ? "可優先改善公園，同時保留部分預算延長圖書館開放時間；方案兼顧主要需求，也回應不同居民的使用情境。" : slot % 2 === 0 ? "A" : "C",
      答案解析: open ? "建議須引用至少一項調查資料，並說明如何透過公開討論兼顧不同群體。" : "說明會提供表達與討論的管道；調查中公園獲得45人支持，最多但未過半數。",
      題目內容類型: "純文字",
    };
    if (open) sub.評分規準 = [
      { code: "2", 規準說明: "引用資料，提出兼顧不同需求且可執行的建議。", 學生作答實例: ["以公園改善為主，也保留圖書館服務經費，並公開說明取捨。"] },
      { code: "1", 規準說明: "有具體建議，但資料運用或理由不足。", 學生作答實例: ["先改善公園，因為支持者最多。"] },
      { code: "0", 規準說明: "未提出相關建議或未作答。", 學生作答實例: ["隨便決定即可。"] },
    ];
    if (kind === "拖放題") {
      sub.題目 = "將居民參與方式配對到對應的目的。";
      sub.interaction = {
        draggables: [{ id: "a", label: "說明會" }, { id: "b", label: "問卷調查" }],
        targets: [{ id: "discussion", label: "交換意見", capacity: 1 }, { id: "survey", label: "蒐集偏好", capacity: 1 }],
        correct_mapping: { a: "discussion", b: "survey" }, exact_match: false, shuffle_draggables: false,
      };
      sub.答案 = "說明會→交換意見；問卷調查→蒐集偏好";
    }
    if (kind === "滑桿題") {
      sub.題目 = "100位受訪居民中，有多少百分比支持公園方案？";
      sub.interaction = { min: 0, max: 100, step: 1, unit: "%", correct_value: 45, tolerance: 0, show_ticks: true };
      sub.答案 = "45%";
    }
    return sub;
  });
  return {
    id, 情境: strings(params.context).length ? strings(params.context) : ["公共"], 題型種類: "題組題", 題型: "題組題",
    內容領域: params.content_domain ?? "Civic Participation", 題目內容類型: "graphs/charts/tables",
    核心問題: params.core_question ?? topics[index % topics.length],
    文本: "青溪社區有一筆公共建設預算。里辦公處調查100位居民，45人優先選擇改善公園、30人選擇延長圖書館開放時間，25人選擇增設運動設施。\n\n說明會上，有居民希望優先照顧最多人的需求，也有人提醒，晚間使用圖書館的學生與輪班工作者較難參與白天的會議。工作小組決定公開調查結果，增加線上意見管道，再討論預算分配。",
    取材來源: ["為本操作回饋原型編寫的虛構社區資料。"],
    題目: [], 正確解題分析: [], subquestions,
    metadata: { prototype: true, coverage_mode_used: params.coverage_mode ?? "balanced" },
  };
}

function verification(questionId: string, passed: boolean): Data {
  return {
    code: "verification_trail", kind: "verification", question_id: questionId, passed,
    details: passed ? "答案與資料相符；已釐清最多與過半數的差異。" : "第二小題解析應明確區分『最多』與『過半數』。",
    my_answer: "A；C；依評分規準", provided_answer: "A；C；依評分規準", answer_match: true,
    chart_verification: { chart_data_match: true, chart_labels_correct: true, chart_details: "45、30、25與文本一致。" },
    model: "claude-opus-4-6", timestamp: new Date().toISOString(),
  };
}

function imageQuestion(question: Data): Data {
  return { ...question, image_base64: chartPng, chart_spec: { type: "bar", title: "居民優先方案調查", labels: ["公園", "圖書館", "運動設施"], values: [45, 30, 25] } };
}

function historyRecord(id: string, question: Data, params: Data, createdAt = new Date().toISOString()): HistoryRecord {
  return {
    id, subject: "social_studies", question_id: String(question.id), created_at: createdAt,
    status: "completed", error: null, params_json: params, question_json: question,
    verification_trail: [verification(String(question.id), true)], figure_policy_trail: [],
    reference_example_record: { disabled: true, entries: [] },
  };
}

function json(response: ServerResponse, value: unknown, status = 200) {
  if (response.destroyed || response.writableEnded) return;
  response.writeHead(status, { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" });
  response.end(JSON.stringify(value));
}

async function readBody(request: IncomingMessage): Promise<Data> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += buffer.length;
    if (size > 2_000_000) throw new Error("原型請求內容過大。");
    chunks.push(buffer);
  }
  const text = Buffer.concat(chunks).toString("utf8");
  return text ? record(JSON.parse(text) as unknown) : {};
}

function stream(response: ServerResponse) {
  response.writeHead(200, {
    "Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-cache, no-transform",
    Connection: "keep-alive", "X-Accel-Buffering": "no",
  });
  response.flushHeaders();
  return (event: string, value: unknown) => {
    if (response.destroyed || response.writableEnded) return;
    const data = typeof value === "string" ? value : JSON.stringify(value);
    response.write(`event: ${event}\ndata: ${data}\n\n`);
  };
}

function forced(url: URL, kind: string) {
  return url.searchParams.getAll("fail").some((value) => [kind, "1", "true", "all"].includes(value));
}

/** Import { fakeBackend } (or the default export) from Vite config. */
export function fakeBackend(): Plugin {
  const history = new Map<string, HistoryRecord>();
  const modifications = new Map<string, { recordId: string; body: Data; fail: boolean }>();
  let runNumber = 0;
  let modificationNumber = 0;

  async function generate(response: ServerResponse, payload: Data, fail: boolean) {
    const send = stream(response);
    const total = Number(payload.count);
    const thisRun = ++runNumber;
    const batchRows = rows(payload.per_question_params);
    const alive = () => !response.destroyed && !response.writableEnded;
    const pipeline = (eventName: string, extra: Data = {}) => send("pipeline", { event_name: eventName, ts: Date.now() / 1000, total, ...extra });
    send("started", { status: "started", total });
    await delay(3000);
    if (!alive()) return;
    pipeline("pipeline_start");

    async function questionRun(index: number) {
      await delay((index % 3) * 650);
      if (!alive()) return;
      const params = batchRows[index] ?? payload;
      const id = `proto-run-${thisRun}-${index + 1}`;
      let question = makeQuestion(id, index, params);
      const subquestions = rows(question.subquestions);
      const stage = (agent: string, name: string, status: string) => send("stage", {
        type: "stage", agent, stage: name, status, index, question_id: id, ts: Date.now() / 1000,
      });
      const request = (agent: string, purpose: string, description: string) => {
        send("llm_request", { agent, purpose, index, model: "gemini-3.1-pro-preview", messages: [{ role: "user", content: description }], params: { reasoning_effort: "high" } });
      };
      const chunks = async (agent: string, purpose: string, content: string) => {
        for (const text of ["先核對題組的資料與限制。", "\n依學生的閱讀情境安排具體問題。", "\n檢查答案是否能由文本支持。"] ) {
          await delay(220);
          if (!alive()) return;
          send("llm_thinking", { agent, purpose, index, text });
        }
        for (const text of content.match(/.{1,30}/gs) ?? [content]) {
          await delay(100);
          if (!alive()) return;
          send("llm_content", { agent, purpose, index, text });
        }
      };
      const finishCall = (agent: string, purpose: string) => send("llm_response", { agent, purpose, index, model: "gemini-3.1-pro-preview", usage: { prompt_tokens: 420, completion_tokens: 180 } });
      const update = (phase: string) => send("question_update", { index, phase, question });
      async function phase(agent: string, name: string, purpose: string, description: string) {
        if (!alive()) return;
        const startedAt = Date.now();
        stage(agent, name, "start");
        request(agent, purpose, description);
        await chunks(agent, purpose, `${description}\n${String(question.核心問題)}\n資料來源：虛構社區調查。`);
        await delay(Math.max(0, 2000 - (Date.now() - startedAt)));
        if (!alive()) return;
        finishCall(agent, purpose);
        stage(agent, name, "end");
      }

      pipeline("question_start", { index, question_id: id });
      send("progress", `第 ${index + 1} 題：文本生成中`);
      await phase("generator", "llm_generate", "text_generate", "以公共參與為主題撰寫共享文本與三題規劃。");
      if (!alive()) return;
      question = { ...question, subquestions: [] };
      update("draft");
      send("plan", { index, sub_question_total: subquestions.length });
      const subStart = Date.now();
      for (let slot = 0; slot < subquestions.length; slot++) {
        stage(`sub_generator#${slot + 1}`, "llm_generate", "start");
        request(`sub_generator#${slot + 1}`, `sub_generate_${slot + 1}`, `撰寫第 ${slot + 1} 小題，保留已解析的題型與課綱設定。`);
      }
      for (let slot = 0; slot < subquestions.length; slot++) {
        const agent = `sub_generator#${slot + 1}`;
        const purpose = `sub_generate_${slot + 1}`;
        await delay(Math.max(0, 2000 * (slot + 1) / subquestions.length - (Date.now() - subStart)));
        if (!alive()) return;
        send("llm_thinking", { agent, purpose, index, text: "逐一比對文本資訊，辨識常見誤解。" });
        send("llm_content", { agent, purpose, index, text: String(subquestions[slot].題目) });
        if (fail && index === 0 && slot === 1) {
          stage(agent, "llm_generate", "error");
          send("error", { code: "prototype_run_failed", message: "第 1 題的子題生成中斷。這是原型的強制失敗；關閉強制失敗後可重新產生。" });
          response.end();
          return;
        }
        finishCall(agent, purpose);
        stage(agent, "llm_generate", "end");
        question = { ...question, subquestions: subquestions.slice(0, slot + 1) };
        update("draft");
      }
      await phase("image_agent", "render_image", "image_generate", "產生與文本一致的45、30、25人調查圖。");
      if (!alive()) return;
      question = imageQuestion(question);
      update("image");
      send("trail", { code: "verification_trail", kind: "initial", question_id: id, timestamp: new Date().toISOString(), snapshot: question });
      await phase("verifier", "verify", "verify", "獨立作答，核對答案、圖表與課綱代碼。");
      if (!alive()) return;
      const initialVerdict = verification(id, false);
      question = { ...question, verification: initialVerdict };
      send("trail", initialVerdict);
      update("verified");
      await phase("corrector", "correct", "correct", "補充第二小題解析，說明最多不等於過半數。");
      if (!alive()) return;
      const finalVerdict = verification(id, true);
      question = { ...question, verification: finalVerdict };
      send("trail", { code: "verification_trail", kind: "correction", question_id: id, retry_index: 1, model: "gemini-3.1-pro-preview", timestamp: new Date().toISOString(), snapshot: question });
      send("trail", finalVerdict);
      update("corrected");
      history.set(id, historyRecord(id, question, { ...params, subject: "social_studies", count: 1 }));
      send("result", question);
      pipeline("question_end", { index, question_id: id });
    }

    // Match the real server's concurrent workers while keeping batches easy to inspect.
    for (let start = 0; start < total && alive(); start += 3) {
      await Promise.all(Array.from({ length: Math.min(3, total - start) }, (_, offset) => questionRun(start + offset)));
    }
    if (alive()) {
      pipeline("pipeline_end");
      send("done", { status: "completed", total });
      response.end();
    }
  }

  async function modify(response: ServerResponse, recordId: string, runId: string, fail: boolean) {
    const source = history.get(recordId);
    if (!source) { json(response, { detail: "找不到這筆原型歷史紀錄。" }, 404); return; }
    const send = stream(response);
    const alive = () => !response.destroyed && !response.writableEnded;
    send("started", { run_id: runId, status: "started" });
    let question = { ...source.question_json };
    const steps = [
      { stage: "modification", step: "修改", agent: "corrector" },
      { stage: "verify", step: "驗證", agent: "verifier" },
      { stage: "correct", step: "修正", agent: "corrector" },
    ];
    for (const [index, step] of steps.entries()) {
      if (!alive()) return;
      send("pipeline", { event_name: `${step.stage}_start`, ...step, ts: Date.now() / 1000 });
      send("stage", { type: "stage", ...step, status: "start", ts: Date.now() / 1000 });
      send("llm_request", { purpose: step.stage, agent: step.agent, model: "gemini-3.1-pro-preview", messages: [{ role: "user", content: "依人工審題註記進行局部修改。" }] });
      await delay(650);
      if (!alive()) return;
      send("llm_thinking", { purpose: step.stage, agent: step.agent, text: "保留原有題型與課綱設定，檢查相關答案。" });
      await delay(650);
      if (!alive()) return;
      if (fail && index === 1) {
        send("stage", { type: "stage", ...step, status: "error", ts: Date.now() / 1000 });
        send("error", { message: "人工審題修正的審題步驟中斷。關閉強制失敗後可重試。" });
        response.end();
        return;
      }
      send("llm_content", { purpose: step.stage, agent: step.agent, text: "已釐清題幹措辭，保留原有資料與答案依據。" });
      await delay(700);
      if (!alive()) return;
      send("llm_response", { purpose: step.stage, agent: step.agent, model: "gemini-3.1-pro-preview" });
      send("stage", { type: "stage", ...step, status: "end", ts: Date.now() / 1000 });
      question = { ...question, 文本: `${String(source.question_json.文本)}\n\n說明：每位受訪者僅能選擇一個優先方案。` };
      send("question_update", { index: 0, phase: index === 0 ? "draft" : "corrected", question });
    }
    if (!alive()) return;
    const childId = `${recordId}-${runId}`;
    const verdict = verification(String(question.id), true);
    question = { ...question, verification: verdict };
    history.set(childId, historyRecord(childId, question, source.params_json));
    const result = { record_id: childId, question, ripple_report: ["文本"], verified: true, verification: verdict, failure_details: null };
    send("result", result);
    send("done", result);
    response.end();
  }

  return {
    name: "prototype-720-fake-backend",
    apply: "serve",
    configureServer(server) {
      if (process.env.PROTO_720 !== "1") return;
      for (let index = 0; index < 45; index++) {
        const id = `proto-${String(index + 1).padStart(3, "0")}`;
        const params = resolve({ subject: "social_studies", seed: 720 + index, content_type: "graphs/charts/tables" }).payload;
        const question = imageQuestion(makeQuestion(id, index, params));
        question.verification = verification(id, true);
        history.set(id, historyRecord(id, question, params, new Date(Date.UTC(2026, 8, 14, 8) - index * 3_600_000).toISOString()));
      }
      server.middlewares.use((request, response, next) => {
        const url = new URL(request.url ?? "/", "http://prototype.local");
        const path = url.pathname;
        if (!path.startsWith("/auth/") && !path.startsWith("/api/") && path !== "/health") { next(); return; }
        void (async () => {
          if (path === "/health") { json(response, { status: "ok", prototype: true }); return; }
          if (path === "/auth/me") {
            json(response, { id: "proto-user", email: "reviewer@example.test", created_at: "2026-09-14T00:00:00Z" }); return;
          }
          if (path === "/auth/verify") {
            const encode = (value: unknown) => Buffer.from(JSON.stringify(value)).toString("base64url");
            json(response, { access_token: `${encode({ alg: "HS256", typ: "JWT" })}.${encode({ sub: "proto-user", email: "reviewer@example.test", exp: 4_102_444_800 })}.prototype-only`, token_type: "bearer" }); return;
          }
          if (path === "/auth/magic-link") {
            await readBody(request);
            json(response, { message: "原型登入不寄信。請開啟 /verify?token=x&email=reviewer@example.test" }); return;
          }
          if (path === "/api/schemas") {
            const subject = url.searchParams.get("subject") ?? "social_studies";
            if (subject !== "social_studies") json(response, { detail: "此原型僅提供社會領域；請開啟 /generate/social_studies。" }, 422);
            else json(response, schema);
            return;
          }
          if (path === "/api/models") {
            json(response, { allowed: ["gemini-3.1-pro-preview", "claude-opus-4-6"], effort: { "gemini-3.1-pro-preview": ["low", "medium", "high"], "claude-opus-4-6": ["low", "medium", "high"] }, defaults: { plan: "claude-opus-4-6", execute: "gemini-3.1-pro-preview", verify: "claude-opus-4-6", correct: "", effort_plan: "high", effort_execute: "high", effort_verify: "high", effort_correct: "" } }); return;
          }
          if (path === "/api/plan-core-questions") {
            const body = await readBody(request);
            await delay(600);
            json(response, { candidates: body.topic ? topics.map((topic) => `${String(body.topic)}：${topic}`) : topics }); return;
          }
          if (path === "/api/generate/resolve") {
            const body = await readBody(request);
            await delay(600);
            if (forced(url, "resolve")) json(response, { detail: "參數解析暫時失敗。關閉強制失敗後可重試。" }, 500);
            else json(response, resolve(body));
            return;
          }
          if (path === "/api/generate/preview") {
            const payload = await readBody(request);
            await delay(450);
            const groups = rows(payload.per_question_params);
            json(response, { prompts: Array.from({ length: numeric(payload.count, 1) }, (_, index) => ({ index, system_prompt: "你是108課綱社會領域命題教師。這是固定資料原型的提示預覽。", user_prompt: `請依下列參數規劃共享文本與各小題。\n${JSON.stringify(groups[index] ?? payload, null, 2)}` })) }); return;
          }
          if (path === "/api/generate") {
            await generate(response, resolve(await readBody(request)).payload, forced(url, "run")); return;
          }
          if (path === "/api/history") {
            await delay(600);
            if (forced(url, "history")) { json(response, { detail: "無法載入這一頁歷史紀錄。關閉強制失敗後可重試。" }, 500); return; }
            const subject = url.searchParams.get("subject");
            const all = [...history.values()].filter((item) => !subject || subject === item.subject).sort((a, b) => b.created_at.localeCompare(a.created_at));
            const offset = Math.max(0, numeric(url.searchParams.get("offset"), 0));
            const limit = Math.max(1, numeric(url.searchParams.get("limit"), 20));
            json(response, { total: all.length, items: all.slice(offset, offset + limit).map((item) => ({ id: item.id, subject: item.subject, question_id: item.question_id, created_at: item.created_at, status: item.status, error: null, preview: String(item.question_json.核心問題), verified: true, figure_policy_trail: [] })) }); return;
          }
          const historyMatch = path.match(/^\/api\/history\/([^/]+)(\/download)?$/);
          if (historyMatch) {
            await delay(historyMatch[2] ? 600 : 200);
            if (historyMatch[2] && forced(url, "download")) { json(response, { detail: "無法下載這份 JSON 檔案。關閉強制失敗後可重試。" }, 500); return; }
            const detail = history.get(decodeURIComponent(historyMatch[1]));
            if (!detail) { json(response, { detail: "找不到這筆原型歷史紀錄。" }, 404); return; }
            if (historyMatch[2]) response.setHeader("Content-Disposition", `attachment; filename="${detail.question_id}.json"`);
            json(response, historyMatch[2] ? detail.question_json : detail); return;
          }
          const modification = path.match(/^\/api\/generation-records\/([^/]+)\/modifications(?:\/([^/]+)(?:\/stream)?)?$/);
          if (modification) {
            const recordId = decodeURIComponent(modification[1]);
            if (!modification[2]) {
              const body = await readBody(request);
              if (!history.has(recordId)) { json(response, { detail: "找不到原型來源紀錄。請從歷史紀錄開啟人工審題修正。" }, 404); return; }
              const runId = `mod-${++modificationNumber}`;
              modifications.set(runId, { recordId, body, fail: forced(url, "run") });
              json(response, { run_id: runId, status: "started" }); return;
            }
            const runId = decodeURIComponent(modification[2]);
            const run = modifications.get(runId);
            if (!run || run.recordId !== recordId) { json(response, { detail: "找不到這次原型修改工作。" }, 404); return; }
            await modify(response, recordId, runId, run.fail || forced(url, "run")); return;
          }
          json(response, { detail: `原型未實作此端點：${path}` }, 404);
        })().catch((error: unknown) => {
          if (!response.headersSent) json(response, { detail: error instanceof Error ? error.message : "原型後端錯誤。" }, 500);
          else response.end();
        });
      });
    },
  };
}

export default fakeBackend;

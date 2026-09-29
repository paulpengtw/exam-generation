# Deployment Guide for Teachers

This guide takes you from **"I have nothing"** to **"my school has a working exam-generation website on the internet, with HTTPS, that other teachers can log into."**

It is written for teachers who have never used a command line. Everything in this guide happens inside a web browser. You will not install anything on your own computer.

If at any point a step is unclear, the **Glossary** at the bottom defines every technical word.

---

## 1. What you will have at the end

When you finish this guide:

- A public website URL (for example, `https://examgen-yourschool.up.railway.app` or your own domain `https://examgen.yourschool.tw`).
- A login screen where you and other teachers can sign up.
- A working "Generate Question" page in the browser that creates new Taiwan math exam questions.

> _Screenshot of the finished UI — add here once your deployment is live._

---

## 2. What you will pay

You are paying for hosting and model API usage:

| Service | Cost | What it does |
|---|---|---|
| Railway (hosting) | About **US$5 per month** (Hobby plan) | Runs the website and the database |
| Gemini API | **Pay-as-you-go** (see Google AI Studio pricing) | Generates questions and handles corrections |
| Anthropic API | **Pay-as-you-go** (see Anthropic pricing) | Plans 核心問題 and verifies questions using Opus 4.6 with adaptive thinking |
| Custom domain (optional) | About **US$10–15 per year** | A nicer URL like `examgen.yourschool.tw` |

You can stop and delete everything at any time.

---

## 3. What you need before you start

- A credit or debit card (for Railway, Google AI, and Anthropic billing).
- An email address.
- About **60 minutes** the first time.
- A web browser. That's it.

---

## 4. Step 1 — Get Gemini and Anthropic API keys

An **API key** is a password that lets your website talk to an AI provider. The defaults use Gemini for generation and Claude Opus 4.6 for planning and 驗證, so you need both keys to start.

1. Open `https://aistudio.google.com/apikey` in your browser.
2. Sign in with a Google account.
3. Click **Create API key**.
4. **Copy the key immediately** — it looks like `AIzaSy...`. Paste it into a safe place (Notes app, password manager).
5. Open `https://console.anthropic.com` and create an Anthropic API key.
6. Save that key separately — it looks like `sk-ant-...`. You will enter the Gemini key as `GEMINI_API_KEY` and the Anthropic key as `LLM_API_KEY` in Step 5.

> ⚠️ Treat both keys like passwords. Anyone who has them can make calls charged to the corresponding provider account.

**Optional addition:**
- **OpenAI key** (`sk-...` from `https://platform.openai.com/api-keys`) — needed only if you change the model to a `gpt-*` or o-series model.

---

## 5. Step 2 — Make your own copy of the project on GitHub

**GitHub** is where the project source code lives. To deploy it, Railway needs your own copy of the code (called a **fork**).

1. Open `https://github.com` and click **Sign up**. Create a free account.
2. Open the project page (the link you were given to this guide).
3. In the top-right corner, click the **Fork** button.
4. On the next screen, leave the defaults and click **Create fork**.
5. You now have a copy of the project at `https://github.com/YOUR-USERNAME/exam-generation`.

---

## 6. Step 3 — Sign up for Railway

**Railway** is the hosting service that will run your website.

1. Open `https://railway.com` in your browser.
2. Click **Login** and choose **Login with GitHub**.
3. When asked, **Authorize Railway** to read your GitHub repositories.
4. Click **Subscribe to Hobby Plan** (US$5/month). You will be asked for a credit card.

---

## 7. Step 4 — Create your project on Railway

You will create **three** services inside one Railway project:

1. A **Postgres database** (stores users and generation history).
2. A **backend** service (the API that talks to Claude).
3. A **frontend** service (the website teachers see).

### 7.1 Create the project and add Postgres

1. On the Railway dashboard, click **New Project**.
2. Choose **Deploy from GitHub repo**.
3. Pick your fork: `YOUR-USERNAME/exam-generation`.
4. Railway will create one service automatically and start trying to build it. **Don't worry if it fails now** — it will likely show a "Railpack / No start command detected" error. That's expected; we override the builder in step 7.2.
5. Inside the project, click **+ New** (top right) → **Database** → **Add PostgreSQL**.
6. Wait about 30 seconds for Postgres to finish starting up.

### 7.2 Set up the backend service

The service Railway created in 7.1 will be the **backend**.

1. Click the service Railway auto-created.
2. Go to the **Settings** tab.
3. Rename it to `backend`.
4. Under **Build**:
   - Set **Builder** to **Dockerfile** (not Railpack or Nixpacks).
   - Set **Dockerfile Path** to `Dockerfile.backend`.
   - Leave **Root Directory** blank.
5. Click **Save** / wait for the auto-redeploy to start.
6. Under **Networking**, click **Generate Domain**. Railway will give you a URL like `backend-production-xxxx.up.railway.app`. **Copy this URL** — you will need it. Choose Port `8000`.

### 7.3 Add the frontend service

1. Back on the project page, click **+ New** → **GitHub Repo** → pick the same fork.
2. Rename the new service to `frontend`.
3. Go to **Settings** → **Build**:
   - Set **Builder** to **Dockerfile**.
   - Set **Dockerfile Path** to `web/Dockerfile`.
   - Leave **Root Directory** blank.
4. Under **Networking**, click **Generate Domain**. Railway gives you a URL like `frontend-production-yyyy.up.railway.app`. **Copy this URL** — this is the website your teachers will visit. Choose Port `80`.

---

## 8. Step 5 — Fill in the secret settings

Each service needs configuration values called **environment variables**. Think of them as labelled boxes the program reads when it starts up.

### 8.1 Settings for the backend service

Open the **backend** service, click the **Variables** tab, and add the following one by one. Click **+ New Variable** for each row. Both `GEMINI_API_KEY` and `LLM_API_KEY` are needed for the default configuration.

| Variable name | Value to type | What it is |
|---|---|---|
| `GEMINI_API_KEY` | The `AIzaSy...` key from Step 1 | Required for the default 執行模型 (`gemini-3.1-pro-preview`) |
| `LLM_MODEL_PLAN` | `claude-opus-4-6` | Which model handles planning |
| `LLM_MODEL_EXECUTE` | `gemini-3.1-pro-preview` | Which model generates questions |
| `LLM_MODEL_VERIFY` | `claude-opus-4-6` | Which model handles 驗證; explicitly empty follows the execute model |
| `LLM_MODEL_CORRECT` | *(leave blank)* | 修正 inherits the execute model unless overridden |
| `LLM_EFFORT_PLAN` | `high` | Planning effort |
| `LLM_EFFORT_EXECUTE` | `high` | Execution effort; Gemini supports `low`, `medium`, and `high` |
| `LLM_EFFORT_VERIFY` | `high` | 驗證 effort; explicitly empty inherits execute effort |
| `LLM_EFFORT_CORRECT` | *(leave blank)* | 修正 inherits execute effort unless overridden |
| `LLM_API_KEY` | An Anthropic `sk-ant-...` key | Required for the default plan and 驗證 model (`claude-opus-4-6`) and for the web-search fact-check feature |
| `LLM_BASE_URL` | `https://api.anthropic.com/v1` | Anthropic API endpoint (leave as default if setting `LLM_API_KEY`) |
| `OPENAI_API_KEY` | An OpenAI `sk-...` key *(optional)* | Required only if using a `gpt-*` or o-series model |
| `LLM_RATE_LIMIT_DELAY` | `2` | Wait 2 seconds between Claude calls (avoids rate-limit errors) |
| `LLM_TEMPERATURE` | (unset) | Optional sampling temperature; leave unset to use the provider default. Ignored for models that reject sampling params. |
| `JWT_SECRET` | A long random string (see below) | Used to sign login tokens |
| `JWT_EXPIRE_DAYS` | `7` | Keeps each login token valid for 7 days |
| `SESSION_RENEWAL_THRESHOLD_MINUTES` | `360` | Renews a login session when less than 360 minutes remain on the token |
| `FRONTEND_URL` | The frontend URL you copied in Step 7.3, with `https://` in front | Tells the backend which website is allowed to call it |
| `RELEASE_AUTHORITY_URL` | `https://<your-gateway-domain>/release/policy.json` | The backend reads the live controller policy through the independent gateway on every generation request |
| `RELEASE_AUTHORITY_PATH` | *(optional local path)* | Alternative for deployments where the backend can read a local policy file; ignored when `RELEASE_AUTHORITY_URL` is set |
| `RELEASE_ENVIRONMENT` | `production` | Must match the controller's policy environment; a mismatch fails closed |
| `EMAIL_BACKEND` | `console` | `console` prints magic-link login emails to backend logs — fine for your own first login; switch to `ses` after following **Step 13** so other teachers receive real emails |
| `EMAIL_WHITELIST` | *(leave blank for now)* | Comma-separated list of email addresses (or `*@domain` wildcards) that are allowed to request a magic link. Leave empty to allow anyone who knows the URL to sign up. Set to `*@yourschool.tw` (for example) to restrict sign-ups to your school domain. |
| `SENTRY_DSN` | *(leave blank, or paste the backend project's DSN)* | Sends backend errors and traces to Sentry. Leave it unset or blank to disable backend Sentry completely. |
| `SENTRY_ENVIRONMENT` | `production` (or `staging`) | Tags backend Sentry data with the deployment environment. |
| `SENTRY_RELEASE` | *(leave blank on Railway; set on other platforms)* | Tags every backend Sentry event with a release identifier so errors map to a specific build. On Railway the value is auto-detected from `RAILWAY_GIT_COMMIT_SHA`, so this variable is only needed when you want to override that value or when deploying on a platform that does not set `RAILWAY_GIT_COMMIT_SHA`. Leave unset to let the backend fall back to the platform commit SHA, or leave both unset to omit the release tag entirely. |

The model and effort values above are the code defaults when their variables are
unset. Opus 4.6 calls enable adaptive thinking with a 16,384-token output ceiling
shared by thinking and the response; `LLM_TEMPERATURE` is ignored for this model.
Planning and 驗證 therefore spend thinking tokens at Opus output rates.

Set exactly one of `RELEASE_AUTHORITY_URL` or `RELEASE_AUTHORITY_PATH` for the
backend. `RELEASE_AUTHORITY_URL` takes precedence when both are present. If
neither is set, generation fails closed with a retryable `503 AUTHORITY_UNAVAILABLE`;
the backend does not assume that a separately deployed
frontend's `web/dist` directory is available locally.

**How to generate `JWT_SECRET`:** open `https://passwordsgenerator.net` in a new tab, set length to 64, click **Generate**, and paste the result.

#### Connecting the database

You also need to tell the backend how to reach the Postgres database you added in 7.1.

1. Still on the **backend** Variables tab, click **+ New Variable**.
2. Type `DATABASE_URL` for the name.
3. For the value, click the small **Reference** dropdown next to the value box.
4. Pick **Postgres → DATABASE_URL** from the list. Railway will automatically wire the two services together.
5. Click **Add**.

After Postgres connects, Railway will tell you the URL starts with `postgres://...`. The backend code expects `postgresql+asyncpg://...`, so:

6. Click the pencil icon next to `DATABASE_URL` you just added.
7. At the start of the value, change `postgres://` to `postgresql+asyncpg://`.
8. Click **Save**.

The backend service should automatically redeploy. Wait about 1-2 minutes.

### 8.2 Settings for the frontend service

Open the **frontend** service, click **Variables**, and add:

| Variable name | Value to type | What it is |
|---|---|---|
| `BACKEND_HOST` | The backend hostname from Step 7.2 — **no** `https://`, **no** trailing slash (e.g. `backend-production-xxxx.up.railway.app`) | Tells the frontend's web server where to forward API calls |
| `BACKEND_SCHEME` | `https` | Use HTTPS when forwarding to the backend |

The frontend will redeploy. Wait 1-2 minutes.

### 8.3 Docker Compose

The included `docker-compose.yml` wires the backend directly to the gateway
with `RELEASE_AUTHORITY_URL=http://gateway:8000/release/policy.json`. The
frontend nginx `/release/policy.json` and `/build-meta.json` locations proxy to
that same gateway, so browser version reporting and backend generation
admission cannot observe different artifacts. If you override the backend
environment, point `RELEASE_AUTHORITY_URL` at the controller/gateway policy
route (or use a readable `RELEASE_AUTHORITY_PATH` for a deliberately local
fixture). Leaving both authority variables unset causes generation to return
the retryable `503 AUTHORITY_UNAVAILABLE`.

---

## 9. Step 6 — Database setup (already automatic!)

Good news: this backend creates its own database tables automatically when it starts up. You do not need to run any commands.

> ⚠️ **Which service to click:** Railway shows tiles for every service — make sure you click the tile you renamed **`backend`** in Step 7.2, not the **Postgres** tile. The Postgres tile has its own logs that look completely different (see below).

You can confirm it worked by clicking the **backend** service → **Deployments** tab → click the latest deployment → look at the logs. You should see lines like:

```
Curriculum loaded: 14 grade entries, target grades [7, 8, 9]
Playwright renderer started
```

**How to tell backend logs apart from Postgres logs:**

| What you see in the logs | Which service you opened |
|---|---|
| `PostgreSQL 18.3 ...` / `listening on IPv4 address` / `database system is ready to accept connections` | ❌ You opened the **Postgres** tile — go back and click **backend** |
| `Curriculum loaded: 14 grade entries, target grades [7, 8, 9]` / `Application startup complete` | ✅ Correct — this is the backend |

If you see an `alembic upgrade failed` line, see **Troubleshooting** below.

---

## 10. Step 7 — Open your website

1. Click the **frontend** service.
2. Click the public URL (the one ending in `.up.railway.app`).
3. The login screen should appear.
4. Click **Sign up** and create your account.
5. Try generating a question.

🎉 **You are live on the internet.** Share the URL with other teachers at your school.

> Until you complete **Step 13** (AWS SES), the backend only prints magic-link login emails to its logs. That means only you — as the person who can open Railway logs — can sign in. Other teachers cannot receive a login email until SES is set up.

> Your Railway project dashboard should show exactly **three tiles**: `Postgres`, `backend`, and `frontend`. If you see a fourth tile named after your GitHub repo (e.g. `exam-generation`) left over from Step 7.1, you can delete it: click that tile → **Settings** → scroll to the bottom → **Delete service**.

---

## 11. Step 8 — Add a custom domain (optional)

A custom domain (like `examgen.yourschool.tw`) is more professional than a `.up.railway.app` URL.

### 11.1 Buy a domain

If your school doesn't already have a domain, the easiest place to buy one is **Cloudflare Registrar** (`https://www.cloudflare.com/products/registrar/`) or **Namecheap** (`https://www.namecheap.com`). A `.com` or `.tw` domain costs about US$10-15 per year.

### 11.2 Point the domain to Railway

1. In Railway, open the **frontend** service → **Settings** → **Networking** → **Custom Domain**.
2. Type the subdomain you want, for example `examgen.yourschool.tw`.
3. Railway shows you a **CNAME target** that looks like `xxxx.up.railway.app`. Copy it.
4. Open your domain registrar's DNS panel (Cloudflare, Namecheap, etc.).
5. Add a new **CNAME** record:
   - **Type:** CNAME
   - **Name:** the subdomain (e.g. `examgen`)
   - **Value / Target:** paste the Railway target from step 3.
6. Save. Wait 5-15 minutes for the new DNS record to spread across the internet.

### 11.3 HTTPS is automatic

Railway gives you a free HTTPS certificate (via Let's Encrypt) the moment the domain is verified. You don't need to do anything — just wait. After a few minutes, `https://examgen.yourschool.tw` will work.

### 11.4 Update the `FRONTEND_URL`

Now that the frontend has a new address, the backend needs to be told.

1. Open the **backend** service → **Variables**.
2. Edit `FRONTEND_URL` to be the new custom domain (e.g. `https://examgen.yourschool.tw`).
3. Save. The backend will redeploy automatically.

---

## 12. Alternative: deploy on Render instead

If you prefer **Render** (`https://render.com`) over Railway, the flow is very similar:

1. Sign up at Render with GitHub.
2. **New → Web Service** → pick your fork → set the Dockerfile to `Dockerfile.backend`. This becomes the **backend**.
3. **New → Web Service** → pick your fork again → set the Dockerfile to `web/Dockerfile`. This becomes the **frontend**.
4. **New → PostgreSQL** → create a free Postgres instance. Copy the **Internal Database URL** Render gives you, prefix it with `postgresql+asyncpg://`, and add it as `DATABASE_URL` on the backend service.
5. Add the same environment variables as Step 8 to the backend service. Set `VITE_API_BASE_URL` on the frontend.
6. Custom domain + free HTTPS work the same way as Railway: **Settings → Custom Domains → Add → follow the CNAME instructions.**

Render's free tier puts services to sleep after 15 minutes of inactivity. The first request after a sleep takes ~30 seconds to wake up. The paid tier (US$7/month per service) keeps services running 24/7.

---

## Generation admission gateway (pause new generation)

The **generation admission gateway** is a small ASGI reverse proxy that sits in front of the backend.  It lets an operator pause **all new generation requests** (`GET /api/generate` and `POST /api/generate`) from a single control point — completely independent of the frontend and backend deployment units — while established SSE streams keep delivering and result/history reads keep working.

Key properties:

- **Fail-closed on first install.** A fresh state directory (no `admission.json`) is treated as paused, so the gate is always safe to add even before it has been explicitly opened.
- **State lives on its own volume.** The `admission.json` file is written atomically on a named Docker volume (`gate-state`) or a Railway volume.  Rolling the frontend or backend back to a previous image does not affect the gate state.
- **Survives frontend/backend rollback.**  Because the state file is outside every application container, an operator can pause generation, roll back the backend, and the gate stays paused until explicitly opened again.
- **The live release controller uses the same record.**  When controller mode is enabled, `admission.json` also carries the `exam-generation.release-policy/1` contract (`environment`, increasing `release_revision`, `released_build_id`, `admission`, `supported_recovery_formats`, reader/artifact metadata).  The gateway serves `/release/policy.json` and gates every generation entry from fresh reads of that record; there is no positive process-local policy cache and no second pause switch.

### Compose usage

With the gateway service in docker-compose.yml, the gateway is the only service that binds host port 8000.  The backend becomes internal-only.

```bash
# Pause all new generation
docker compose exec gateway python scripts/admission_gate.py pause --reason "v2 rollout in progress"

# Open the gate again
docker compose exec gateway python scripts/admission_gate.py open

# Check current state (exits 3 if the gate does not match --require)
docker compose exec gateway python scripts/admission_gate.py status
docker compose exec gateway python scripts/admission_gate.py status --require OPEN
```

### Railway deployment steps

1. Add a fourth service in your Railway project: name it **gateway**, set the source to your fork, and choose `Dockerfile.gateway` as the Dockerfile.
2. Attach a **volume** to the gateway service at `/var/lib/examgen-gate`.  This is where the state file lives.
3. Set the following environment variables on the gateway service:
   - `GATEWAY_BACKEND_URL` → `http://backend.railway.internal:8000` (the backend's internal Railway hostname)
   - `GATEWAY_CONTROL_TOKEN` → a long random secret of your choice (keep this safe)
   - `RELEASE_ENVIRONMENT` → `production` (must match the release policy)
   - `GATEWAY_RELEASED_BUILD_ID` → the first deployed frontend build ID; omit it only while deliberately keeping the fresh controller fail-closed
   - `GATEWAY_RELEASE_REVISION` → `1` for the first controller record
   - `GATEWAY_READER_VERSION` → the recovery-reader version, for example `reader-1`
   - `GATEWAY_SUPPORTED_RECOVERY_FORMATS` → comma-separated formats accepted during recovery, default `exam-generation.recovery/1`. The web client's 儲存草稿並更新 requires the published policy to list `exam-generation.recovery/1`.
   - `PORT` → `8000` explicitly — set this so the gateway listens on the port its public domain targets.  Without it the domain answers 502 "Application failed to respond" even though the deploy shows as succeeded.
4. Give the gateway service a **public domain** (Railway → Settings → Networking → Generate Domain).  Set the domain's target port to `8000`, matching `PORT`.
5. Update the **frontend** service: change `BACKEND_HOST` from the backend's domain to the gateway's new domain.
6. **Remove the backend's public domain** so nothing can bypass the gate.  The backend is now reachable only via the gateway.

#### Control endpoint examples (curl)

```bash
# Pause
curl -X POST https://<gateway-domain>/gateway/admission \
  -H "X-Gateway-Control-Token: <your-token>" \
  -H "Content-Type: application/json" \
  -d '{"state": "paused", "reason": "planned maintenance"}'

# Open
curl -X POST https://<gateway-domain>/gateway/admission \
  -H "X-Gateway-Control-Token: <your-token>" \
  -H "Content-Type: application/json" \
  -d '{"state": "open"}'

# Health / current state
curl https://<gateway-domain>/gateway/health
```

> **Note:** This work (issue #740) establishes the operational capability — the gateway is wired, the state is durable, and new generation can be paused instantly.  Drain evidence (confirming in-flight streams complete before a deployment) and the stream-version protocol upgrade are tracked separately in issues #741 and #742.

---

## Drain telemetry and release control (issue #741)

Drain telemetry extends the gateway pause capability by letting operators
**confirm that all in-flight generation work has truly ended** before reopening
admission after a pause.  Without this you must guess whether active SSE
streams have finished; with drain telemetry you can poll a single endpoint and
get a machine-readable `quiescent: true/false` signal.

### How it works

Each backend instance maintains a set of thread-safe gauges:

| Gauge | What it counts |
|---|---|
| `active_runs` | `generate_question_stream` calls currently live |
| `active_workers` | worker threads currently executing inside `_worker_one` |
| `open_streams` | SSE event generators currently open to a client |
| `renderer_leases_held` | Playwright renderer borrows currently in progress |
| `pending_deliveries` | items queued in the stream's asyncio.Queue |
| `pending_persistence` | pending DB-write operations |

`quiescent: true` means all six gauges are zero simultaneously — the instance
is idle and safe to take out of rotation.

### Drain endpoint: GET /internal/drain

The backend exposes a restricted telemetry endpoint at `GET /internal/drain`.

**Security:**
- The gateway blocks all `/internal/*` paths — they never reach the public internet.
- The endpoint itself requires an `X-Drain-Token` header matching `DRAIN_TELEMETRY_TOKEN`.
- Set `DRAIN_TELEMETRY_TOKEN` to a long random secret on the backend service.
- If the environment variable is empty, the endpoint returns `404`.

**Example:**
```bash
curl -s https://<backend-internal-url>/internal/drain \
  -H "X-Drain-Token: <DRAIN_TELEMETRY_TOKEN>" | python3 -m json.tool
```

Response fields: `instance_id`, `hostname`, `pid`, `started_at`, `app_version`,
`supported_stream_versions`, all six gauges, `captured_at`, and `quiescent`.

### Inventory file

`scripts/release_control.py` reads an **inventory.json** that lists every backend
instance and the gateway:

```json
{
    "instances": [
        {
            "name": "backend-1",
            "url": "http://backend1.railway.internal:8000",
            "token_env": "DRAIN_TOKEN_1"
        }
    ],
    "gateway": {
        "url": "https://<gateway-domain>",
        "token_env": "GATEWAY_CONTROL_TOKEN"
    },
    "routes": [
        {"name": "frontend", "policy_url": "https://<frontend-domain>/release/policy.json"},
        {"name": "gateway", "policy_url": "https://<gateway-domain>/release/policy.json"}
    ]
}
```

Each `token_env` names an environment variable that holds the secret token.

### Release control subcommands

```bash
# Check all instances are reachable and drain endpoints respond
python scripts/release_control.py preflight --inventory inventory.json

# Poll until all instances report quiescent: true (or timeout)
python scripts/release_control.py drain-check --inventory inventory.json --timeout 120

# Pause gateway THEN wait for all in-flight work to finish
python scripts/release_control.py pause-and-drain --inventory inventory.json \
    --timeout 120 --reason "release v2.3"

# Verify all instances support stream version 1 (or your required version)
python scripts/release_control.py compat-check --inventory inventory.json \
    --require-version 1

# Reopen the gateway after deployment
python scripts/release_control.py reopen --inventory inventory.json

# Combined readiness check (preflight + compat + quiescence)
python scripts/release_control.py readiness --inventory inventory.json \
    --require-version 1

# Prepare a target. This sets admission=preparing and does not open the gate.
python scripts/release_control.py prepare --inventory inventory.json \
    --target target-release.json

# Publish only when every inventory instance has fresh positive drain evidence
# and every serving route reports the target build/revision/reader metadata.
python scripts/release_control.py publish --inventory inventory.json \
    --max-age-seconds 15

# Retire a transition asset only after another positive drain observation.
python scripts/release_control.py retire --inventory inventory.json \
    --artifact schema-v1 --max-age-seconds 15
```

### Recommended release runbook

1. `python scripts/release_control.py preflight` — confirm every instance is reachable.
2. `python scripts/release_control.py compat-check --require-version 1` — confirm compatibility.
3. `python scripts/release_control.py prepare --target target-release.json` — enter `preparing`; the independent gate remains closed.
4. Deploy/roll the target artifact without exposing a backend public domain.
5. `python scripts/release_control.py publish` — require fresh positive drain evidence, zero in-flight gateway admissions, and matching policy/reader metadata on every route.
6. `python scripts/release_control.py readiness --require-version 1` — record post-switch server evidence.
7. `python scripts/release_control.py reopen` — use the same durable gate only after readiness passes.
8. Retain the current artifact, prepared rollback artifact, and transition assets until a later `retire` command has positive retirement evidence. An application rollback cannot reopen the gate or replace the controller record.

> **Gateway privacy rule**: `/internal/` paths are never proxied by the gateway.
> The drain endpoint is reachable only from internal network (Railway internal
> hostnames, VPN, or direct container exec) — never via the public gateway URL.

---

## Live release controller and admission evidence (issue #778)

The controller is a gateway-owned file-backed state machine. It extends the
existing `admission.json`; it does not introduce another pause file or a
frontend-controlled override. The public policy response is
`exam-generation.release-policy/1` and includes:

- `environment`, monotonically increasing `release_revision`, and
  `released_build_id`;
- `admission`: `open`, `paused`, or `preparing`;
- `supported_recovery_formats` and `reader_version`;
- `artifacts.current`, `artifacts.prepared_rollback`, and transition assets.

The backend uses `RELEASE_AUTHORITY_URL` to read the gateway's policy on every
GET/POST generation admission. The browser's `/release/policy.json` and
`/build-meta.json` requests are proxied to the same gateway. A missing,
unreadable, malformed, paused, or preparing record fails closed; a missing or
outdated `X-Frontend-Build-ID` gets `426 CLIENT_UPDATE_REQUIRED` before the
backend dispatch seam, and authority/maintenance failures get retryable 503.

Target publication is deliberately separate from reopening. The controller
rejects stale/unreachable/nonzero drain evidence, incomplete route metadata,
nonzero in-flight gateway admissions, and non-increasing revisions. The
gateway counts an admission from its decision through response delivery, so a
policy transition cannot overtake an already admitted stream. Existing streams
and read-only routes continue while new admissions are closed. Restarting or
rolling back the application leaves the controller volume and gate unchanged.

For a local, no-deployment rehearsal covering two backend instances, every
route in the #740 inventory, both nginx files, zero-dispatch rejection, stream
continuity, and a pending transition, run:

```bash
uv run python scripts/release_admission_rehearsal.py \
  --output docs/research/2026-09-17-778-release-admission/evidence.json
```

The committed README and JSON evidence under
`docs/research/2026-09-17-778-release-admission/` record observed route
responses and backend/provider dispatch counts. This is a controlled readiness
checkpoint only; it does not deploy or perform the final teacher-facing A→B→A
rollout.


## Error reporting (Sentry, optional)

The web app has a bottom-right "?" button that lets users report problems.
It and the backend error reporting are powered by [Sentry](https://sentry.io)
and are **entirely optional**. The frontend never contacts Sentry when
`VITE_SENTRY_DSN` is unset; the backend never contacts Sentry when
`SENTRY_DSN` is unset or blank.

One-time setup:

1. Create a free account at sentry.io and create two projects: one with the
   **React** platform and one with the **FastAPI** platform. Copy each
   project's **DSN** (a public client key, not a secret).
2. Set `VITE_SENTRY_DSN` to that DSN when building the frontend
   (docker-compose reads it from the environment / `.env` file). Staging
   builds are tagged with environment `staging` (via `VITE_IS_STAGING`),
   production builds with `production`.
3. Set the FastAPI project's DSN as `SENTRY_DSN` on the backend and set
   `SENTRY_ENVIRONMENT` to `staging` or `production`; also set
   `DB_POOL_CHECKOUT_ATTRIBUTION=1` on the **staging** backend so that any
   abandoned asyncpg pool connection is attributed to its owning code path and
   forwarded to Sentry automatically by the `LoggingIntegration`. On Railway,
   backend events are automatically tagged with the deploy commit SHA via
   `RAILWAY_GIT_COMMIT_SHA`; set `SENTRY_RELEASE` only to override that value
   or when deploying on a platform that does not inject `RAILWAY_GIT_COMMIT_SHA`.
4. In Sentry: **Settings → Integrations → GitHub**, install the GitHub
   integration and connect the `paulpengtw/exam-generation` repository.

On the **frontend** service only, add these build-time variables in both the
production and staging environments. The frontend build's source-map upload
step uses them to publish releases and upload source maps:

| Variable name | Value to type | What it is |
|---|---|---|
| `SENTRY_AUTH_TOKEN` | An organisation auth token from Sentry | Authorises the frontend build to publish releases and upload source maps. This is a real secret: never commit it and never put it in `.env.example`. |
| `SENTRY_ORG` | Your Sentry organisation slug | Tells the upload step which Sentry organisation to use |
| `SENTRY_PROJECT` | The Sentry project slug for this web service and environment | Tells the upload step which project to use. Use a different project for each environment (for example, one for the production web build and another for staging). |

If these three variables are unset, the frontend build still succeeds and
simply skips the source-map upload.

The frontend Docker build automatically stamps the release with the deploy
commit SHA on Railway (`RAILWAY_GIT_COMMIT_SHA`) and Render
(`RENDER_GIT_COMMIT`), so there is nothing to configure on those platforms.
Set `VITE_SENTRY_RELEASE` manually only on other platforms or when you want to
override the automatically detected value.

Forks can leave **all** Sentry variables unset, including the three frontend
build variables above. Everything degrades gracefully: there is no Sentry
error reporting, no source-map upload, and no build failure.

Triage flow: user feedback and captured errors appear in the Sentry project
(User Feedback / Issues views). Open an item and use **Create GitHub Issue**
to file a pre-filled, linked issue in the repository — issue creation is a
deliberate one-click action, not automatic, to keep the tracker free of
duplicates.

---

## 13. Step 9 — Switch email delivery to AWS SES

By default the backend only prints sign-in links to its logs (`EMAIL_BACKEND=console`). Teachers who were not given that link cannot sign in. This step wires up **AWS Simple Email Service (SES)** so the backend emails every teacher a real magic-link.

**Cost:** ~US$0.10 per 1,000 emails. AWS offers 3,000 free messages per month for the first 12 months.

### 13.1 Create an AWS account

1. Open `https://aws.amazon.com` and click **Create an AWS Account**.
2. Follow the sign-up flow (email, password, credit card). You land on the **AWS Management Console**.

### 13.2 Verify your sender address (or domain) in SES

1. In the AWS Console search bar, type **SES** and click **Amazon Simple Email Service**.
2. In the top-right corner, choose a region close to your users — `ap-northeast-1` (Tokyo) works well for Taiwan.
3. In the left menu, click **Verified identities** → **Create identity**.
4. Choose **Email address**, type the address you want emails to come from (e.g. `noreply@yourschool.tw`), then click **Create identity**.
5. AWS sends a verification email to that address. Open it and click the link.

> **Better deliverability (optional):** Instead of verifying a single address, verify the whole domain. Choose **Domain** in step 4, then copy the DKIM **CNAME** records AWS shows you into your domain registrar's DNS panel (the same panel you used in Step 11.2). AWS verifies the domain automatically once the records propagate (5–30 minutes).

### 13.3 Request production access (so you can email anyone)

AWS puts new SES accounts in a **sandbox** — you can only send to addresses you have individually verified. To email real teachers:

1. In SES, click **Account dashboard** in the left menu.
2. Under **Production access**, click **Request production access**.
3. Fill in the form:
   - **Mail type:** Transactional
   - **Website URL:** paste your frontend URL
   - **Use case description:** "Magic-link sign-in emails for a school exam tool. Recipients are teachers who created their own accounts. Volume: under 100 emails per day."
4. Submit. AWS typically approves within 24 hours.

> While waiting for approval, you can verify each teacher's email address individually under **Verified identities** so they can log in during the sandbox period.

### 13.4 Create an IAM user with SES-send permissions

Railway does not have an AWS IAM role, so you must supply an access key.

1. In the AWS Console, search for **IAM** and open it.
2. Click **Users** → **Create user**. Name it `examgen-ses`. Click **Next**.
3. Choose **Attach policies directly**. Search for `AmazonSESFullAccess` and tick it. Click **Next** → **Create user**.
4. Click the new `examgen-ses` user → **Security credentials** tab → **Create access key**.
5. Choose **Application running outside AWS**. Click **Next** → **Create access key**.
6. **Copy both values** — the **Access key ID** and the **Secret access key**. The secret is shown only once.

### 13.5 Add the five variables on Railway

Open the **backend** service → **Variables** tab.

| Variable name | Value to set |
|---|---|
| `EMAIL_BACKEND` | Change `console` → `ses` |
| `AWS_REGION` | The region you chose in §13.2, e.g. `ap-northeast-1` |
| `SES_FROM_EMAIL` | The verified sender address, e.g. `noreply@yourschool.tw` |
| `AWS_ACCESS_KEY_ID` | The Access key ID from §13.4 |
| `AWS_SECRET_ACCESS_KEY` | The Secret access key from §13.4 |

Railway redeploys the backend automatically. Wait 1–2 minutes.

### 13.6 Test it

1. Open the frontend → click **Sign up** → enter your email → submit.
2. A sign-in email should arrive within 5–30 seconds. Check your spam folder if it doesn't.
3. If nothing arrives, open Railway → **backend** service → **Deployments** → latest → **Logs** and look for `botocore` or `ClientError`. The table below lists common errors.

**SES-specific errors:**

| What you see in the logs | Likely cause | What to do |
|---|---|---|
| `MessageRejected: Email address is not verified` | SES sandbox: recipient not yet verified | §13.3 — request production access, or verify each recipient under **Verified identities** |
| `InvalidClientTokenId` / `SignatureDoesNotMatch` | Wrong `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` | Re-paste both from §13.4; no leading or trailing spaces |
| `Could not connect to the endpoint URL` | Wrong `AWS_REGION` | Match the region where you verified the sender |
| Login email never arrives, no errors in logs | `EMAIL_BACKEND` is still `console` | §13.5 — change to `ses` and save; wait for redeploy |

---

## 14. Maintaining your deployment

### Update to a newer version

When the project gets updates:

1. Open your fork on GitHub.
2. Near the top, click **Sync fork** → **Update branch**.
3. Railway automatically detects the new code and redeploys both services. No further action.

### Check the logs

If something looks broken:

1. Railway → the service that looks unhappy → **Deployments** tab → click the latest deployment.
2. Read the logs. Search for the word `Error` or `Warning`.

### Back up the database

1. Railway → Postgres service → **Backups** tab.
2. Railway takes daily backups automatically on the Hobby plan.

### Rotate an API key

If you suspect a key has leaked, rotate it at the provider (Google AI Studio for `GEMINI_API_KEY`, `console.anthropic.com` for `LLM_API_KEY`, `platform.openai.com` for `OPENAI_API_KEY`): disable the old key, create a new one, then update the matching variable in Railway → backend service → **Variables** → **Save**. The backend redeploys with the new key.

### The 15-minute limit on a single generation

Railway closes any single web request after 15 minutes, even while progress updates or messages to keep the connection open are still arriving. This is a fixed platform rule and cannot be raised in Railway settings, on any plan. See the [Railway request limits](https://docs.railway.com/networking/public-networking/specs-and-limits).

The exam generator sends live progress over one long web request. If a generation is still running at the 15-minute mark, that request closes and the browser shows an error.

Questions that finished before the cutoff are already saved in **出題紀錄** (history); only the questions still in progress are lost. Open **出題紀錄** to find the finished questions, then run a new generation for the missing ones.

The slowest single question determines how long a run takes: repeated checks and corrections (verification retries), together with image generation, can push it past the limit. Questions are generated side by side, so their times do not add up with the number of questions in a batch.

If you hit the limit repeatedly, use fewer verification retries or a faster model for that subject, or generate items with many images in smaller runs.

Tracked in [GitHub issue #702](https://github.com/paulpengtw/exam-generation/issues/702).

---

## 15. Troubleshooting

| What you see | Likely cause | What to do |
|---|---|---|
| Frontend loads but login fails | `FRONTEND_URL` on the backend doesn't match the actual frontend URL | Fix the value (Step 8.1) and let the backend redeploy |
| "Invalid API key" / 422 when generating | The provider key for the selected model is wrong or unset | Check the key named in the error in the backend Variables tab. Defaults require both `GEMINI_API_KEY` (execute) and `LLM_API_KEY` (plan/驗證); GPT/o-series overrides require `OPENAI_API_KEY` |
| Backend deployment crashes on startup | Wrong `DATABASE_URL` format | Make sure the value starts with `postgresql+asyncpg://` (not `postgres://`) |
| Generation fails with "Rate limit exceeded" / 429 | You're calling Claude too fast | Raise `LLM_RATE_LIMIT_DELAY` from `2` to `5` |
| Magic link request returns `403 email not allowed` | `EMAIL_WHITELIST` is set and the address doesn't match any entry | Add the address (or `*@theirdomain`) to `EMAIL_WHITELIST` on the backend, then save and redeploy |
| Custom domain shows certificate warning | DNS hasn't propagated yet | Wait 15-30 minutes and refresh |
| Frontend shows blank page | `BACKEND_HOST` or `BACKEND_SCHEME` not set on the frontend service | Step 8.2 — add both variables to the frontend **Variables** tab |
| Frontend logs show `host not found in upstream "backend"` | `BACKEND_HOST` env var missing | Step 8.2 — add `BACKEND_HOST` (hostname only, no `https://`) and `BACKEND_SCHEME=https` |
| `alembic upgrade failed` in logs | The database wasn't reachable when the backend started | Click **Redeploy** on the backend service after Postgres is fully up |
| Logs only show `PostgreSQL 18.3 ...` / `database system is ready to accept connections` | You opened the **Postgres** service tile, not the backend | Go back to the project page and click the tile you renamed `backend` in Step 7.2 |
| Build log shows `Railpack` / `Detected Python` / `No start command detected` | Builder is still set to Railpack, not Dockerfile | Service → **Settings → Build** → set **Builder = Dockerfile** and **Dockerfile Path** = `Dockerfile.backend` (backend) or `web/Dockerfile` (frontend). Click **Save** and redeploy. |
| Frontend URL times out / shows "Application failed to respond" but nginx logs look healthy | Generated domain points at wrong port | Frontend → **Settings → Networking** → click the pencil icon next to your domain → set target port to `80`. |
| Clicking **Send magic link** shows `Request failed with status 508` | The frontend is forwarding API calls back to itself, usually because `BACKEND_HOST` is wrong or the frontend was not redeployed after changing it | Frontend → **Variables** → set `BACKEND_HOST` to the backend hostname only, such as `backend-production-xxxx.up.railway.app` — no `https://`, no trailing slash, and not the frontend hostname. Keep `BACKEND_SCHEME=https`, then redeploy the frontend. |
| Generation stops with an error after exactly 15 minutes even though progress was still moving. | Railway's fixed 15-minute limit on a single request. | See "The 15-minute limit on a single generation" in section 14; finished questions are already in 出題紀錄. |

---

## 16. Glossary

| Word | What it means |
|---|---|
| **API key** | A password that lets one program use another program. The Gemini API key lets your backend call the AI that generates questions. |
| **Environment variable** | A labelled setting that a program reads when it starts (e.g. `LLM_API_KEY = sk-ant-...`). |
| **Fork** | Your personal copy of someone else's GitHub repository. You need a fork because Railway can only deploy from a repository you own. |
| **Deploy** | Take the code and run it on a server connected to the internet. |
| **Container** | A self-contained package that includes the code plus everything it needs to run. Railway runs your backend and frontend as containers. |
| **HTTPS** | The "secure" version of HTTP — shown in the browser as a padlock. Railway sets this up for you automatically. |
| **CNAME** | A type of DNS record that points one website name at another. You use one to point `examgen.yourschool.tw` at Railway. |
| **Migration** | A change to the database structure. The backend runs these automatically on startup, so you don't have to. |
| **SES** | Amazon Simple Email Service — AWS's service for sending emails from applications. Used here to deliver magic-link sign-in emails to teachers. |
| **IAM** | AWS Identity and Access Management — the system that controls who is allowed to use which AWS services. You create an IAM user so the backend can call SES on your behalf. |
| **DKIM** | DomainKeys Identified Mail — a set of DNS records that prove your domain is authorised to send email, improving deliverability and avoiding spam filters. |
| **Backend** | The program on the server that does the actual work (calls Claude, stores users in the database). |
| **Frontend** | The website that teachers see in their browser. |

---

## 17. Where to ask for help

If you get stuck on a step in this guide, open an issue on the project's GitHub repository:

`https://github.com/YOUR-USERNAME/exam-generation/issues` → **New issue**.

When asking for help, include:
1. Which step number you're stuck on.
2. The exact error message you see.
3. A screenshot if possible.

---

## Note: production builds require a commit SHA (issue #770)

When deploying a production frontend build (`npm run build` with `NODE_ENV=production`),
the build will fail unless a real commit SHA is available via one of these environment
variables (checked in priority order):

1. `RAILWAY_GIT_COMMIT_SHA` — set automatically by Railway.
2. `RENDER_GIT_COMMIT` — set automatically by Render.
3. `GIT_COMMIT_SHA` — set manually if using another CI/CD platform.
4. `BUILD_ID` — set this to any unique identifier (e.g. a Docker image digest or CI run ID)
   if none of the above are available.

Placeholder values (`unknown`, `dev`, `local`, `HEAD`, empty string) are rejected and
cause the build to fail with a descriptive error naming the fix.

Optionally set `RELEASE_REVISION` (integer) to increase the release revision number in
`dist/release/policy.json`. Defaults to `1` if not set.

## Staging environment name — coordinated switch-over (issue #892)

The web Dockerfile now accepts a `VITE_ENVIRONMENT` build argument. When set, the
build-identity plugin (`web/buildIdentity.ts`) uses it as the `environment` field in
`dist/build-meta.json` and `dist/release/policy.json` instead of falling back to the
Vite mode (`production`). When the argument is absent or empty the behaviour is
unchanged: the environment defaults to the Vite mode, so production deployments that do
not set `VITE_ENVIRONMENT` continue to produce `environment: "production"`.

### Why three settings must flip together

The backend (`RELEASE_ENVIRONMENT`) and the gateway policy record (`environment`) both
validate that the bundle's declared environment matches. A mismatch fails closed.
All three must agree before a staging generation can pass preflight and reach
`/api/generate`:

| Setting | Service | Staging value | Notes |
|---|---|---|---|
| `VITE_ENVIRONMENT` | Railway frontend build variable | `staging` | Forwarded as a Docker build arg; sets `environment` in the emitted `policy.json` and `build-meta.json`. |
| `RELEASE_ENVIRONMENT` | Railway backend environment variable | `staging` | Backend validates it matches the gateway policy's `environment` field on every generation request. |
| `environment` in gateway policy record | Gateway `admission.json` volume | `staging` | The gateway serves this as `GET /release/policy.json`; both the browser and the backend read it. |

Production keeps all three at `production` and is unaffected by this change.

### Operator switch-over procedure (staging only)

These steps cannot be done in code and require direct Railway + gateway operator access:

1. **Set the Railway frontend build variable**: in the Railway **staging** frontend
   service → Variables, add (or update) `VITE_ENVIRONMENT = staging`. Redeploy the
   frontend service so the new bundle is built and served.

2. **Set the Railway backend environment variable**: in the Railway **staging** backend
   service → Variables, set `RELEASE_ENVIRONMENT = staging`. Redeploy the backend.

3. **Update the gateway policy record**: on the staging gateway, update `admission.json`
   so that the `exam-generation.release-policy/1` record contains `"environment": "staging"`.
   Use `scripts/release_control.py` or the gateway control endpoint; the `RELEASE_ENVIRONMENT`
   env var on the gateway service itself should also be `staging` (set in Step 1 of the
   gateway Railway deployment steps in the section above).

The order matters: change the frontend build first so the new bundle's `released_build_id`
can be recorded before the gateway policy is updated to `staging`.

### Verification

After all three settings are applied:

```bash
# 1. Confirm the bundle declares environment: staging
curl -s https://examgen-staging.cpeng.me/build-meta.json | python3 -m json.tool | grep environment

# 2. Confirm the gateway policy declares environment: staging
curl -s https://examgen-staging.cpeng.me/release/policy.json | python3 -m json.tool | grep environment

# 3. Run the staging smoke test (no committed secrets; needs BASE_URL)
BASE_URL=https://examgen-staging.cpeng.me bash scripts/smoke_test.sh
```

Expected: both JSON responses show `"environment": "staging"`, and the smoke test
reports a generation that reaches `/api/generate` (not a preflight rejection).
Production must still show `"environment": "production"` and must be verified
independently after any change to production variables.

## Staging: gateway follows the frontend build (issue #922)

After one-time operator setup every staging frontend deploy automatically advances the
gateway `released_build_id` to the new bundle's build ID.  No per-deploy manual steps
are required: nobody has to edit `GATEWAY_RELEASED_BUILD_ID`, wipe the volume, or run
`prepare → publish → reopen`.

### How it works

The frontend nginx:alpine image runs every executable script under
`/docker-entrypoint.d/` synchronously before nginx starts.  `50-follow-release.sh`
reads `build_id` from `/usr/share/nginx/html/build-meta.json` and POSTs it to
`POST /gateway/release/follow`.  The gateway atomically advances `released_build_id`
and `release_revision` in the policy record.  Admission state (`open` or `paused`)
is not changed.

### One-time operator setup (staging only)

| Service | Variable | Value |
|---|---|---|
| Gateway | `GATEWAY_FOLLOW_FRONTEND` | `1` |
| Frontend | `GATEWAY_CONTROL_TOKEN` | `${{gateway.GATEWAY_CONTROL_TOKEN}}` — Railway [reference variable](https://docs.railway.com/reference/variables), single source of truth |
| Frontend | `GATEWAY_FOLLOW_URL` | `http://gateway.railway.internal:8000/gateway/release/follow` |

After setting these variables, redeploy the gateway first (so the new endpoint is live),
then redeploy the frontend.

### Trade-offs

On staging, the drain-before-switch procedure is not used and admission is not paused
around a deploy.  Old tabs get "update required" once they next check the policy (they
must reload).  For a few seconds during a deploy, new page loads can still be served the
old bundle while the gateway has already recorded the new build ID; those loads see
"update required" once and a reload fixes it.

### Rollback

If a rollback deploys an older image, the hook runs on that image's start and posts the
older `build_id` at a higher revision than when that image was first deployed.  The
gateway accepts this (revision always increases).  This behaviour is inferred from the
nginx entrypoint, which runs `/docker-entrypoint.d/` on every container start; Railway
does not document this explicitly.

To disable follow mode entirely, remove `GATEWAY_FOLLOW_FRONTEND` from the gateway and
`GATEWAY_CONTROL_TOKEN` / `GATEWAY_FOLLOW_URL` from the frontend.  The endpoint returns
404 and the hook is inert.

### Unreachable internal hostname

If `gateway.railway.internal` is unreachable, the hook logs it and nginx starts
regardless.  Use the public gateway URL as `GATEWAY_FOLLOW_URL` instead.

Production does not set `GATEWAY_FOLLOW_FRONTEND`; production is unchanged.

## Production facts before detached generation runs (issue #903)

The OpenSpec change `openspec/changes/detached-generation-runs/` needs two read-only facts from the production database that only someone with production access can collect. First, check whether `generation_records` already holds duplicate rows per `(generation_log_id, question_id)`; this decides whether a cleanup step must precede the planned unique constraint. Second, measure the per-question p95 generation duration; this sets `RAILWAY_DEPLOYMENT_DRAINING_SECONDS` (about 120 seconds until it is measured). Post both results on issue #903. If duplicates exist, record the cleanup decision on #903 before the uniqueness change ships.

### Connecting

Open a psql session against the Railway Postgres service, for example with `railway connect Postgres`, or with `psql` and the Postgres service's public connection URL. The backend's `DATABASE_URL` uses the `postgresql+asyncpg://` prefix, which psql does not accept; use a plain `postgresql://` URL. Everything below is read-only; wrap it in `BEGIN READ ONLY;` … `ROLLBACK;`.

```sql
BEGIN READ ONLY;
-- run the queries below
ROLLBACK;
```

### 1. Duplicate pre-check

Rows with a NULL `generation_log_id` are excluded because Postgres treats NULLs as distinct, so they cannot violate the constraint.

```sql
SELECT count(*)                 AS duplicate_pairs,
       coalesce(sum(n - 1), 0)  AS surplus_rows
FROM (
  SELECT generation_log_id, question_id, count(*) AS n
  FROM generation_records
  WHERE generation_log_id IS NOT NULL
  GROUP BY generation_log_id, question_id
  HAVING count(*) > 1
) d;
```

Only if `duplicate_pairs` is above 0, list examples to inform the cleanup decision:

```sql
SELECT generation_log_id, question_id,
       array_agg(status::text || ' @ ' || created_at ORDER BY created_at) AS rows
FROM generation_records
WHERE generation_log_id IS NOT NULL
GROUP BY generation_log_id, question_id
HAVING count(*) > 1
ORDER BY min(created_at) DESC
LIMIT 20;
```

### 2. Per-question p95 duration

Questions in one run start in parallel after batch planning, and each record is saved when that question finishes, so `generation_records.created_at − generation_logs.started_at` approximates one question's wall time. It includes batch-planning time, which makes it a slight overestimate and is the safe side for a drain window. Only completed rows from the last 90 days are counted; rows with a `parent_record_id` (人工審題修正) are skipped.

```sql
SELECT count(*)                                                  AS n,
       round(percentile_cont(0.50) WITHIN GROUP (ORDER BY secs)::numeric, 1) AS p50_s,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY secs)::numeric, 1) AS p95_s,
       round(percentile_cont(0.99) WITHIN GROUP (ORDER BY secs)::numeric, 1) AS p99_s,
       round(max(secs)::numeric, 1)                              AS max_s,
       min(started_at)::date                                     AS from_day,
       max(started_at)::date                                     AS to_day
FROM (
  SELECT extract(epoch FROM r.created_at - l.started_at) AS secs, l.started_at
  FROM generation_records r
  JOIN generation_logs l ON l.id = r.generation_log_id
  WHERE r.status = 'completed'
    AND r.parent_record_id IS NULL
    AND l.started_at >= now() - interval '90 days'
) t
WHERE secs > 0;
```

Set `RAILWAY_DEPLOYMENT_DRAINING_SECONDS` to the p95, rounded up, and record the value here.

### Results

| Fact | Value | Date measured |
|---|---|---|
| Duplicate pairs / surplus rows | `_pending_` | `_pending_` |
| Per-question p95 (s) | `_pending_` | `_pending_` |
| Cleanup decision | `_pending_` | `_pending_` |

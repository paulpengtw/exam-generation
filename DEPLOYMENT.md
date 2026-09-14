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
| `EMAIL_BACKEND` | `console` | `console` prints magic-link login emails to backend logs — fine for your own first login; switch to `ses` after following **Step 13** so other teachers receive real emails |
| `EMAIL_WHITELIST` | *(leave blank for now)* | Comma-separated list of email addresses (or `*@domain` wildcards) that are allowed to request a magic link. Leave empty to allow anyone who knows the URL to sign up. Set to `*@yourschool.tw` (for example) to restrict sign-ups to your school domain. |
| `SENTRY_DSN` | *(leave blank, or paste the backend project's DSN)* | Sends backend errors and traces to Sentry. Leave it unset or blank to disable backend Sentry completely. |
| `SENTRY_ENVIRONMENT` | `production` (or `staging`) | Tags backend Sentry data with the deployment environment. |

The model and effort values above are the code defaults when their variables are
unset. Opus 4.6 calls enable adaptive thinking with a 16,384-token output ceiling
shared by thinking and the response; `LLM_TEMPERATURE` is ignored for this model.
Planning and 驗證 therefore spend thinking tokens at Opus output rates.

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
   forwarded to Sentry automatically by the `LoggingIntegration`.
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

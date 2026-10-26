# 05 — Tech stack, repo layout, hosting & deployment

> **DECIDED Oct 26 2026** (supersedes the Oct 21 audit's Next.js + Vercel + Supabase + Inngest proposal, kept in `docs/research/03_...`).

---

## 1. Stack

| Layer | Choice |
|---|---|
| Frontend | **React + TypeScript on Vite** (`npm create vite@latest web -- --template react-ts`), Tailwind, **PWA via `vite-plugin-pwa`**, **TanStack Query**; camera/mic via browser APIs (`<input type="file" accept="image/*" capture="environment">`, `getUserMedia`, `MediaRecorder`); TS API types generated from FastAPI OpenAPI with **`openapi-typescript`** |
| Backend | **FastAPI** (async) + **Pydantic** (schemas, structured model outputs) |
| DB / migrations | **Postgres** + **SQLAlchemy** + **Alembic** (`alembic upgrade head` on API container start) |
| Jobs | **ARQ** worker on **Redis** (long Wonder runs, reminders, retention/deletion jobs); APScheduler or ARQ cron for reminder scans |
| Live trace | **SSE** (server-sent events) from API → trace panel |
| AI layer | OpenAI Python SDK (`AsyncOpenAI`, Responses API) or `httpx` → Meta API (Wonder, Spark 1.3, SAM 3.1, Voice, Image); `httpx` → **Baseten** (Spark Open `meta-models/muse-spark-open-1026`); **own agent loop** (~100–150 lines) with caps, cost logging, spend limit |
| Media | **Pillow / OpenCV** (apply SAM masks: blur/black-box), **ffmpeg** (`ffmpeg-python`/`pydub`) audio → mono 16-bit WAV 16 kHz, ≤10-min chunks |
| Locales | `locales/kr`, `locales/my` packs (YAML/JSON: obligations, doc types, contacts, sources, guardrails, regex, flags, prompts) |
| Storage | Encrypted volume for **redacted files only**; raw uploads/audio auto-deleted |

Why Vite not Next.js: FastAPI is the backend, so no SSR/API routes needed; static build served by nginx → tiny image, trivial Dokploy deploy; fast dev; easy PWA. TypeScript is the language, Vite the build tool — use both.

### Alternatives considered (not chosen)
- **Laravel 12 + Inertia (React/Vue) PWA** — built-ins (auth, queues, scheduler, storage), Reverb for live trace, `Http::pool`, one app. Downsides: fewer Meta examples (Python-first), image redaction via Intervention/Imagick, manual agent loop. Keira chose Python.
- **Next.js PWA + Vercel `icn1` + Supabase Seoul + Inngest (all TypeScript)** — Oct 21 audit recommendation; superseded by Python + homelab/Dokploy.
- **Flutter (web build)** — same browser limits; Kakao Flutter SDK lacks web. Flutter = native app **after** the hackathon.

## 2. Repo layout (target)

```
kolife/                          # PUBLIC GitHub repo (hackathon rule)
├── CLAUDE.md / AGENTS.md        # agent instructions
├── README.md                    # judge-facing: pitch, demo video, architecture, which Meta model does what, setup, cost notes
├── PROGRESS.md                  # running log: done / next / blockers / spend
├── docs/                        # this knowledge base
├── .env.example                 # no real values
├── .gitignore                   # .env, samples/, logs/, *.wav, uploads/
├── docker-compose.yml           # local dev (builds from source)
├── deploy/
│   └── docker-compose.prod.yml  # Dokploy compose: GHCR images only, no build
├── .github/workflows/
│   └── build-and-deploy.yml
├── web/                         # React + TS + Vite PWA
│   └── src/{pages,components,api(openapi types),hooks,i18n}
├── api/                         # FastAPI
│   ├── app/
│   │   ├── main.py  config.py  db.py  security.py(crypto, auth)
│   │   ├── core/    models.py(IDs, efforts, prices, client) orchestrator.py workers.py specialists.py store.py trace.py spend.py
│   │   ├── redaction/  sam.py regex.py blur.py
│   │   ├── cases/      engine.py calendar.py deadlines.py(holidays)
│   │   ├── integrations/ kakao.py baseten.py maps.py
│   │   ├── locales/    kr/ my/
│   │   └── routes/     profile.py cases.py uploads.py trace.py(SSE) health.py
│   ├── alembic/
│   └── Dockerfile
├── worker/                      # ARQ worker (can share api image with different command)
├── scripts/                     # smoke_test.py, cost_report.py, seed_demo.py
├── tests/
└── samples/                     # gitignored — redacted sample docs (KR + MY), mock call
```

## 3. Hosting

### Environments
| Env | Where | Image tag | Trigger |
|---|---|---|---|
| **Staging / dev** | **Homelab** Dokploy (VM 220) via Cloudflare Tunnel | `:main` (+ `:sha-xxxx`) | push to `main` → webhook |
| **Prod (judges' URL)** | **DigitalOcean droplet** Dokploy (existing, also hosts Hermes Agent) | `:vX.Y.Z` | git tag `v*` → manual deploy or webhook |

Rationale: homelab is free and a good "self-hosted, privacy-first" story, but it's a shared mini PC on home power with **no UPS**, a router Keira can't administer, and a co-owner who might reboot it. One outage during judging (Nov 5–10) costs demo-quality points → prod on the droplet, homelab as fallback (or vice-versa with the droplet kept warm with seeded demo data; switch Cloudflare hostname if Kuma alerts).

### Homelab
Single x86 mini PC (Proxmox, no GPU) running Dokploy in a VM, exposed via Cloudflare Tunnel (tunnel route = HTTP `localhost:80`, Dokploy domain HTTPS off). Admin UIs Tailscale-only; only KoLife exposed. Uptime Kuma monitors site + `/api/health`; daily `pg_dump` during the hackathon. Host details kept in the private notes (`docs/research/05_homelab.md`, not in the repo).

## 4. CI/CD — GitHub Actions builds, Dokploy only pulls (DECIDED)

```
push to main ─► GitHub Actions
                 ├─ build web, api, worker images (linux/amd64 only)
                 ├─ push to GHCR (tags: sha-xxxx + main)
                 └─ curl Dokploy webhook (staging)
                         │
   Homelab Dokploy (VM 220) pulls :main ─► Cloudflare Tunnel ─► staging URL

tag v* (e.g. v1.0.0) ─► same build ─► push :v1.0.0 (+ :latest-release)
                         │
   Droplet Dokploy pulls :v1.0.0 (manual or webhook) ─► judges' URL
```

Rules:
- **Dokploy only pulls** — compose references GHCR images, no `build:` keys.
- **Build `linux/amd64` only** (homelab + droplet are x86; Keira's Mac is arm64 → local dev builds natively).
- **No secrets in images.** API keys/DB passwords live in each Dokploy environment. Anything `VITE_*` is public by design (only public keys like Kakao JS key).
- GHCR: public repo → public packages OK; if private, add a read-only GHCR token to Dokploy.
- Webhook URLs as GitHub secrets: `DOKPLOY_STAGING_HOOK`, `DOKPLOY_PROD_HOOK`.
- Migrations run on API start (`alembic upgrade head`).
- **Freeze prod by Nov 4** on a release tag; change nothing until Nov 10. Roll back = redeploy previous tag.

### Workflow sketch (`.github/workflows/build-and-deploy.yml`) — adapt
```yaml
name: build-and-deploy
on:
  push:
    branches: [main]
    tags: ['v*']
permissions: { contents: read, packages: write }
jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix: { svc: [web, api] }      # worker reuses api image with a different command
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with: { registry: ghcr.io, username: ${{ github.actor }}, password: ${{ secrets.GITHUB_TOKEN }} }
      - id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/${{ github.repository_owner }}/kolife-${{ matrix.svc }}
          tags: |
            type=sha,prefix=sha-
            type=ref,event=branch
            type=semver,pattern=v{{version}}
      - uses: docker/build-push-action@v6
        with:
          context: ./${{ matrix.svc }}
          platforms: linux/amd64
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
  deploy-staging:
    needs: build
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - run: curl -fsS -X POST "${{ secrets.DOKPLOY_STAGING_HOOK }}"
  deploy-prod:
    needs: build
    if: startsWith(github.ref, 'refs/tags/v')
    runs-on: ubuntu-latest
    steps:
      - run: curl -fsS -X POST "${{ secrets.DOKPLOY_PROD_HOOK }}"   # or deploy manually in Dokploy
```
Note: action major versions are from memory — check latest before use. `VITE_*` build args for `web` must be passed at build time (public values only).

### Prod compose sketch (`deploy/docker-compose.prod.yml`)
```yaml
services:
  web:    { image: ghcr.io/<owner>/kolife-web:${TAG:-main}, restart: unless-stopped }
  api:
    image: ghcr.io/<owner>/kolife-api:${TAG:-main}
    command: sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"
    env_file: .env          # set in Dokploy, never committed
    depends_on: [postgres, redis]
    restart: unless-stopped
  worker:
    image: ghcr.io/<owner>/kolife-api:${TAG:-main}
    command: arq app.worker.WorkerSettings
    env_file: .env
    depends_on: [postgres, redis]
    restart: unless-stopped
  postgres: { image: postgres:16, volumes: [pgdata:/var/lib/postgresql/data], restart: unless-stopped }
  redis:    { image: redis:7, restart: unless-stopped }
volumes: { pgdata: {} }
```
Routing: nginx in `web` serves the SPA and proxies `/api` → `api:8000` (keeps one hostname for the tunnel), or Dokploy/Traefik domains per service. Cloudflare Tunnel `homelab` → HTTP `localhost:80`, Dokploy domain HTTPS off.

## 5. Environment variables (`.env.example`)
```
META_API_KEY=
META_BASE_URL=https://api.meta.ai/v1
ORCH_MODEL=muse-wonder-1.0          # fallback muse-spark-1.3 (effort max)
WORKER_MODEL=muse-spark-1.3
BASETEN_API_KEY=
BASETEN_MODEL=meta-models/muse-spark-open-1026
SPEND_CAP_USD_TOTAL=120
SPEND_CAP_USD_DAILY=20
DATABASE_URL=postgresql+asyncpg://...
REDIS_URL=redis://redis:6379/0
MASTER_KEY=                          # envelope-encryption master key
KAKAO_REST_KEY=
KAKAO_CLIENT_SECRET=
VITE_KAKAO_JS_KEY=                   # public
DATA_GO_KR_KEY=                      # KR holidays
JUSO_API_KEY=                        # KR address
PUBLIC_BASE_URL=
```

## 6. Scaffold timing (DECIDED)
Scaffold **right after kickoff (Oct 27 01:00 KST)**, not before — the FAQ says only work built during the hackathon may be showcased; first commits after kickoff are the cleanest proof. Before kickoff: setup only (accounts, keys, empty public repo, Dokploy apps + webhooks, tunnel route, Kakao app, samples, docs).

First commits after kickoff:
1. `web/` from Vite `react-ts` + Tailwind + PWA plugin
2. `api/` FastAPI + Alembic + `/health`
3. `worker/` ARQ
4. `docker-compose.yml` (dev) + `deploy/docker-compose.prod.yml`
5. `.github/workflows/build-and-deploy.yml` → GHCR → staging webhook
6. `.gitignore` (`.env`, `samples/`, `logs/`), `README.md`, `AGENTS.md`/`CLAUDE.md`
**Milestone 0: "hello world" through the whole pipeline to staging before any features.**

# KoLife

> ChatGPT answers questions. KoLife knows your Korean obligations before the letter arrives, tracks each one as a case, and tells you who to call — in your language, with your ID blurred.

AI life-admin assistant for foreigners in **Korea** (primary) and **Malaysia**. Built for the Meta Global AI Developer Hackathon 2026 (Indie track, *Build for Your World*).

**Built during the hackathon:** all application code in this repo was written after kickoff (Tue Oct 27 2026, 01:00 KST). The technical notes in `docs/` were written before kickoff as planning.

## Meta models
| Job | Model |
|---|---|
| Orchestrator (plans, routes, judges) | Muse Spark 1.3 @ `max` (Muse Wonder not available from Korea) |
| Workers (explain, draft, extract) | Muse Spark 1.3 |
| Open-weight worker (reply drafting) | Muse Spark Open via Baseten |
| Redaction (IDs, faces, QR) | SAM 3.1 |
| Call transcripts | Muse Voice Transcribe |

Built with Muse Spark Open.

## Stack
React + TypeScript + Vite PWA · FastAPI + SQLAlchemy/Alembic + Postgres · ARQ/Redis · GitHub Actions → GHCR → Dokploy.

## Run locally
```bash
cp .env.example .env            # add META_API_KEY etc.
brew install tesseract tesseract-lang   # local OCR for redaction (Linux: apt install tesseract-ocr tesseract-ocr-kor)
docker compose up postgres redis -d   # or a local Postgres: createdb kolife
cd api && uv sync && uv run alembic upgrade head
uv run uvicorn app.main:app --reload   # http://localhost:8000/api/health
cd web && npm install && npm run dev                         # http://localhost:5173
```
Or everything in containers: `docker compose up --build` → http://localhost:8080

## Disclaimer
KoLife explains, reminds and routes. It is not legal advice and never fills in or submits government forms. Replies are AI-drafted.

# 03 — KoLife architecture (runtime, agent design, privacy, locale packs)

> Status: **DECIDED** unless marked REC/OPEN. Stack specifics in `docs/05_stack_deployment.md`.

---

## 1. System structure (layers)

```
┌──────────────────────── Frontend · mobile-first PWA (React + TS + Vite) ────────────────────────┐
│  Profile setup        Case inbox (home)        Capture (camera/upload/record)        Trace panel │
└───────────────────────────────────────────────┬──────────────────────────────────────────────────┘
                                                │ HTTPS (REST) + SSE (live trace)
┌──────────────────────────────── Backend API · Python (FastAPI) ─────────────────────────────────┐
│  Redaction gate          Orchestrator (agent loop)          Case engine           Locale packs   │
│  (SAM + regex)           (Wonder + tools)                   (cases, calendar,     (kr, my)       │
│                                                             reminders)                           │
│                         ARQ worker (long agent runs, reminders, retention jobs)                  │
└───────────────┬──────────────────────────────────────────────────────────────┬──────────────────┘
                │                                                              │
┌───────────────▼──────────── Meta models ───────────┐   ┌──────────── Data & integrations ──────────────┐
│ Muse Wonder      · plans, delegates, judges         │   │ Postgres   · profiles, cases, events, usage    │
│ Muse Spark 1.3   · explains, drafts (workers)       │   │ Redis      · ARQ queue                         │
│ Muse Spark Open  · Baseten worker (open-weight)     │   │ File store · redacted files only (encrypted)   │
│ SAM 3.1          · redacts IDs / faces / QR         │   │ Kakao (KR) / WhatsApp (MY) · share, reminders  │
│ Voice Transcribe · transcribes call recordings      │   │ Maps · offices, routing                        │
│ Muse Image       · step cards (optional)            │   │ Public data · KR holidays, address (juso)      │
└─────────────────────────────────────────────────────┘   └────────────────────────────────────────────────┘
```

**The redaction gate is the only path into the orchestrator** — no raw image/ID number can reach Wonder/Spark/Spark Open by accident.

## 2. Main workflow — a student snaps a document

```
1. Snap or upload          (notice, bill, SMS screenshot, call recording)
        │
2. Redact first            SAM 3.1 blurs IDs, faces, QR, barcodes, seals (one concept per call, in parallel)
                           + regex on extracted text (ARC/IC/passport/phone/account) → placeholders [ARC_1]
        │
3. Plan and match          Muse Wonder classifies the doc and links it to an existing case / obligation
                           ("this is your September NHIS bill")
        │
   ┌────┴──────────────────────────────┐   (parallel)
4a. Explain                         4b. Draft reply
   Spark 1.3, user's language          Spark Open (Baseten) or Spark, Korean (or Malay/English),
   amount, deadline, consequence,      polite register + back-translation; labelled "AI-drafted"
   steps, official source
   └────┬──────────────────────────────┘
5. Update the case         case engine: deadlines (holiday-aware), reminders, contacts, status
        │
6. Show and route          steps, who to call (1345/1350/132 KR · EMGS/JIM/997 MY), share card, map pin
```
Every model call is logged (model, tokens, cached tokens, cost, latency) and streamed to the **trace panel**.

Explain-aloud branch (walkthrough): tap point on the redacted document → SAM 3.1 segments that region (point/phrase prompt) → UI highlight → Spark explains in user's language (cached per region) → browser `speechSynthesis` reads it aloud → optional voice follow-up recorded in browser → ffmpeg → Voice Transcribe → Wonder routes → spoken answer + case event. All calls logged to the trace panel.

Call-recording branch: upload audio → ffmpeg → mono 16-bit WAV 16 kHz, ≤10-min chunks → Voice Transcribe (diarized) → audio deleted → Wonder extracts agreed points + next steps → case updated. **Disabled in the Malaysia locale** (see §6).

## 3. Agent design (orchestrator)

### Roles
| Role | Model | Job |
|---|---|---|
| Orchestrator | `muse-wonder-1.0` (fallback `muse-spark-1.3` @ `max`) | plan, route, judge results, final synthesis — **never writes long content** |
| Workers | `muse-spark-1.3` | explanations, drafts, extraction, classification, summaries |
| Open-weight worker | Spark Open via Baseten `meta-models/muse-spark-open-1026` | e.g. reply drafting or back-translation (REC: one meaningful task, for the open-weight bonus) |
| Specialists (plain functions, not agents) | `sam-3.1`, `muse-voice-transcribe-1.0`, `muse-image-1.0` | perception / generation |
| Own tools | `fetch_official(url)`, `get_profile`, `get_cases`, `create_or_update_case`, `compute_deadline` | allowlisted official sources + app state |

### Core principles
1. **Wonder thinks, Spark writes.** Wonder output is ~5× Spark output price. Anything longer than a short paragraph is delegated.
2. **Short results back to Wonder.** Every tool returns compact JSON: `{artifact_id, status, summary (≤150 words), key_fields}`; full outputs stay in the artifact store keyed by ID.
3. **Batch tool calls.** Wonder is instructed to issue all independent calls in ONE turn; execute in parallel (`asyncio.gather`). (Remember `tool_choice` only accepts `auto`.)
4. **Specialists are plain functions** wrapping one API call, returning structured results.
5. **Reasoning continuity:** Responses API + `include=["reasoning.encrypted_content"]` + `store=False`; append full `response.output` items to the next input. **Never Chat Completions for the loop.**
6. **Stable prompt prefix** (system → tools → history) + `prompt_cache_key`; check `cached_tokens`.
7. **Effort:** Wonder `high` on turn 0 (plan) and final review only; `medium` otherwise. Spark `high` (drop routine steps to `medium` if over budget; never silently raise Wonder effort).

### Hard caps (enforced in code)
- Max **15** orchestrator turns per request → return partial results + clear message.
- Max **8** parallel workers per turn.
- Max **2** retries per tool call (429/500/503 with backoff + `Retry-After`).
- **Global spend cap** (daily + total, per environment) checked before every model call — Meta billing won't stop itself.
- Every loop has a cap. No model call inside an unbounded loop.

### Reference skeleton (Python — pattern; verify field names day 1)
```python
from openai import AsyncOpenAI
import os, json, asyncio

client = AsyncOpenAI(base_url="https://api.meta.ai/v1", api_key=os.environ["META_API_KEY"])
ORCH_MODEL = os.getenv("ORCH_MODEL", "muse-wonder-1.0")   # fallback: muse-spark-1.3 + effort "max"

ORCH_SYSTEM = """You are KoLife's orchestrator. You plan, delegate, and synthesize.
- Never write long content yourself; delegate it to spark_worker.
- Issue ALL independent tool calls in ONE turn.
- Use segment / transcribe / generate_image for vision, audio, image tasks.
- Only cite official sources returned by fetch_official.
- Explain, remind and route. Never fill in or submit government forms. Not legal advice.
- Tool results are summaries; full outputs are stored by artifact_id.
- Finish with a concise final answer that references artifact_ids."""

store: dict[str, str] = {}

async def spark_worker(task: str, context: str = "") -> str:
    r = await client.responses.create(
        model="muse-spark-1.3", reasoning={"effort": "high"}, store=False,
        input=f"{context}\n\nTask: {task}\nEnd with a SUMMARY section of at most 150 words.")
    aid = f"a{len(store)}"; store[aid] = r.output_text
    log_usage("muse-spark-1.3", r.usage)          # → model_calls table + SSE trace event
    return json.dumps({"artifact_id": aid, "summary": r.output_text.split("SUMMARY")[-1][:1200]})

HANDLERS = {"spark_worker": spark_worker}  # + segment, transcribe, generate_image, fetch_official, case tools

async def orchestrate(user_input, tools, max_turns=15):
    items = [{"role": "user", "content": user_input}]
    for turn in range(max_turns):
        check_spend_cap()
        r = await client.responses.create(
            model=ORCH_MODEL, instructions=ORCH_SYSTEM,
            reasoning={"effort": "high" if turn == 0 else "medium"},
            include=["reasoning.encrypted_content"], store=False,
            tools=tools, input=items)
        log_usage(ORCH_MODEL, r.usage, turn=turn)
        items += r.output
        calls = [o for o in r.output if o.type == "function_call"]
        if not calls:
            return r.output_text, store
        outs = await asyncio.gather(*[HANDLERS[c.name](**json.loads(c.arguments)) for c in calls[:8]])
        items += [{"type": "function_call_output", "call_id": c.call_id, "output": o} for c, o in zip(calls, outs)]
    return "Reached step limit; partial results saved.", store
```

### Day-1 verification tasks
Confirm exact request/response shapes for (a) Responses function tools, (b) `sam-3.1` (+ mask parsing in Python), (c) Voice transcribe, (d) Muse Image, (e) Baseten Spark Open, (f) structured output `text.format`. Write `scripts/smoke_test.py` that calls all models once and prints usage + cost. **Test Wonder from Seoul.**

## 4. Budget ($150 Meta credits; Baseten $100 separate)

| Bucket | Budget |
|---|---|
| Wonder orchestrator | ~$90 |
| Spark workers | ~$35 |
| SAM / Voice / Image | ~$10 |
| Demo-day buffer | ~$15 (don't touch before Nov 4) |

Rules: log `usage` + computed cost for **every** call (`model_calls` table + `logs/usage.jsonl`); `scripts/cost_report.py` per model per day; **mock/recorded responses** for UI work and tests; small sample media in tests; check dashboard daily.

## 5. Privacy & security design

### Redaction pipeline (every upload)
1. Upload to private storage (homelab volume / object store), **encrypted**.
2. **SAM 3.1** finds visual identifiers — one call per concept, in parallel: `"ID card"`, `"face"`, `"QR code"`, `"barcode"`, `"seal"` (KR 도장), `"signature"` → server blurs/blackboxes regions (Pillow/OpenCV) **before any other model call**.
3. **Text redaction** on extracted text (regex, per locale):
   - KR foreign registration number (ARC): `\b\d{6}[-\s]?[5-8]\d{6}\b` (13 digits, 7th digit 5–8 for foreigners). Don't rely on the old checksum — numbers issued since Oct 2020 have random digits.
   - MY: MyKad/IC pattern, i-Kad number, passport numbers, phone numbers, bank account numbers (both locales).
4. **Placeholders, not deletion:** `[ARC_1]`, `[PASSPORT_1]`; mapping encrypted server-side; refilled only in what the user sees.
5. Only then do Wonder/Spark/Spark Open see content.
6. **Audit log:** hash of each model payload + redaction counts ("2 IDs, 1 face blurred"), not the raw prompt. User-visible **"what left your device"** view.
7. User confirms the blurred preview (fallback if SAM misses something).

### Storage & retention
- Envelope encryption: data key per user wrapped by a master key from env/secret store; AES-GCM for documents/transcripts.
- Per-user access control on every query (Postgres RLS optional; enforce in API layer at minimum).
- Raw images/audio deleted after **7 days** (audio: right after transcription). Case summaries kept until user deletes. One-tap "delete everything".
- Kakao refresh tokens encrypted at rest; revoke on unlink.
- Store **only redacted files** on the homelab; encrypt the volume.

### Consent screens (onboarding)
- **AI notice** (KR AI Basic Act, in force 22 Jan 2026; MY AIGE guidelines): KoLife uses generative AI; drafts labelled "AI-drafted".
- **Cross-border transfer** (KR PIPA; MY PDPA 2024 amendments — transfer impact assessment / consent): separate screen naming Meta (and Baseten), the US, what is sent (redacted text/images), purpose, retention, right to refuse. Korea's EU adequacy (Sep 2025) doesn't cover the US.
- **Unique identifiers:** KoLife does not store ID numbers; if it ever must → separate consent + encryption.
- **Recording:** KR participant-only, user-started, audio deleted after transcription. **MY: call recording OFF** (CMA 1998 s.234).

### Deadlines & time
Store UTC; compute in `Asia/Seoul` (KR) / `Asia/Kuala_Lumpur` (MY); roll weekend/holiday deadlines to next working day. Seed holidays 2026–2028 (KR: KASI 특일정보 API on data.go.kr, re-sync monthly; MY: federal + state holidays).

## 6. Locale packs (Korea + Malaysia) — DECIDED

Engine is country-agnostic; everything country-specific lives in a pack:
```
backend/app/locales/
  kr/  obligations.yaml   # recurring obligations + rules (NHIS 25th, address change 14 days, visa ext window 4 months…)
       doc_types.yaml     # NHIS bill, management fee, lease notice, school notice, fine, scam text…
       contacts.yaml      # 1345, 1350, 132, NHIS, HiKorea, Danuri 1577-1366, BBB 1588-5644, licensed 행정사
       sources.yaml       # allowlisted official domains + "last checked" dates
       guardrails.yaml    # legal lines (Administrative Agents Act, Attorney Act, PIPA, AI Basic Act)
       regex.yaml         # ARC, passport, phone, account patterns
       flags.yaml         # call_recording: true, share_channel: kakao, payments: [bank, kakaopay, toss]
       prompts/           # reply etiquette (존댓말), explanation style
  my/  … same files …     # EMGS/JIM/i-Kad/insurance/attendance chain, 997 NSRC, PDPA, LPA s.37
       flags.yaml         # call_recording: false, share_channel: whatsapp, payments: [duitnow, fpx, tng]
```
- **Feature flags per locale** (not just content) — e.g. `call_recording` off in MY. Good "technical depth" point.
- **Don't hard-code fees/penalties** that vary (MY late fees per university; stamp duty rates conflict): read from the user's own notice, link to official calculators, show "last checked".
- Demo moment: switch country → same engine → new calendar + new routing.
- Malaysia detail: `docs/research/04_malaysia_locale_pack.md`.

## 7. Data model sketch (REC — refine at build)
- `users` (id, auth provider, locale, language, consent flags, created_at)
- `profiles` (user_id, country, visa_type, school, arrival_date, address_date, visa/pass_expiry, passport_expiry, lease_end, insurance_expiry…)
- `obligations` (generated from profile + locale pack: type, due_date, recurrence, source_id)
- `cases` (id, user_id, type, title, status, amount, currency, deadline, office, confidence, locale)
- `case_events` (case_id, kind: document|transcript|reply|scam_check|note, artifact_ref, created_at)
- `artifacts` (id, case_id, kind, encrypted_blob_ref, redaction_counts, expires_at)
- `reminders` (case_id/obligation_id, channel: kakao|push|email|whatsapp_link, send_at, sent_at)
- `model_calls` (id, request_id, model, turn, input_tokens, cached_tokens, output_tokens, cost_usd, latency_ms, created_at) → trace panel + spend cap
- `audit_log` (payload_hash, redaction_counts, model, created_at)

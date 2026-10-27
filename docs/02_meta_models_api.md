# 02 — Meta models, API details, Muse Code and coding-agent setup

> Compiled from research done Oct 21 2026 against dev.meta.ai docs + reviews, and the official hackathon FAQ (Oct 26).
> Anything marked **VERIFY** must be checked against https://dev.meta.ai/docs on day 1 before relying on it.

---

## 1. Model roster

| Role in KoLife | Model | ID | Price (Standard) | Modalities / context |
|---|---|---|---|---|
| **Orchestrator** | Muse Wonder | `muse-wonder-1.0` | **$4.00 in / $0.20 cached in / $20.00 out** per 1M tokens | 1M context; reasoning effort `minimal`→`max` (and `xhigh`); **preview** model |
| **Workers** | Muse Spark 1.3 | `muse-spark-1.3` | **$1.25 in / $0.15 cached / $4.25 out** per 1M | 1M context; vision, function calling, reasoning (incl. `max`), web search, prompt caching, structured output |
| Older workers | Muse Spark 1.1 / 1.2 | `muse-spark-1.1`, `muse-spark-1.2` | — | 1.1: 1M ctx, text/image/video/PDF input. **Muse Code defaults to 1.2.** |
| **Segmentation / redaction** | SAM 3.1 | `sam-3.1` | **$2.50 / 1,000 images; $0.20 / 1,000 video frames** | Text-prompted detect + segment + track in images and video |
| **Speech-to-text** | Muse Voice Transcribe | `muse-voice-transcribe-1.0` | **$0.18 / audio hour** | Diarization, turn detection, 25 languages. **No TTS. No word-level timestamps.** |
| **Image gen/edit** | Muse Image | `muse-image-1.0` | **$0.01 / image** | Agentic generation & editing (plans, self-corrects, refines) |
| **Open-weight worker** (bonus prize) | Muse Spark Open | Baseten: **`meta-models/muse-spark-open-1026`** | via Baseten/Modal/Fireworks credits | 816B total / 42B active, 1M ctx, text/image/video/audio input |
| Open-weight local | Muse Glimmer | open weights (Hugging Face) | self-host | ~30B open-weight **vision** model, Apache 2.0; 4-bit build ≈ 19 GiB VRAM (fits a 24 GB GPU, not a phone); built for always-on local agents. **VERIFY at kickoff.** |
| Tool | Web search | `{"type":"web_search"}` | **$2.50 / 1,000 queries** + tokens | **Cannot be domain-restricted** → build own `fetch_official` |

**Never use `*-contributor` model IDs** for anything touching user data — Meta trains on contributor traffic (contributor endpoint ~ $0.10/$0.20 for Spark).

### Rate limits (per team)
- Wonder & Spark: **3,000 RPM / 4M TPM**
- Muse Image: **150 RPM**
- SAM: **3,000 RPM**
- Voice: **256 concurrent streams**

---

## 2. Strengths & weaknesses (research, Oct 21)

### Muse Wonder
- **Strengths:** long multi-step coding/agentic tasks. DeepSWE 1.1: Wonder Full 79%, Wonder 78.8% vs Opus 5.5 74.2%, GPT-6 Astra 74.1%. Plans long tasks, delegates to sub-agents, parallel tool calls, error recovery, operates browsers/desktop/mobile apps.
- **Weaknesses:** not best overall — Artificial Analysis index: Wonder Full 56, Wonder 52 vs Claude Opus 5.5 58, Sonnet 5.5 56. Headline benchmarks are **Wonder Full**, which is only in Muse Code subscriptions (Power $50 / Max $200), not the public API. Preview label. Smaller Wonder trails on FocusBench. Output ≈ 5× Spark price.
- **Availability:** Meta's model docs said Wonder & Wonder Full **were not available in South Korea** (API or Muse Code). Geographic policy (updated Oct 12) doesn't list Korea but Meta controls availability technically. **Using a VPN to circumvent = rules violation → never.** **DECIDED: plan as if all models are usable; test from Seoul on day 1; fallback = Spark 1.3 at `max` effort as orchestrator (keep model ID in config).**
- **Tested Oct 26, 20:0x KST from Seoul:** `/v1/models` lists sam-3.1, muse-spark-1.1/1.2/1.3 (+contributor), muse-voice-transcribe-1.0, muse-image-1.0 — **no Wonder**. `POST /v1/responses` with `muse-wonder-1.0` → `404 model_not_found`; same call with `muse-spark-1.3` → 200. ⇒ Wonder blocked from Korea (or not enabled on this account). ~~Fallback active~~ → **Oct 27 ~14:00 KST smoke test: `muse-wonder-1.0` → 200 from Seoul, on the new key after rotation.** Cause unknown (per-key provisioning vs Meta enabling KR) → re-run `scripts/setup/check-wonder.sh` before committing budget. Wonder now usable; orchestrator choice per decision #30. Ask `#office-hours` whether hackathon participants in KR can get Wonder enabled; re-run `scripts/setup/check-wonder.sh` if Meta changes anything.

### Muse Spark 1.3
- **Strengths:** cheap (100K in / 20K out ≈ **$0.21**); MRCR 98.1 at 512K–1M; DeepSWE 75.4; ~20% fewer tool calls and ~25% fewer tokens than 1.2 (Meta self-reported).
- **Weaknesses:** wordy ("thinks out loud"); **slow first token** (stream in UI/demo); **audio understanding degraded/not fully supported → use Voice Transcribe for audio.**

### Muse Spark Open
- **Strengths:** 816B/42B active, 1M ctx, multimodal incl. audio, MCP-Atlas 89.2 (leads Meta's open table), ~102 tok/s vs median 68, fine-tunable.
- **Weaknesses:** AA index 39 vs GLM-5.3 45, Kimi K3 44; needs ≥700 GB GPU memory (NVFP4) self-hosted → use Baseten; **licence: products must display "Built with Muse Spark Open"**; usage policy excludes under-18 audiences.

### SAM 3.1
- One call → detections, pixel masks, video tracks with identity. Upgrade is mainly faster tracking, not better still-image accuracy. **One concept per request.**

### Muse Image / Voice Transcribe
- No independent reviews found (as of Oct 21).

---

## 3. API integration details (verified Oct 21 unless marked)

Base URL: `https://api.meta.ai/v1`. OpenAI-SDK compatible (swap model ID). Also natively speaks the **Anthropic Messages** format.

| Model | Endpoint | Key request details | Gotchas |
|---|---|---|---|
| Wonder / Spark | `POST /v1/responses` (https://dev.meta.ai/docs/protocols/responses) | Function tools; **parallel calls on by default**; `reasoning.effort` minimal→max; `store:false` + `include:["reasoning.encrypted_content"]` for stateless replay | **`tool_choice` only accepts `auto`** — steer via instructions, not forced calls |
| SAM 3.1 | `POST /v1/responses`, `model:"sam-3.1"` (https://dev.meta.ai/docs/sam/segmenting) | Short noun phrase + image or video | **One concept per request** ("face, QR code" returns nothing) → parallel calls per concept. Output = text lines with pixel boxes + **base85 masks**; parse with `@meta-sam/parser` (JS) / **`meta-sam-parser` (Python, verified Oct 27)**: regex `<\|mask;…data=<H>,<W>,<payload>\|>` → `SegmentationMask(encoding, payload_incl_marker, width=W, height=H)` → `decode_mask_to_raster()` → bytes of 0/1, len H·W. Box `x1;y1;x2;y2;w;h` in source px. Non-streamed works: text in `output[].content[].text` |
| Voice Transcribe | `POST /v1/asr/transcribe`; live `wss://api.meta.ai/v1/asr/realtime` (https://dev.meta.ai/docs/speech-to-text) | **multipart/form-data** (verified Oct 27): part `request` = JSON `{model, audioEncoding:"WAV", mode: PUSH_TO_TALK\|ENDPOINTING\|DIARIZATION, languageBias:["Korean"], keywords}`, part `audio` = WAV. No `sampleRate`/`diarization` fields. Response `{sessionId, transcript, audioDurationMs, turns[{turnId,startMs,endMs,transcript,speaker?}]}` (`turns` empty in PUSH_TO_TALK) | **Mono 16-bit WAV, 16/24 kHz, ≤32 MB, ≤10 min** → convert with ffmpeg, chunk long audio |
| Muse Image | `POST /v1/images/generations` (+ `/v1/images/edits`, or Responses) (https://dev.meta.ai/docs/image-generation) | `n` 1–10; `size` sets aspect ratio; base64 or temporary URL | 150 RPM; keep off the critical path |
| Web search | `{"type":"web_search"}` tool (https://dev.meta.ai/docs/search-grounding) | Location hint (KR, Asia/Seoul) | **No domain allowlist** → own `fetch_official(url)` tool |

### Patterns
- **Reasoning continuity:** always use the **Responses API** with `include=["reasoning.encrypted_content"]` and append full `response.output` items into the next request. **Chat Completions drops reasoning between turns** → repeated work / lost track. Never use Chat Completions for the agent loop.
- **Caching:** prefix caching is automatic; set a `prompt_cache_key` per prompt template; read `usage.input_tokens_details.cached_tokens`. Keep a stable prefix: system → tools → history; no timestamps/random IDs at the top.
- **Files:** uploaded files **never expire by default** → always set an expiry (e.g. 1 day); prefer inline base64 for redacted images (https://dev.meta.ai/docs/file-handling).
- **Errors:** retry 429/500/503 with exponential backoff, honour `Retry-After`.
- **Structured output:** ask the classifier step for JSON (case type, amount, deadline, office, confidence); validate with Pydantic. Responses shape **verified Oct 27**: `text={"format":{"type":"json_schema","name":"…","schema":{…,"additionalProperties":false},"strict":true}}` → JSON in output text.
- **Reasoning tokens** are included in `output_tokens` (`output_tokens_details.reasoning_tokens` ⊂ output, verified Oct 27) → bill as output.
- **Muse Image** (verified Oct 27): `POST /v1/images/generations` `{model, prompt, n, size:"1024x1024", output_format:"png"}` → `data[].b64_json`; ~12 s; 1024² PNG ≈ 2.5 MB.
- **Baseten** (verified Oct 27): `https://inference.baseten.co/v1/responses`, model `meta-models/muse-spark-open-1026` works, auto prefix caching.

### Data handling (PIPA / PDPA relevance)
- Standard mode doesn't train on your data; Contributor mode does.
- Standard keeps content "as needed" with no fixed period; zero-retention only via Meta sales.
- No page states where data is processed → **treat every call as a transfer to the US**: redact first, `store:false`, disclose in consent screen.

### Cost reference ($150 credits)
| Call | Price | ≈ calls on $150 |
|---|---|---|
| Spark 1.3, 100K in / 20K out | ~$0.21 | ~700 |
| Wonder, same size | ~$0.80 | ~185 |
| Wonder orchestrator turn (25K cached + 5K fresh in, 2K out) | **≈ $0.065** (no cache ≈ $0.16) | ~1,500 turns per $100 |
| SAM video | $0.20 / 1,000 frames | ~free |
| SAM image | $2.50 / 1,000 images | cheap |
| Muse Image | $0.01 / image | cheap |
| Voice | $0.18 / audio hour | ~free |

**Text tokens are what drain credits.** Specialists are nearly free.

### Python reference (pattern only — verify field names)
```python
from openai import OpenAI
import os
client = OpenAI(base_url="https://api.meta.ai/v1", api_key=os.environ["META_API_KEY"])

r = client.responses.create(
    model="muse-spark-1.3",
    reasoning={"effort": "high"},
    include=["reasoning.encrypted_content"],
    store=False,
    tools=TOOLS,
    input=items,
)
print(r.output_text, r.usage)
```

---

## 4. Muse Code (Meta's terminal coding agent) — dev workflow

### Install / launch
```bash
curl -fsSL https://dev.meta.ai/install.sh | sh        # macOS/Linux
# Windows: irm https://dev.meta.ai/install.ps1 | iex
muse --version
export META_API_KEY="..."                               # in ~/.zshrc; never commit
muse init                                               # creates AGENTS.md (Muse also reads CLAUDE.md if no AGENTS.md)
alias m='muse --model muse-spark-1.3 --reasoning-effort high'
```
- **Default model is `muse-spark-1.2`** → always launch with `--model muse-spark-1.3` or `/models`.
- Effort levels: `minimal` → `max`, plus `ultra` (triggers workflows more often). Switch with `/effort`.

### Plans
| Plan | Price | Includes |
|---|---|---|
| Everyday | $5/mo | Spark, Wonder, Image; 10–50 prompts / 5h |
| High | $15/mo | 5× Everyday |
| Power | $50/mo | + **Wonder Full**, 20× usage |
| Max | $200/mo | (mentioned) |
- **Subscriptions default to Contributor mode** (Meta trains on your code) → **turn it OFF**.
- Subscription only covers the key tied to the Muse Code CLI; any other API key is pay-as-you-go.
- **OPEN:** do the $150 hackathon credits cover Muse Code pay-as-you-go? Ask on Discord.
- Suggested split: coding sessions on a Muse Code subscription; $150 credits for the app + demo.

### Which model when (in Muse Code)
| Task | Model | Effort |
|---|---|---|
| Daily building, small features, fixes | `muse-spark-1.3` | high |
| Architecture, big multi-file refactors, stuck after 2 tries | `muse-wonder-1.0` (or Wonder Full on Power) | high / xhigh |
| Final review before submission | Wonder | max |
"Plan with Wonder, build with Spark, Wonder for hard bugs and the final review."

### Daily loop
| Step | Command | Why |
|---|---|---|
| Plan | `/plan` | Full plan, stops for approval |
| Stress-test | `/grill` | Challenges the plan, records agreed scope |
| Build | `/goal <feature + acceptance criteria>` | Works until every requirement is checked off |
| Parallelize | "spawn subagents, isolated worktrees for writers" | Up to 8 agents by default |
| Watch | `/subagents`, `/tasks` | Track agents |
| Context | `/compact`, `/fork`, `/side` | Summarize / branch / side question |
| Commit | **Keira, manually** | Muse Code won't commit/push unless asked |

### Other facts
- **Permissions:** Auto-review default (built-in judge approves routine actions, asks on risky ones); shell commands in an OS sandbox. `--yolo` only in a disposable container — **never on Keira's machine**.
- **Background observers (4, on by default):** memory recall, skill recall, goal tracking, verification — each costs tokens; turn off if credits run low.
- **Workflows** ("use a workflow", `/workflows`) are **rollout-gated** — the current Apple-silicon Mac build lacks the workflow engine. Plain subagents work.
- **Rewind** (double Esc) restores the old message as an unsent draft **in a new session and leaves files unchanged** → use git for real rollback.
- `/migrate` imports Claude Code memory + MCP servers. MCP config `~/.config/muse/settings.json` **must include `"schema_version": 1`** or every command fails.
- TypeScript Agent SDK (developer preview); inter-session messaging between terminals.
- Alternatives: **OpenCode** with the Meta API (Meta cookbook pairs them).

---

## 5. Claude Code on Meta's API (officially documented)

Meta's coding-agents doc (https://dev.meta.ai/docs/coding-agents) documents this:
```bash
export ANTHROPIC_BASE_URL="https://api.meta.ai"
export ANTHROPIC_AUTH_TOKEN="$META_API_KEY"          # AUTH_TOKEN, not ANTHROPIC_API_KEY
export ANTHROPIC_MODEL="muse-wonder-1.0"
export ANTHROPIC_DEFAULT_OPUS_MODEL="muse-wonder-1.0"
export ANTHROPIC_DEFAULT_SONNET_MODEL="muse-spark-1.3"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="muse-spark-1.3"
export CLAUDE_CODE_SUBAGENT_MODEL="muse-spark-1.3"
export ENABLE_TOOL_SEARCH="true"
```
⚠️ Bills **pay-as-you-go**; Wonder running every main-loop turn will eat the $150 fast → use a **separate key/billing**, or use Muse Code subscription. (Using normal Claude Code with Claude models for coding is also fine — the hackathon only requires the **product** to use Meta models; Muse Code is optional.)

---

## 6. Docs index (bookmark)
- Hackathon: https://dev.meta.ai/events/global-hackathon
- Models: https://dev.meta.ai/docs/models
- Pricing & rate limits: https://dev.meta.ai/docs/pricing-rate-limits
- Responses API: https://dev.meta.ai/docs/protocols/responses
- Reasoning: https://dev.meta.ai/docs/reasoning
- Tool calling: https://dev.meta.ai/docs/tool-calling
- Structured output: https://dev.meta.ai/docs/structured-output
- Prompt caching: https://dev.meta.ai/docs/prompt-caching
- File handling: https://dev.meta.ai/docs/file-handling
- Image understanding: https://dev.meta.ai/docs/image-understanding
- Search grounding: https://dev.meta.ai/docs/search-grounding
- SAM: https://dev.meta.ai/docs/media-segmentation , /docs/sam/overview , /docs/sam/segmenting , /docs/sam/reading-segmentation , /docs/cookbook/sam
- Speech-to-text: https://dev.meta.ai/docs/speech-to-text , /docs/api-reference/voice/transcribe , /docs/cookbook/muse-voice-transcribe
- Image generation: https://dev.meta.ai/docs/image-generation
- Muse Glimmer: /docs/muse-glimmer , /docs/muse-glimmer/hardware-platforms , /docs/muse-glimmer/quantization , /docs/cookbook/run-locally
- Auth / errors: /docs/authentication , /docs/error-handling
- Cookbook: https://dev.meta.ai/docs/cookbook
- Muse Code: https://dev.meta.ai/docs/muse-code (+ /configuration /extending /permissions /interactive /workflows /subscriptions /auth)
- Coding agents: https://dev.meta.ai/docs/coding-agents
- Geographic policy: https://dev.meta.ai/legal/geographic-use-policy
- Terms: https://dev.meta.ai/legal/terms-of-service · Help: https://dev.meta.ai/help
- LiteLLM provider page: https://docs.litellm.ai/docs/providers/meta

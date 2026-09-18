# GymRamp AI Course Factory — practice build

A working rehearsal of the **GymRamp AI Course Factory** job (see
`GymRamp AI Development Description.docx`), built before the client's full specification
arrives. Same topic, same chain, running for real on the local stack. When the real
requirements come in, this gets corrected to fit them rather than started over.

```
Research → Evidence analysis → Course script → PowerPoint + speaker notes → Narration
        → MP4 training video → Worksheet → Quiz + certification exam → Human approval → LMS
```

Nothing health-related is published without a person approving it. That is enforced by the
graph, not by a setting: `scripts/test-wiring.js` walks every path from every trigger and
fails the build if the LMS publish is reachable without passing the approval node.

---

## Status

| | |
|---|---|
| Deliverable | **Live in the local instance** + exported `*.workflow.json` |
| Workflows | 7 deployed, validated (0 errors), wiring verified — see [IDs](#deployed-workflows) |
| Active | **All inactive.** Course Factory and its sub-workflows were activated for the test run and deactivated on 2026-09-15 |
| Verification | see [Verification status](#verification-status) |

## Deployed workflows

| Key | Workflow | Nodes | Role |
|---|---|---|---|
| `factory` | **GymRamp · Course Factory** | 35 | Main pipeline. Webhook / form / radar → … → approval → LMS |
| `research` | GymRamp · Research Topic | 10 | Europe PMC + ClinicalTrials.gov → ranked evidence pack, upserted into `sources` |
| `analysis` | GymRamp · Evidence Analysis | 9 | Grades evidence; decides new / update / flag / no action |
| `content` | GymRamp · Build Course Content | 12 | Script, worksheet, quiz, exam → **Citation & Claim Gate** |
| `media` | GymRamp · Produce Media | 14 | Course worker → PPTX, MP4, DOCX; optional Supabase Storage copy |
| `radar` | GymRamp · Research Radar | 14 | Weekly scan of watch topics; only never-seen sources are analysed |
| `errors` | GymRamp · Error Handler | 4 | Marks the failed version, emails the real error |

IDs live in `config/deployed.json` (gitignored — instance-specific).

---

## How it maps to the job description

| GymRamp asks for | Here |
|---|---|
| Recurring research across literature and regulatory sources | **Research Radar**, weekly, 10 seeded watch topics (the modalities named in the brief) |
| Decide new course / update / flag / no action | **Evidence Analysis**: model proposes, code applies policy (min relevant sources, course history) |
| Don't reprocess research already reviewed | `sources` table, unique on DOI / PMID / NCT id. `INSERT … ON CONFLICT DO NOTHING RETURNING` — only new rows flow on |
| OpenAI / LLM integration, structured output | OpenAI models via OpenRouter; every LLM step has a JSON Schema parser with auto-fix |
| Traceable sources, reviewable claims | Writers may cite only `[E03]` markers; the gate computes references from DB records and stores every claim with its source |
| PowerPoint with consistent template + speaker notes | `course.pptx` from one layout spec; notes on every slide |
| AI video from presentation/script | `course.mp4`: each slide + its narration (ElevenLabs, edge-tts fallback) |
| Worksheets, quizzes, certification exams | `worksheet.docx`, `quiz.docx` (10 Q), `exam.docx` (20 Q, 80% pass), `answer-key.docx` |
| Admin review before publication | HTML review email → login-protected decision form (Approve / Request changes + notes). **Slack built and wired**, switched off |
| Database of courses, research, sources, versions, status | Postgres `gymramp` — **schema runs unchanged on Supabase** |
| LMS / Lovable / Supabase integration | `Publish To LMS (Mock)` writes the exact payload; swap for the real endpoint |
| Content Command Center | Not built — the tables it would read (`courses`, `course_versions`, `research_findings`, `assets`, `reviews`) exist |

---

## Architecture

```
                         ┌──────────── Course Request Webhook  (header token)
                         ├──────────── Course Request Form     (basic auth)
                         ├──────────── Called By Radar
                         ▼
  Normalize Request → Config → Create Course (courses + course_versions v+1)
        → [Research Topic] ─────────────── sources, research_runs
        → [Evidence Analysis] → Save Analysis (course_sources)
        → Produce Course? ── no ─→ Record Not Produced → Write + Email · Not Produced
        │ yes: new/update, or flagged with ≥ min relevant sources, or forced
        → [Build Course Content] → Save Content (claims, gate_report)
        → Gate Passed? ── no ─→ Write + Email · Gate Blocked      (no TTS spent)
        │ yes
        → [Produce Media] ───────────────── assets
        → Mark In Review → Build Review Message
        → Review Channel ─┬─ gmail → Gmail · Send Review Pack (HTML)
                          ├─ slack → Slack · Send Review Link (disabled until credentialed)
                          └─ other → Unknown Review Channel (error)
        → Wait For Decision (form behind basic auth, up to 7 days)
        → Normalize Decision → Record Review → Approved?
        → Publish To LMS (Mock) → Write + Email · Published

  every fallible node's error output → Mark Failed → Write + Email · Failure Alert
  anything that escapes → Error Handler workflow
```

The approval wait lives in the **main** workflow, not a sub-workflow, so the resume never
depends on a parent correctly waiting on a child that is itself waiting.

### The course-media worker (`worker/`)

The n8n container has no python, ffmpeg or package manager (repo CLAUDE.md), so media runs
in a sidecar at `http://host.docker.internal:8100`. It is built **FROM the YT autopilot
worker image** — ffmpeg and fonts come from that cache, making a rebuild one pip layer
instead of a 40-minute apt install. Separate container, so the YT autopilot is untouched.

| Output | How |
|---|---|
| `course.pptx` | python-pptx, drawn from one layout spec; speaker notes keep `[n]` markers for reviewers |
| slide frames | Pillow draws the **same** layout (no LibreOffice to convert PPTX) |
| narration | one clip per slide; ElevenLabs, all-or-nothing fallback to edge-tts so the voice never changes mid-video |
| `course.mp4` | slide PNG + clip per segment, identical encode params, stream-copy concat |
| DOCX | python-docx: worksheet, quiz, exam, answer key (answers, rationale, sources) |

Spend guard: `MAX_TTS_CHARS` (3,000) refuses the whole job **before** any character is paid
for. The gate enforces the same budget one step earlier. Renders are idempotent per
`(course_slug, version)`, so an n8n retry never pays twice.

---

## Emails

Every message is deterministic HTML from one kit (`code/email-kit.js`), in the same style as the
earlier newsletter projects: inline styles, nested tables, a centred 640px card, web-safe fonts,
no external images. Wording is plain English — internal codes such as `flag_review` or
`CURE_PROMISE` are translated before they reach the reader — and each email says what happened,
why, and what to do next. Sender name: *GymRamp Course Factory*.

| Email | When |
|---|---|
| Ready for your review | Course produced; flag banner, files, statements worth a second look, every claim with its sources, decision button |
| No course produced yet | Evidence did not support producing it |
| Needs changes before production | Content checks blocked the draft (no voice credits used) |
| Published | Approved and published |
| Course production stopped | A node failed |
| Research radar | Weekly digest |
| Workflow error | Anything the per-node handling did not catch |

`node scripts/preview-emails.js` renders all seven from real fixtures into `previews/`.

**Why not send-and-wait:** n8n's send-and-wait email HTML-escapes its message, so the reviewer
received a wall of plain text. The review is now an ordinary HTML email whose button opens the
Wait node's form (`$execution.resumeFormUrl`), protected by the same basic-auth login as the
request form.

## Decision policy

| Analyst decision | Course requested by an administrator | Radar |
|---|---|---|
| new / update | produced | recorded as a proposal (produced only with `auto_produce`) |
| flag for review, ≥ `min_relevant_sources` relevant | **produced**, flag leads the review email | recorded for a closer look |
| flag for review, fewer relevant | not produced (unless forced) | recorded |
| no action | not produced (unless forced) | recorded |

## The Citation & Claim Gate

A Code node, zero LLM calls, between the writers and anything a human is asked to approve.

| Check | Result |
|---|---|
| Marker not in the evidence pack | **blocking** `UNKNOWN_MARKER` |
| Author-year citation the writer made up | **blocking** `FREETEXT_CITATION` |
| Cure / "clinically proven" language (negated forms allowed) | **blocking** `CURE_PROMISE` |
| Statistic without a marker | **blocking** `UNCITED_STATISTIC` |
| Dose without a marker / with one | **blocking** / advisory `DOSE_STATED` |
| Start/stop/change medication | **blocking** `MEDICATION_INSTRUCTION` |
| "Our members…", "at our clinic…" | **blocking** `INVENTED_EXPERIENCE` |
| Disease treatment claim uncited / cited | **blocking** / advisory |
| Invalid question, no citations, over narration budget | **blocking** |
| Outcome-sounding sentence without a marker | advisory `UNCITED_CLAIM` — shown to the reviewer |

References are **computed** from the structured source rows, renumbered by first
appearance. Every narration sentence is stored in `claims` as cited / uncited / blocked with
its source markers, so any sentence in a course traces back to a `sources` row.

`scripts/test-gate.js` runs the gate's code **extracted from the generated workflow JSON**,
with `$input` mocked to throw, against positive, negative, and real-payload cases.

---

## What is not in this repository

Three things are gitignored because they are output or somebody else's code.

**`video-production/vendor/`** — two full upstream clones the video pipeline builds
on. They carry their own git history (HyperFrames' pack alone is 278 MB) and test
fixtures past GitHub's 100 MB hard limit, so they are fetched rather than committed:

| Vendored | Pinned at | Why pinned |
|---|---|---|
| [`heygen-com/hyperframes`](https://github.com/heygen-com/hyperframes) | `71b274bb` (v0.8.42, 2026-09-16) | Behaviour changes between releases. Several workarounds in `video-production/rendering/` are version-specific — the streaming-encode worker rule, the FFmpeg preflight retry, the staging-directory rescue. |
| [`browser-use/video-use`](https://github.com/browser-use/video-use) | `9575612f` (2026-08-30) | Presenter-extraction helpers. |

```bash
sh scripts/vendor.sh     # clones both at the pinned commits
```

**`.work/`** — render scratch, about 7,800 frames, contact sheets and per-take audio.
Regenerable.

**`samples/**/final.mp4`** — finished renders, 9–64 MB each. The `preview.mp4` files and
the contact sheets beside them are kept, so the samples still show what the pipeline
produces.

### One cross-project dependency

`worker/docker-compose.yml` and `worker/docker-compose.video.yml` both read
`../../yt-cross-domain-autopilot/worker/.env` for a shared `ELEVENLABS_API_KEY` — the
quota is shared with that pipeline, and `MAX_TTS_CHARS` is the guard. That path will not
resolve in a standalone clone. Either point `env_file` at a local `.env` or drop it and
set `ELEVENLABS_API_KEY` in the environment; without a key the worker falls back to
edge-tts.

---

## Setup (from scratch)

```bash
# 0. vendored upstreams the video pipeline needs
sh scripts/vendor.sh

# 1. database + role (password generated, never printed)
PW=$(node -e "console.log(require('crypto').randomBytes(24).toString('base64url'))")
docker exec -i postgres-db psql -U postgres -c "CREATE ROLE gymramp LOGIN PASSWORD '$PW'"
docker exec postgres-db psql -U postgres -c "CREATE DATABASE gymramp OWNER gymramp"
docker exec -i postgres-db psql -U postgres -d gymramp -c "SET ROLE gymramp;" -f - < sql/schema.sql
GYMRAMP_PG_PASSWORD="$PW" node scripts/create-credentials.js
node scripts/create-credentials.js --triggers      # webhook token + form login -> config/secrets.local.env

# 2. worker (needs the YT worker image to exist locally)
(cd worker && docker compose up -d --build)

# 3. workflows
node scripts/build-workflows.js && node scripts/test-gate.js && node scripts/test-wiring.js
node scripts/deploy.js && node scripts/deploy.js --verify
```

## Running it

```bash
set -a; . config/secrets.local.env; set +a
curl -X POST http://localhost:5678/webhook/gymramp/course \
  -H "$GYMRAMP_WEBHOOK_HEADER: $GYMRAMP_WEBHOOK_TOKEN" -H 'Content-Type: application/json' \
  -d '{"topic":"Cold water immersion for post-exercise recovery"}'
```

Or open the form at `http://localhost:5678/form/<form id>` (login in `secrets.local.env`).
Optional body fields: `audience`, `search_hint`, `force: true` (produce even if evidence is thin).

Radar, once, without activating it: `node scripts/run-radar-once.js`.

## Switches (Config node, editable in the n8n UI)

| Key | Default | Notes |
|---|---|---|
| `review_channel` | `gmail` | `slack` needs a `slackApi` credential + `slack_channel_id`, then redeploy (re-enables the node). Both channels lead to the same decision form |
| `storage_backend` | `local` | `supabase` needs `supabase_url` + a `supabaseApi` credential (`create-credentials.js --supabase-only`) |
| `tts_provider` | `elevenlabs` | `edge` for free narration |
| `auto_produce` | `false` | radar sends new/update findings straight to the factory when `true` |
| `min_relevant_sources` | `3` | policy floor for producing a course |

Moving to **Supabase Postgres**: run `sql/schema.sql` in the Supabase SQL editor, create the
credential with `GYMRAMP_PG_HOST/PORT/USER/DB/SSL` pointing at the pooler, update
`config/deploy.config.json` → `postgres`, redeploy. No node changes.

---

## Traps found while building

- **A Basic LLM Chain (1.9) with an output parser returned `{ output: {...} }`** — nested,
  the opposite of what the repo CLAUDE.md recorded for ChainLLM. Every reader here accepts
  both shapes; the gate test covers both.
- **`13.333 × 144` truncates to 1919 px** and libx264 refuses odd widths. The PPTX never
  notices; only the video dies. Canvas is pinned to 1920×1080.
- **Ranking by evidence strength + recency alone** put thyroiditis and orthodontic reviews
  ahead of exercise trials. The planner now returns `core_terms` (the modality's names — a
  record mentioning none is discarded) and `context_terms` (what makes it relevant to fitness
  professionals, used for scoring).
- **Writers put markers after the full stop** (`…tissue. [E02]`), so a naive sentence split
  hands the citation to the next sentence. The gate moves trailing markers back first.
- **The cure rule blocked "a recovery service, not a cure"** — the most responsible
  sentence in the course. Negated forms are allowed.
- **Ten full citations overflow one slide.** References paginate, 4 per slide.
- **n8n refuses to publish a workflow with a credential-less Slack node**, even on a branch
  that never runs. Deploy disables it until a credential exists; disabled fails closed
  (the decision reads as `expired`, never `approved`).
- **The analyst is not deterministic.** The same topic got `new_course` in one run and
  `flag_review` in the next, because the research set differed slightly between runs. That is why
  a flag on an administrator-requested course no longer stops production (see Decision policy).
- **Updating an active workflow over the public API republishes it** on this instance —
  `versionId` equals `activeVersionId` straight after a PUT. No separate re-activation needed.
- **Tool-channel escapes**: `̀` and `\n` typed through the build tooling became literal
  characters in source files twice. Code avoids `\u` escapes; generated line breaks use
  `String.fromCharCode(10)` where it matters.

## Verification status

Verified 2026-09-14 on the live instance.

| Check | Result |
|---|---|
| Build guards, gate suite (21 cases incl. 2 real payloads), wiring suite | **pass** |
| `validate_workflow` on all 7 | **0 errors** (warnings: intentional `executeOnce`, disabled Slack node) |
| Worker unit tests (9) | **pass** |
| Each sub-workflow in isolation (`test-subworkflow.js`) | **pass** — research 8-22 s, analysis 15 s, content 51 s, media 244 s (edge-tts) |
| End-to-end, execution 720 | **reached review**: 20 sources, gate passed (0 blocking), 11-slide PPTX with notes on every slide, 170.7 s MP4 narrated by **ElevenLabs** (2,428 characters), 7 files, review email sent |
| Webhook without the token | **403** |
| Human approval → publish | **Verified** — execution 720: form submitted "Approve and publish", `reviews` row, `lms_publications` row, version 3 `published`, Published email SENT |
| Radar, run once | **pass** — 10 topics, 10 findings, digest sent (242 s) |
| Dedupe | **pass** — across all runs searches returned 349 records; 240 rows exist in `sources` and exactly 240 were counted new. 109 already-seen records were skipped and no source was ever counted new twice. The second radar run's "new" sources were records the first run never stored (its narrower date window surfaced different papers), not reprocessing |

Earlier attempts, kept because they found real bugs: execution 713 blocked by a false-positive
cure rule; execution 717 stopped as "flagged" before the flag policy changed.

### Known limitations

- **Update targets are the analyst's judgement.** Run 2 proposed updating the red light course with
  longevity research. The code now rejects updates to courses that do not exist, but not updates to
  the wrong course; the reviewer sees the target in the digest.
- **Voice budget:** ElevenLabs free tier is shared with the YT autopilot (4,212 characters left this
  month after this test). Set `tts_provider` to `edge` for further test runs.
- **File links point at localhost:8100**, so they open only on this machine until Supabase Storage
  (or another host) is switched on.
- Content Command Center and the real LMS / Lovable integration are not built.

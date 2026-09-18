# GymRamp Video Production — Architecture

**Repository:** `workflows/gymramp-course-factory-hyperframe` (duplicate of the verified
`gymramp-course-factory` build, suffix `-hyperframe`)
**Status:** Phase 1 deliverable — discovery and design. No destructive change has been made.
**Date:** 16 September 2026 · n8n 2.32.6 · worker image `worker-yt-media-worker` base

---

## 1. Scope

Extend the **Media stage** of the existing Course Factory so an approved course becomes a
professionally produced instructional video in one of two selectable templates:

| Template | Primary layer | Chosen by |
|---|---|---|
| `faceless` | Designed motion graphics driven by narration | Reviewer, before publication |
| `face` | Human or HeyGen presenter, supported by overlays | Reviewer, before publication |

Everything upstream of Media is untouched: Research → Evidence Analysis → Production Decision →
Course Content → **Citation & Claim Gate** → Media → **Human Review** → LMS. The claim gate stays
upstream of media, and publication remains impossible without explicit human approval.

---

## 2. Existing media architecture (as found)

### 2.1 The pipeline today

```
Course Factory (factory.workflow.json)
  Gate Passed? ──true──▶ Produce Media (Execute Workflow, waits)
                            │
                            ▼
                   GymRamp · Produce Media (media.workflow.json, 14 nodes)
                     Start ▶ Start Render ▶ [Wait 20s ▶ Check Render ▶ Render Status]↻
                       ▶ Render Complete ▶ Record Assets ▶ (Supabase branch, off)
                       ▶ Return Media
                            │  HTTP: host.docker.internal:8100
                            ▼
                   gymramp-course-worker (worker/app.py, FastAPI)
                     POST /courses/render → job_id
                     GET  /jobs/{id}      → status, stage, files
                     GET  /jobs/{id}/files/{name}
                     DELETE /jobs/{id}
  Produce Media ▶ Mark In Review ▶ Build Review Message ▶ Review Channel
                ▶ Gmail · Send Review Pack ▶ Wait For Decision (form)
                ▶ Normalize Decision ▶ Record Review ▶ Approved? ▶ Publish To LMS (Mock)
```

### 2.2 Current inputs

The media sub-workflow is called with exactly three fields
(`buildFactory()` → `execWf('Produce Media', …)`):

| Field | Source | Shape |
|---|---|---|
| `version_id` | `Create Course` | integer (primary key of `course_versions`) |
| `package` | `Build Course Content` → Citation & Claim Gate | `CoursePackage` (below) |
| `config` | `Config` node | runtime config object |

`CoursePackage` (`worker/app.py`, Pydantic) is the approved, gate-checked course:

```
course_slug, version, title, subtitle, audience, intro_notes,
slides[]      { title, bullets[], notes (narration, may contain [n]), refs[] }
takeaways[], takeaways_notes,
references[]  { n, citation, url }
worksheet     { title, instructions, sections[] }
quiz, exam    { title, instructions, pass_mark_percent, questions[] }
disclaimer, tts_provider?
```

Citation markers in `notes` are already renumbered `[1]…[n]` by the gate, and `references[]` is
**computed from structured source records**, never written by a model. This is the contract the video
system must honour: on-screen citations come from `references[]` and `slides[].refs`, nothing else.

### 2.3 Current outputs

`_render()` in `worker/app.py` produces, per job directory:

| Artifact | How |
|---|---|
| `course.pptx` | python-pptx, speaker notes on every slide |
| `slide_NN.png` | Pillow draws the **same** `LAYOUT` spec at 1920×1080 |
| `audio_NN.mp3` | ElevenLabs (all-or-nothing) with edge-tts fallback, guarded by `MAX_TTS_CHARS` |
| `seg_NN.mp4` → `course.mp4` | one ffmpeg encode per slide with identical parameters, then `concat` **stream copy** |
| `worksheet/quiz/exam/answer-key.docx`, `sources.md` | python-docx |

Return contract to n8n: `{ job_id, files[], video_seconds, slide_count, tts_provider, … }`.
`Record Assets` writes one `assets` row per file kind; `Return Media` (Set, `executeOnce`) fixes the
shape for the caller.

**What the current video is:** one still slide per narration segment, 0.7 s padding, no captions, no
motion. That is the thing this project replaces — everything else in the chain is reusable as is.

### 2.4 Persistence

Database `gymramp` (Postgres, `host.docker.internal:5433`), tables relevant here:

| Table | Role in video work |
|---|---|
| `course_versions` | `slides`, `outline`, `gate_report` jsonb; `media_job_id`; `status`; `n8n_execution_id` |
| `assets` | one row per produced file, `UNIQUE (version_id, kind, storage_backend)` |
| `claims` | every narration sentence with `markers` and `cited/uncited/blocked` — the source of truth for what may appear on screen |
| `course_sources` | version ↔ source ↔ marker ↔ evidence level ↔ `cited` |
| `sources` | DOI/PMID/NCT, title, authors, year, journal — the evidence a card may display |
| `reviews` | channel, decision, comments |
| `lms_publications` | publish record, upsert per version |

### 2.5 Review flow (must be preserved)

`Build Review Message` (`code/build-review-message.js`) builds the HTML pack with `%%REVIEW_URL%%`;
`Gmail · Send Review Pack` substitutes `$execution.resumeFormUrl`; `Wait For Decision` (Wait 1.1,
`resume: form`, basic auth, 7-day limit) serves a form with **Decision** (dropdown) and **Comments**;
`Normalize Decision` fails closed (a timeout is `expired`, never approval); `Approved?` guards
`Publish To LMS (Mock)`. `scripts/test-wiring.js` asserts the publish node is unreachable without
passing `Wait For Decision`.

### 2.6 Tooling and conventions

- `scripts/build-workflows.js` generates all 7 `*.workflow.json` (node code from `code/*.js`, prompts
  from `prompts/*.txt`), with build guards: braces in prompts, cross-node `.item`, credentials in
  exports, connections naming unknown nodes.
- `scripts/deploy.js` creates or updates workflows in dependency order, attaches credentials **by node
  type**, substitutes `__WF_*__` placeholders, and disables optional nodes with no credential.
- Credentials live in n8n (ids in gitignored `config/deploy.config.json`); secrets never enter files.
- LLM steps: `chainLlm` 1.9 + `outputParserStructured` 1.3 (`schemaType: manual`, `autoFix`) + a fixer
  model. Parsed output is read as **both** `$json` and `$json.output`.
- Postgres nodes: `queryReplacement` as a single array expression, every element `(expr) ?? null`,
  and every query returns exactly one row.

### 2.7 Environment as found

| Item | State |
|---|---|
| Node | v24.18.0 (HyperFrames needs ≥ 22 ✔) |
| Python | 3.13.1 host; worker image has its own |
| Docker | 29.6.2; `gymramp-course-worker` up on 8100, `n8n` on 5678, `postgres-db` on 5433 |
| ffmpeg | present in the worker image |
| ElevenLabs | key present in `../yt-cross-domain-autopilot/worker/.env`; **1,200 characters remaining** |
| HeyGen | **no key anywhere on this machine** |
| Approved sample | worker job `red-light-therapy-…-v3-a68ea9`: `package.json` + 11 narration MP3s + `course.mp4` |

---

## 3. Integration points

| # | Point | File / node | Change |
|---|---|---|---|
| 1 | Media call | `buildFactory()` → `execWf('Produce Media')` | pass `video_template`, `presenter_source`, evidence for cards |
| 2 | Media sub-workflow | `media.workflow.json` (generated by `buildMedia()`) | after document/deck render, call the **video job API** and poll it |
| 3 | Worker API | `worker/app.py` | add `/video/jobs*` endpoints; keep `/courses/render` unchanged |
| 4 | Review pack | `code/build-review-message.js` | video preview link, storyboard link, current template, QA summary |
| 5 | Review form | `buildFactory()` → `Wait For Decision` | add **Video style** dropdown + two new actions |
| 6 | Decision handling | `code/normalize-decision.js` | four actions: approve / request changes / change style / regenerate |
| 7 | Loop back | factory connections | style change and regenerate re-enter media only, then return to review |
| 8 | Persistence | `sql/schema.sql` | `video_renders`, `video_assets`, `storyboards`, `course_versions.video_template` |
| 9 | Asset recording | `Record Assets` | record video artifacts with their own kinds and version |
| 10 | Config | `config/factory.config.json` | video defaults: template, resolution, fps, caption style, cache policy |

Renaming for the duplicate: every workflow becomes `GymRamp HF · …`, so the originals are never
touched. `config/deployed.json` has been emptied (original ids kept in
`config/deployed.original-ids.bak.json`), so `deploy.js` **creates** new workflows rather than
overwriting the live ones.

---

## 4. Proposed video architecture

### 4.1 Component map

```
n8n  GymRamp HF · Produce Media
        │ POST /video/jobs { course_video_input }
        ▼
gymramp-hf-video-worker  (FastAPI, port 8101)
        │
        ├── editing/      video-use wrappers  ── ElevenLabs Scribe (word timestamps, cached)
        │                 transcribe · cut plan · EDL · master.srt
        ├── storyboard/   beat parser → deterministic treatment rules → LLM refinement (OpenRouter)
        │                 → storyboard.json  (production artifact)
        ├── templates/    faceless · face · motion components (HyperFrames HTML compositions)
        ├── rendering/    HyperFrames driver (lint → render → check), scene cache, recomposite
        ├── qa/           technical · editorial · visual · content  → video_qa.json + report
        └── assets/       registry with licence and provenance per asset
```

HyperFrames renders **locally** (headless Chrome + ffmpeg, deterministic, seekable). No HeyGen
account is required for rendering; HeyGen is only a presenter source.

### 4.2 Data contract — `CourseVideoInput`

Built by n8n from data that already exists (approved package + evidence rows). The video system
never invents educational content.

```jsonc
{
  "course_id": 1, "course_version": 3, "version_id": 4,
  "title": "", "subtitle": "", "audience": "",
  "learning_objectives": [],
  "slides": [ { "title": "", "bullets": [], "notes": "", "refs": [1,2] } ],
  "narration_script": "",            // concatenation of approved notes, for editorial QA
  "narration_audio": [ { "index": 0, "path": "", "seconds": 0 } ],  // reuse approved audio if present
  "claims": [ { "slide_no": 1, "text": "", "markers": ["E04"], "status": "cited" } ],
  "references": [ { "n": 1, "citation": "", "url": "", "doi": "", "year": 2024,
                    "design": "rct", "population": "", "outcome": "" } ],
  "assessment_summary": { "quiz_questions": 10, "exam_questions": 20, "pass_mark_percent": 80 },
  "branding": { "tokens": "brand/*.json" },
  "media_preferences": { "resolution": "1920x1080", "fps": 30, "caption_style": "two_word_upper",
                         "visual_density": "balanced", "music": false },
  "video_template": "faceless",      // faceless | face | not_selected
  "presenter_source": null           // PresenterVideoSource when template = face
}
```

`PresenterVideoSource`: `{ source_type: "heygen" | "human", video_path, audio_path, duration,
speaker, transcript_id }`. Both adapters normalise to this, so the editor never knows which produced
it.

### 4.3 Job lifecycle

`queued → preparing → transcribing → storyboarding → generating_assets → composing → rendering →
quality_check → ready_for_review → approved → published`, and `failed` with `failure_stage`,
`failure_reason`, `retryable`. Persisted in `video_renders`; the worker also keeps `job.json` per job
(the existing pattern that survives a worker restart).

### 4.4 Faceless pipeline

1. **Narration** — reuse the approved `audio_NN.mp3` when the package version matches (free, already
   approved); otherwise ElevenLabs with the existing spend guard.
2. **Transcribe** — video-use `transcribe.py` → word-level timestamps, cached per audio hash.
3. **Beats** — parse the narration into teaching beats, evidence beats, emphasis points and
   transitions, using slide boundaries as a *hint*, never as the cut list. One slide may yield
   several visual states; several slides may share one continuous sequence.
4. **Storyboard** — every beat gets one of: `TITLE, TEXT_EMPHASIS, DIAGRAM, PROCESS, COMPARISON,
   STATISTIC, CHART, B_ROLL, IMAGE, SCREEN_CAPTURE, QUOTE, EVIDENCE_CARD, TIMELINE, ICON_SEQUENCE,
   SECTION_TRANSITION, RECAP` — or **nothing**, deliberately (quiet beats are allowed and expected).
   Deterministic rules decide first (evidence markers → `EVIDENCE_CARD`; a number with a unit →
   `STATISTIC`; "first/then/finally" → `PROCESS`; "versus/compared with" → `COMPARISON`; section
   openers → `SECTION_TRANSITION`). One structured LLM call then refines treatment, emphasis words
   and the `visual_reason`, constrained by a schema and validated against the approved text.
5. **Scenes** — each storyboard entry renders through a motion component into a cached scene clip
   (cache key = component + props + duration + brand token hash).
6. **Compose** — HyperFrames composition assembles scenes, then video-use `render.py` applies
   per-segment extract → concat → overlays → **subtitles last**, with 30 ms audio fades.
7. **QA** → preview + final.

### 4.5 Face pipeline

1. **Source** — human upload (Phase 4 test) or HeyGen generation (adapter, untested until a key
   exists), normalised to `PresenterVideoSource`.
2. **Transcribe** the presenter audio (word timestamps, cached).
3. **Edit** — filler words, false starts and dead air removed; retake selection when multiple takes
   exist; cuts snapped to word boundaries with 30–200 ms padding; natural pauses and deliberate
   emphasis preserved. Educational speech is not over-edited.
4. **Align** the delivered words to the approved narration script; material divergence is a QA
   failure, not a silent rewrite.
5. **Overlays** — lower thirds, evidence cards, keyword highlights, side-panel citations, charts.
   The presenter stays the primary layer: overlays are placed in free screen regions and never cover
   the face; no decorative animation over the presenter.
6. **Compose → subtitles last → QA.**

### 4.6 Motion system and design tokens

`video-production/brand/{colors,typography,spacing,motion}.json` is the single source of truth,
seeded from the existing palette (navy `#0B1F33`, accent `#FF6B2C`, text `#1B2733`, muted `#5B6673`,
rule `#E4E8EE`) and Montserrat, so video, deck and email look like one brand. Components take content,
duration and timing as props; no component hard-codes a brand value.

`TitleReveal · SectionIntro · KeywordHighlight · EvidenceCard · StatisticCard · ComparisonCard ·
ProcessFlow · Timeline · QuoteCard · ChartCard · LowerThird · SourceCitation · KeyTakeaway · Recap ·
Outro`

### 4.7 Review integration

The review pack gains: current template, video preview link, storyboard link, QA summary, and the
existing evidence/claims sections. The Wait form becomes:

- **Decision**: Approve and publish · Request changes · Change video style · Regenerate video
- **Video style**: Faceless · Presenter (persisted on the version)
- **Comments**

`Change video style` and `Regenerate video` re-enter the **media path only** and return to the same
review gate — research, analysis, content and the claim gate are never re-run. Approved renders are
immutable: a new style creates `video_face_v01` beside `video_faceless_v01`.

### 4.8 Quality control (nothing reaches a human unchecked)

| Family | Checks |
|---|---|
| Technical | valid MP4, streams present, duration matches EDL, fps, resolution, aspect, no missing assets |
| Editorial | rendered transcript vs approved script, captions vs narration, no clipped sentences, no duplicated audio, no pops at boundaries |
| Visual | captions visible and unoccluded, no text clipping, overlay timing, presenter not obscured, no black or frozen frames |
| Content | every on-screen citation exists in `references[]`/evidence, no new numeric claims, approved wording intact |

Self-evaluation loop: render → inspect → correct → re-render, **max 3 attempts**, then
`needs_manual_review` with `video_qa.json` and `VIDEO_QA_REPORT.md`. Failures are reported, never
hidden.

### 4.9 Caching and cost

Cache keys by content hash: transcripts (per audio), storyboard decisions (per narration + template +
prompt version), scene renders (per component + props), assets. A one-scene change recomposites that
scene only. Deterministic work — timing, file operations, validation, formatting, metadata, state —
stays in code; model calls are limited to editorial reasoning. An external call is made only after a
cache miss.

---

## 5. Files to modify / add

**Modify (in the duplicate only):** `scripts/build-workflows.js` (HF names, media call fields, review
form and actions), `code/build-review-message.js`, `code/normalize-decision.js`,
`sql/schema.sql`, `config/factory.config.json`, `worker/app.py` + `worker/Dockerfile` +
`worker/requirements.txt` + `worker/docker-compose.yml`, `README.md`.

**Add:** `video-production/{schemas,config,brand,templates/{faceless,face,motion},storyboard,editing,
rendering,qa,assets}/`, `docs/video-production/{ARCHITECTURE,VIDEO_STYLE_GUIDE,OPERATIONS}.md`,
`samples/{faceless,face}/`, `tests/video-production/`, `video-style.md`.

---

## 6. Assumptions

1. The approved `CoursePackage` is the only source of educational content; the video layer adds
   presentation, never information.
2. Slide boundaries inform pacing but do not define scenes.
3. Reusing the already-approved narration audio for samples is preferable to paying for new TTS, and
   is editorially safer (it is the audio a human already approved).
4. 1920×1080, 30 fps, H.264 + AAC, matching the current worker output.
5. The duplicate runs beside the original: its own database (`gymramp_hf`), its own worker container
   on 8101, its own inactive workflow copies.
6. Runtime reasoning is deterministic by default (rules + one structured LLM call); a full Claude Code
   agent pass is an explicit, per-course request.

## 7. Unresolved technical dependencies

| # | Item | Impact | Resolution |
|---|---|---|---|
| 1 | **ElevenLabs balance: 1,200 characters** | new narration or a new voice cannot be synthesised | reuse approved audio for samples; user tops up for a new voice |
| 2 | **Scribe transcription billing** (per minute, separate from TTS characters) | first transcription run costs money | confirm price and get a go-ahead before the first run |
| 3 | **No HeyGen key** | HeyGen adapter cannot be tested | build behind the interface, document, test when a key exists |
| 4 | **Talking-head file not yet supplied** | face sample blocked | needed at Phase 4 |
| 5 | **Chrome inside the worker image** | HyperFrames render fails without the right shared libraries | Phase 2 `hyperframes doctor` + a trivial render before anything else is built |
| 6 | **`npx skills add` needs network and writes skills** | install may be interactive | install project-level inside the duplicate; never touch the user's global skills |
| 7 | **Render time and disk** | long courses could be slow | scene cache, partial recomposite, per-job cleanup; 1.3 TB free today |
| 8 | **Reference video not transcribable** | styling detail from the linked YouTube video is unknown | follow official video-use and HyperFrames docs; ask the user for specifics |

## 8. Phases

1. **Discovery & architecture** (this document) ✔
2. Foundation — database, tooling install, worker image, schemas, brand tokens, HF workflow copies
3. Faceless template — motion system, storyboard engine, renderer, **real sample**
4. Face template — presenter adapters, **real sample**
5. Review integration — template selection and the four actions, publish gate intact
6. QA — four check families, self-evaluation loop, regression tests
7. Hardening — retries, caching, versioning, secrets, logging, concurrency, Docker, operations doc

Each phase ends with artifacts that have been inspected, not with a claim that the code compiles.

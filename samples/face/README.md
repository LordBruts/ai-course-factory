# Face template — sample output

`Red Light Therapy for Exercise Recovery`, the same course as `samples/faceless/`, delivered by
the presenter's own recording instead of synthesised narration. Produced 2026-09-18 from
`Talking-Head Video.mp4` (1080p HEVC, 259 s, one continuous take with retakes).

| | |
|---|---|
| Video | [final.mp4](final.mp4) — 1920×1080, 30 fps, 188.5 s, 64 MB |
| Preview | [preview.mp4](preview.mp4) — 960×540, 4.7 MB |
| Frames | [contact_sheet.png](contact_sheet.png) — 26 frames across the timeline |
| QA | [qa/VIDEO_QA_REPORT.md](qa/VIDEO_QA_REPORT.md) — **FAIL**, one editorial check (see below) |
| Provenance | [render_metadata.json](render_metadata.json) |

## How the screen is arranged

The layout director picks an arrangement per page and moves the presenter between them in the
pause the edit leaves between sections (`templates/face/layouts.py`).

| Page | s | Mode | What the viewer sees |
|---|---|---|---|
| B01 Hero + roadmap | 0.0–12.7 | glass | presenter full-frame, translucent title panel right |
| B02 What PBM is | 12.7–36.3 | pip | presenter in a small rounded window, page left |
| B03 How it may work | 36.3–57.5 | split | presenter in a tall right window, study card left |
| B04 The research gallery | 57.5–111.7 | pip | each study enters large, then docks |
| B05 Protocols | 111.7–139.0 | pip | variables grid builds as it is spoken |
| B06 Safety and scope | 139.0–165.9 | split | trials card, then do/don't tiles |
| B07 Key takeaways | 165.9–180.8 | glass | presenter full-frame, takeaway panel right |
| B08 Sources | 180.8–187.9 | glass | closing panel, then it fades for the last beat |

7 presenter moves, 3 punch-ins at jump cuts (1.00 ↔ 1.06). B02 and B05 were authored as `split`
and fall back to `pip` because their pages do not fit beside a 680 px window — the fallback is
deliberate, not a failure.

## How it is rendered

**The presenter is not in the composition.** `build_project.py` builds the pages alone over
transparency; `rendering/composite.py` rebuilds the presenter layer from the manifest's own
schedules and lays the pages over it in one ffmpeg pass:

```
hyperframes render --format webm   pages.webm   (alpha, 17 MB)
composite.py                       base.mp4     presenter track + pages + the edit's audio
timeline.py                        final.mp4    captions burned in, preview
```

A `<video>` inside the composition forces HyperFrames to screenshot every frame with the
presenter decoded in Chrome: **~1.2 s per frame** on this host against **0.15 s** for the pages
alone, memory that grows until capture stalls, and three renders lost between 40 minutes and
3.5 hours. The composite path renders the same 5,654 frames in ~37 minutes and composites them
in ~25. `templates/face/presenter_track.py` reproduces the CSS exactly — the same easing curve,
the same punch-in step function, the window clipped with anti-aliased corners — and the pages
keep real alpha, so a glass panel dims the presenter as a translucent panel over video should.

Measured on this run:

| Step | Time |
|---|---|
| pages render (5,654 frames, 1 worker, streaming encode) | 37 min |
| composite (3.7 frames/s) | 25 min |
| captions + preview | 6 min |
| QA | 8 min |

## The edit

25 approved sentences, 23 with a clean take, 18 kept ranges, 17 cuts — all between words.

- **"Welcome." was never said.** The video opens on "In this course…". Flagged `takes_complete: WARN`.
- **3 retakes dropped**, including the "servi–service" false start and two re-reads of "But one
  human study…"; the last clean read wins.
- **Asides cut**: the slide title "Key takeaways." and the recording instruction "When done, save
  the file…" — both spoken, neither in the approved script.
- **Numbers by value**: "eight oh eight" = 808, "six thirty plus eight fifty" = 630 + 850.

Audio: −16.5 LUFS integrated, true peak −0.7 dBFS. Video and audio agree within 8 ms.

## The one QA failure

`sections_match_script` fails on **Sources and next step, 88.4%** (threshold 92%). It is a genuine
misreading, not a tooling fault:

| Approved | Spoken |
|---|---|
| Every claim in this **course** | Every claim in this **source** |
| linked to the **sources** listed here | linked to the **source** listed here |
| before **your** certification exam | before certification exam |

The board on screen shows the approved wording, so the text and the voice disagree for those two
sentences. Re-recording them is the fix; every other section scores 94–100%.

## Cost

One paid call for the whole phase: ElevenLabs Scribe, **274 credits** for 246.7 s of audio
(balance 8,978 → 9,252 used of 10,000). The transcript is cached by audio hash under
`/data/cache/transcripts`, so re-running the pipeline never re-buys it.

## Reproducing

```bash
docker exec gymramp-hf-video-worker python3 /app/video-production/rendering/run_job.py \
  --job /data/video-jobs/rlt-v3-face --template face \
  --title "Red Light Therapy for Exercise Recovery" --recording <path in the container>
```

Add `--allow-paid` only when no cached transcript exists. `--from-step render` resumes after the
presenter steps. See [RECORDING_SCRIPT.md](RECORDING_SCRIPT.md) for what to send a presenter.

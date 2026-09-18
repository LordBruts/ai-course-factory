# Faceless sample: Red Light Therapy for Exercise Recovery (v3)

Rendered from the **approved** v3 course package using its **existing** ElevenLabs narration.
No new speech was generated and no LLM was called. The only paid call was ElevenLabs Scribe
(transcription of 160 s of narration, cached in `../source/transcripts/`).

| File | What it is |
|---|---|
| `final.mp4` | 1920×1080, 30 fps, H.264 + AAC, 160.03 s. HyperFrames render with captions burned in last |
| `preview.mp4` | 960×540 review copy of `final.mp4` |
| `storyboard.json` | Every beat: verbatim narration, word-level timing, visual treatment and the reason for it |
| `edit/edl.json` | Output timeline: which approved narration file plays where (the faceless template never cuts speech) |
| `edit/master.srt` | Output-timeline captions, 197 two-word cues (video-use `build_master_srt`) |
| `edit/takes_packed.md` | video-use phrase-level transcript view |
| `qa/video_qa.json` | Machine-readable QA gate result: **pass** |
| `qa/VIDEO_QA_REPORT.md` | The same, for a reviewer, with the correction history |
| `qa/contact_sheet.png` | 16 frames sampled from `final.mp4` |
| `qa/hyperframes_check.json` | HyperFrames layout, caption-band and contrast report |
| `render_metadata.json` | Tool versions, timings, SHA-256 of every output and narration source, paid calls |
| `attempts/1`, `attempts/2` | QA reports of the earlier attempts, kept so the history is auditable |

## How it got to a pass

| Attempt | Result | What was wrong | Fixed by |
|---|---|---|---|
| 1 | fail | 19.4 s static hold; a decorative mark hidden under scenes, low contrast, touching the caption band | Bullet matching understands numbers and units; mark removed |
| 2 | pass (QA) | Found by inspecting frames, not by QA: a "48 hours" headline above a finding that, as shown, was about one hour; the closing title shown twice | Headline figures only from the text on the card (validator enforces it); duplicate title dropped |
| 3 | pass | The layout check timed out once on a busy host (a tooling failure, not a video defect) | The check retries and cannot pass without running |

Narration matches the approved script at 100% of 375 words, after normalising digits to
spoken words and British to American spelling. Captions cover 100% of spoken words.
Every one of the 10 citations on screen resolves to the approved reference list.

## Regenerate

```
python video-production/storyboard/build.py --package samples/source/package.json \
    --durations samples/source/durations.json --transcripts samples/source/transcripts \
    --out samples/faceless/storyboard.json
```

Then, inside `gymramp-hf-video-worker`: `rendering/build_project.py`, then `hyperframes render`,
then `editing/timeline.py`, then `qa/checks.py`. See `docs/video-production/OPERATIONS.md` (Phase 7).

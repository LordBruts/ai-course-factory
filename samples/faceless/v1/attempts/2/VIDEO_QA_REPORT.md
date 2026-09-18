# Video QA report

| | |
|---|---|
| Status | **PASS** |
| Job | `rlt-v3-faceless` |
| Template | faceless |
| Attempt | 2 |
| Duration | 160.03 s (EDL 160.03 s) |
| Narration vs approved script | 96.9% of 361 words |
| Caption cues | 197 |
| Scenes | 20 |
| Longest still hold | 12.3 s |
| Generated | 2026-09-17T09:18:05+00:00 |

## Technical

| Check | Result | Detail |
|---|---|---|
| container_valid | PASS |  |
| video_stream | PASS |  |
| audio_stream | PASS |  |
| duration_matches_edl | PASS |  |
| frame_rate | PASS |  |
| resolution | PASS |  |
| assets_present | PASS | 9 narration files placed, hashes match the approved sources |

## Editorial

| Check | Result | Detail |
|---|---|---|
| narration_matches_script | PASS | 96.9% of 361 approved words |
| captions_match_narration | PASS | 197 cues cover 100.0% of spoken words |
| no_clipped_sentences | PASS |  |
| no_duplicated_audio | PASS |  |
| cut_boundaries | PASS | faceless template: approved narration is never cut |
| audio_pops | PASS | no cuts, so no cut points to fade |

## Visual

| Check | Result | Detail |
|---|---|---|
| captions_visible | PASS | caption present at 6 sampled cues |
| caption_occlusion | PASS |  |
| text_overflow | PASS |  |
| text_contrast | PASS |  |
| overlay_timing | PASS | all 20 visuals start within 0.35s of their beat |
| presenter_visible | skipped | faceless template has no presenter |
| black_frames | PASS |  |
| frozen_frames | PASS | longest still hold 12.3s, within the 16s scene limit |

## Content

| Check | Result | Detail |
|---|---|---|
| citations_supported | PASS | 10 distinct citations, all in the approved reference list |
| no_new_claims | PASS |  |
| approved_wording_intact | PASS |  |

## Corrections from earlier attempts

| Attempt | Check | Action |
|---|---|---|
| 1 | frozen_frames | S015 had no approved screen text, so S014 held 19.4 s. Bullet matching now understands numbers and units ('650 nanometre' = '650 nm'); S015 shows its approved slide bullet. |
| 1 | text_overflow | Removed the decorative GYMRAMP mark from the base layer: it sat under every opaque scene (occluded) and failed WCAG contrast. |
| 1 | caption_occlusion | Same mark touched the reserved caption band; removed with it. |
| 1 | qa_classification | Check findings are now classified by code; MP3 encoder-padding and track-density notes are recorded as accepted advisories with reasons. |

## Accepted advisories

- `timeline_track_too_dense`: Track 1 has 20 timed elements in this HTML file. Smaller sub-compositions keep timelines easier to read, iterate on, and diff.. *authoring-style tip; the composition is generated, not hand-maintained*
- `clip_media_fit`: Audio "aud-00" is 12.40s but its slot (data-duration) is 12.46s — the slot is shortened to the media length when rendered. Set data-duration to ~12.40s if that isn't intended.. *MP3 encoder padding: the frame-count duration exceeds the decoded length by under 150 ms, leaving a silent gap between files, not drift*
- `clip_media_fit`: Audio "aud-01" is 21.18s but its slot (data-duration) is 21.24s — the slot is shortened to the media length when rendered. Set data-duration to ~21.18s if that isn't intended.. *MP3 encoder padding: the frame-count duration exceeds the decoded length by under 150 ms, leaving a silent gap between files, not drift*
- `clip_media_fit`: Audio "aud-02" is 17.41s but its slot (data-duration) is 17.48s — the slot is shortened to the media length when rendered. Set data-duration to ~17.41s if that isn't intended.. *MP3 encoder padding: the frame-count duration exceeds the decoded length by under 150 ms, leaving a silent gap between files, not drift*
- `clip_media_fit`: Audio "aud-03" is 21.50s but its slot (data-duration) is 21.58s — the slot is shortened to the media length when rendered. Set data-duration to ~21.50s if that isn't intended.. *MP3 encoder padding: the frame-count duration exceeds the decoded length by under 150 ms, leaving a silent gap between files, not drift*
- `clip_media_fit`: Audio "aud-04" is 20.34s but its slot (data-duration) is 20.40s — the slot is shortened to the media length when rendered. Set data-duration to ~20.34s if that isn't intended.. *MP3 encoder padding: the frame-count duration exceeds the decoded length by under 150 ms, leaving a silent gap between files, not drift*
- `clip_media_fit`: Audio "aud-05" is 25.36s but its slot (data-duration) is 25.42s — the slot is shortened to the media length when rendered. Set data-duration to ~25.36s if that isn't intended.. *MP3 encoder padding: the frame-count duration exceeds the decoded length by under 150 ms, leaving a silent gap between files, not drift*
- `clip_media_fit`: Audio "aud-06" is 21.64s but its slot (data-duration) is 21.71s — the slot is shortened to the media length when rendered. Set data-duration to ~21.64s if that isn't intended.. *MP3 encoder padding: the frame-count duration exceeds the decoded length by under 150 ms, leaving a silent gap between files, not drift*
- `clip_media_fit`: Audio "aud-07" is 12.31s but its slot (data-duration) is 12.38s — the slot is shortened to the media length when rendered. Set data-duration to ~12.31s if that isn't intended.. *MP3 encoder padding: the frame-count duration exceeds the decoded length by under 150 ms, leaving a silent gap between files, not drift*
- `clip_media_fit`: Audio "aud-08" is 7.29s but its slot (data-duration) is 7.37s — the slot is shortened to the media length when rendered. Set data-duration to ~7.29s if that isn't intended.. *MP3 encoder padding: the frame-count duration exceeds the decoded length by under 150 ms, leaving a silent gap between files, not drift*

## Scope of these checks

Narration fidelity is measured on the cached Scribe transcripts of the exact audio files placed in the render; the files' SHA-256 hashes are checked against the approved sources. The rendered mix itself is not re-transcribed, which would be a second paid call.

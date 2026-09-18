# Video QA report

| | |
|---|---|
| Status | **FAIL** |
| Job | `rlt-v3-faceless` |
| Template | faceless |
| Attempt | 1 |
| Duration | 160.03 s (EDL 160.03 s) |
| Narration vs approved script | 96.9% of 361 words |
| Caption cues | 197 |
| Scenes | 19 |
| Longest still hold | 19.43 s |
| Generated | 2026-09-17T09:01:30+00:00 |

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
| caption_occlusion | FAIL |  |
| text_overflow | FAIL |  |
| overlay_timing | PASS | all 19 visuals start within 0.35s of their beat |
| presenter_visible | skipped | faceless template has no presenter |
| black_frames | PASS |  |
| frozen_frames | FAIL |  |

## Content

| Check | Result | Detail |
|---|---|---|
| citations_supported | PASS | 10 distinct citations, all in the approved reference list |
| no_new_claims | PASS |  |
| approved_wording_intact | PASS |  |

## Errors

- **frozen_frames**: picture static for 19.4s (limit 16s)
- **text_overflow**: {"code": "text_occluded", "severity": "error", "time": 100.017, "selector": "div.base-mark", "message": "Text is hidden beneath an opaque element.", "rect": {"left": 120, "top": 769.41, "right": 290.78, "bottom": 803.41, "width": 170.78, "height": 34}, "containerSelector": "#sc-s014", "text": "GYMRA
- **caption_occlusion**: {"selector": "div.base-mark", "dataAttributes": {}, "sourceFile": "index.html", "bbox": {"x": 120, "y": 769.41, "width": 170.78, "height": 34}, "time": 160.027, "rect": {"left": 120, "top": 769.41, "right": 290.78, "bottom": 803.41, "width": 170.78, "height": 34}, "code": "caption_zone_collision", "

## Warnings

- **text_overflow**: {"code": "timeline_track_too_dense", "severity": "warning", "message": "Track 1 has 19 timed elements in this HTML file. Smaller sub-compositions keep timelines easier to read, iterate on, and diff.", "selector": "[data-composition-id]", "dataAttributes": {}, "sourceFile": "/data/video-jobs/rlt-v3-f
- **text_overflow**: {"code": "clip_media_fit", "severity": "warning", "message": "Audio \"aud-00\" is 12.40s but its slot (data-duration) is 12.46s \u2014 the slot is shortened to the media length when rendered. Set data-duration to ~12.40s if that isn't intended.", "selector": "[data-composition-id]", "dataAttributes"
- **text_overflow**: {"code": "clip_media_fit", "severity": "warning", "message": "Audio \"aud-01\" is 21.18s but its slot (data-duration) is 21.24s \u2014 the slot is shortened to the media length when rendered. Set data-duration to ~21.18s if that isn't intended.", "selector": "[data-composition-id]", "dataAttributes"
- **text_overflow**: {"code": "clip_media_fit", "severity": "warning", "message": "Audio \"aud-02\" is 17.41s but its slot (data-duration) is 17.48s \u2014 the slot is shortened to the media length when rendered. Set data-duration to ~17.41s if that isn't intended.", "selector": "[data-composition-id]", "dataAttributes"
- **text_overflow**: {"code": "clip_media_fit", "severity": "warning", "message": "Audio \"aud-03\" is 21.50s but its slot (data-duration) is 21.58s \u2014 the slot is shortened to the media length when rendered. Set data-duration to ~21.50s if that isn't intended.", "selector": "[data-composition-id]", "dataAttributes"
- **text_overflow**: {"code": "clip_media_fit", "severity": "warning", "message": "Audio \"aud-04\" is 20.34s but its slot (data-duration) is 20.40s \u2014 the slot is shortened to the media length when rendered. Set data-duration to ~20.34s if that isn't intended.", "selector": "[data-composition-id]", "dataAttributes"
- **text_overflow**: {"code": "clip_media_fit", "severity": "warning", "message": "Audio \"aud-05\" is 25.36s but its slot (data-duration) is 25.42s \u2014 the slot is shortened to the media length when rendered. Set data-duration to ~25.36s if that isn't intended.", "selector": "[data-composition-id]", "dataAttributes"
- **text_overflow**: {"code": "clip_media_fit", "severity": "warning", "message": "Audio \"aud-06\" is 21.64s but its slot (data-duration) is 21.71s \u2014 the slot is shortened to the media length when rendered. Set data-duration to ~21.64s if that isn't intended.", "selector": "[data-composition-id]", "dataAttributes"
- **text_overflow**: {"code": "clip_media_fit", "severity": "warning", "message": "Audio \"aud-07\" is 12.31s but its slot (data-duration) is 12.38s \u2014 the slot is shortened to the media length when rendered. Set data-duration to ~12.31s if that isn't intended.", "selector": "[data-composition-id]", "dataAttributes"
- **text_overflow**: {"code": "clip_media_fit", "severity": "warning", "message": "Audio \"aud-08\" is 7.29s but its slot (data-duration) is 7.37s \u2014 the slot is shortened to the media length when rendered. Set data-duration to ~7.29s if that isn't intended.", "selector": "[data-composition-id]", "dataAttributes": {
- **text_overflow**: {"code": "text_occluded", "severity": "info", "time": 6.668, "selector": "div.base-mark", "message": "Text is hidden beneath an opaque element.", "rect": {"left": 120, "top": 769.41, "right": 290.78, "bottom": 803.41, "width": 170.78, "height": 34}, "containerSelector": "#sc-s001", "text": "GYMRAMP"
- **text_overflow**: {"code": "text_occluded", "severity": "info", "time": 20.003, "selector": "div.base-mark", "message": "Text is hidden beneath an opaque element.", "rect": {"left": 120, "top": 769.41, "right": 290.78, "bottom": 803.41, "width": 170.78, "height": 34}, "containerSelector": "#sc-s004", "text": "GYMRAMP
- **text_overflow**: {"code": "text_occluded", "severity": "info", "time": 33.339, "selector": "div.base-mark", "message": "Text is hidden beneath an opaque element.", "rect": {"left": 120, "top": 769.41, "right": 290.78, "bottom": 803.41, "width": 170.78, "height": 34}, "containerSelector": "#sc-s005", "text": "GYMRAMP
- **text_overflow**: {"code": "text_occluded", "severity": "info", "time": 46.675, "selector": "div.base-mark", "message": "Text is hidden beneath an opaque element.", "rect": {"left": 120, "top": 769.41, "right": 290.78, "bottom": 803.41, "width": 170.78, "height": 34}, "containerSelector": "#sc-s007", "text": "GYMRAMP
- **text_overflow**: {"code": "text_occluded", "severity": "info", "time": 60.01, "selector": "div.base-mark", "message": "Text is hidden beneath an opaque element.", "rect": {"left": 120, "top": 769.41, "right": 290.78, "bottom": 803.41, "width": 170.78, "height": 34}, "containerSelector": "#sc-s009", "text": "GYMRAMP"
- **text_overflow**: {"code": "text_occluded", "severity": "info", "time": 73.346, "selector": "div.base-mark", "message": "Text is hidden beneath an opaque element.", "rect": {"left": 120, "top": 769.41, "right": 290.78, "bottom": 803.41, "width": 170.78, "height": 34}, "containerSelector": "#sc-s011", "text": "GYMRAMP
- **text_overflow**: {"code": "text_occluded", "severity": "info", "time": 86.681, "selector": "div.base-mark", "message": "Text is hidden beneath an opaque element.", "rect": {"left": 120, "top": 769.41, "right": 290.78, "bottom": 803.41, "width": 170.78, "height": 34}, "containerSelector": "#sc-s013", "text": "GYMRAMP
- **text_overflow**: {"code": "text_occluded", "severity": "info", "time": 126.688, "selector": "div.base-mark", "message": "Text is hidden beneath an opaque element.", "rect": {"left": 120, "top": 769.41, "right": 290.78, "bottom": 803.41, "width": 170.78, "height": 34}, "containerSelector": "#sc-s017", "text": "GYMRAM
- **text_overflow**: {"code": "text_occluded", "severity": "info", "time": 140.024, "selector": "div.base-mark", "message": "Text is hidden beneath an opaque element.", "rect": {"left": 120, "top": 769.41, "right": 290.78, "bottom": 803.41, "width": 170.78, "height": 34}, "containerSelector": "#sc-s018", "text": "GYMRAM
- **text_overflow**: {"code": "text_occluded", "severity": "info", "time": 153.359, "selector": "div.base-mark", "message": "Text is hidden beneath an opaque element.", "rect": {"left": 120, "top": 769.41, "right": 290.78, "bottom": 803.41, "width": 170.78, "height": 34}, "containerSelector": "#sc-s024", "text": "GYMRAM
- **text_overflow**: {"code": "text_occluded", "severity": "info", "time": 160.027, "selector": "div.base-mark", "message": "Text is hidden beneath an opaque element.", "rect": {"left": 120, "top": 769.41, "right": 290.78, "bottom": 803.41, "width": 170.78, "height": 34}, "containerSelector": "#sc-s025", "text": "GYMRAM
- **text_overflow**: {"code": "contrast_aa_failure", "severity": "warning", "message": "Contrast is 2.86:1; WCAG AA requires 3:1.", "text": "GYMRAMP", "fg": "rgb(91,102,115)", "bg": "rgb(11,31,51)", "ratio": 2.86, "requiredRatio": 3, "suggestedColor": "rgb(95,106,118)", "large": true, "selector": "div > div:nth-of-type(

## Scope of these checks

Narration fidelity is measured on the cached Scribe transcripts of the exact audio files placed in the render; the files' SHA-256 hashes are checked against the approved sources. The rendered mix itself is not re-transcribed, which would be a second paid call.

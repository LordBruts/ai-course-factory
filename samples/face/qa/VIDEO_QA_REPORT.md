# Video QA report

| | |
|---|---|
| Status | **FAIL** |
| Job | `rlt-v3-face` |
| Template | face |
| Attempt | 1 |
| Duration | 188.48 s (EDL 188.47 s) |
| Narration vs approved script | 95.0% of 361 words |
| Caption cues | 198 |
| Scenes | 23 |
| Longest still hold | 0.0 s |
| Generated | 2026-09-18T11:03:35+00:00 |

## Technical

| Check | Result | Detail |
|---|---|---|
| container_valid | PASS |  |
| video_stream | PASS |  |
| audio_stream | PASS |  |
| duration_matches_edl | PASS |  |
| frame_rate | PASS |  |
| resolution | PASS |  |
| assets_present | PASS | 1 source file(s) placed, hashes match |

## Editorial

| Check | Result | Detail |
|---|---|---|
| narration_matches_script | PASS | 95.0% of 361 approved words |
| sections_match_script | FAIL |  |
| takes_complete | WARN | 23 of 25 sentences have a clean take; 3 retakes dropped |
| captions_match_narration | PASS | 198 cues cover 99.5% of spoken words |
| no_clipped_sentences | PASS |  |
| no_duplicated_audio | PASS |  |
| cut_boundaries | PASS | 17 cuts, all between words |
| audio_pops | PASS | 20 ms fades at all 18 joints; audio and video within 8 ms |
| loudness | PASS | -16.5 LUFS integrated, true peak -0.7 dBFS |

## Visual

| Check | Result | Detail |
|---|---|---|
| captions_visible | PASS | caption present at 6 sampled cues |
| caption_occlusion | PASS |  |
| text_overflow | PASS |  |
| text_contrast | PASS |  |
| overlay_timing | PASS | all 23 board elements appear while their sentence is spoken |
| presenter_visible | PASS | visible and moving on all 8 pages (glass, pip, split) |
| black_frames | PASS |  |
| frozen_frames | PASS | longest still hold 0.0s, within the 16s scene limit |

## Content

| Check | Result | Detail |
|---|---|---|
| citations_supported | PASS | 10 distinct citations, all in the approved reference list |
| no_new_claims | PASS |  |
| approved_wording_intact | PASS |  |

## Takes kept from the recording

| # | Sentence | Kept take (source time) | Match | Retakes dropped |
|---|---|---|---|---|
| 1 | Welcome. | **missing** | - | 0 |
| 2 | In this course, you will learn what red light therapy is, what exercise recovery | 13.45-25.37s | 97% | 0 |
| 3 | Photobiomodulation, or PBM, uses red or near-infrared light applied to the body. | 27.63-33.57s | 100% | 0 |
| 4 | Reviews describe proposed effects on cellular metabolism, oxidative stress, and  | 34.75-46.55s | 97% | 0 |
| 5 | Lasers and LED devices also differ technically. | 47.53-51.33s | 100% | 0 |
| 6 | PBM is often described as influencing bioenergetics and immune or oxidative stre | 53.63-60.35s | 100% | 0 |
| 7 | But one human study found a single PBM session did not increase mitochondrial re | 67.23-76.55s | 97% | 2 |
| 8 | That means mechanism claims should stay cautious. | 88.13-91.79s | 86% | 0 |
| 9 | A review reports promising effects for exertion recovery, including muscle stren | 93.61-103.29s | 95% | 0 |
| 10 | In CrossFit athletes, PBMT-sMF did not beat other recovery methods for jump perf | 104.49-124.25s | 94% | 0 |
| 11 | Evidence on pain is mixed across conditions. | 127.21-129.79s | 100% | 0 |
| 12 | A fibromyalgia review reported consistent short-term pain and quality-of-life im | 130.37-140.99s | 100% | 0 |
| 13 | In chronic trapezius myofascial pain, 808 nanometre laser was not superior to pl | 141.45-150.07s | 88% | 0 |
| 14 | Protocol design matters because studies vary in wavelength, energy dose, timing, | 153.51-160.89s | 100% | 0 |
| 15 | Examples in the brief include 650 nanometre LED use before exercise-induced musc | 162.03-174.73s | 100% | 0 |
| 16 | Transcranial protocols are preliminary and not routine fitness-business practice | 176.69-182.57s | 100% | 0 |
| 17 | Some included trials reported no adverse events or only mild and infrequent adve | 186.11-198.01s | 100% | 0 |
| 18 | Stay within scope. | 199.81-201.39s | 100% | 0 |
| 19 | Present PBM as a wellness or recovery service, not a medical treatment. | 209.09-213.87s | 100% | 1 |
| 20 | Be clear that evidence is promising in places, mixed in others, and not a guaran | 214.71-221.05s | 100% | 0 |
| 21 | The main message is simple. | 225.15-226.45s | 100% | 0 |
| 22 | PBM may support recovery in some contexts, but the evidence is not uniform. | 227.17-232.41s | 100% | 0 |
| 23 | Your role is to understand the protocol, stay in scope, and communicate uncertai | 233.45-240.01s | 100% | 0 |
| 24 | Every claim in this course is linked to the sources listed here. | 242.81-245.59s | 83% | 0 |
| 25 | Review them in the course materials before your certification exam. | 246.19-249.69s | 95% | 0 |

## Errors

- **sections_match_script**: sections below 92%: Sources and next step 88.4% (course -> source; sources -> source; your -> )

## Warnings

- **takes_complete**: not said in the recording (short, no claim): "Welcome."
- **takes_complete**: no clean take: "Every claim in this course is linked to the sources listed here." was read as "Every claim in this source is linked to the source listed here."

## Accepted advisories

- `timeline_track_too_dense`: Track 1 has 8 timed elements in this HTML file. Smaller sub-compositions keep timelines easier to read, iterate on, and diff.. *authoring-style tip; the composition is generated, not hand-maintained*

## Scope of these checks

Delivery fidelity is measured on the one Scribe transcript of the presenter recording, restricted to the words inside the kept takes and remapped to the edit; the edit placed in the render is checked by SHA-256. The rendered mix is not re-transcribed, which would be a second paid call.

# Faceless sample v2: Red Light Therapy for Exercise Recovery (v3 course)

**Layout: boards.** Pages build up while the narration speaks, instead of v1's one
statement per screen. v1 is kept in [`v1/`](v1/) for comparison.

This render uses the **approved** v3 course package and its **existing** ElevenLabs
narration. No new speech was generated, no LLM was called, and no paid call was made
(the transcripts are cached in `../source/transcripts/`).

## What the viewer sees

| Time | Page | How it builds |
|---|---|---|
| 0–12 s | Hero | The course title appears, then rises into the header. A numbered 4-step roadmap draws in as each item is spoken. |
| 12–34 s | What PBM is | The definition stays up with a red → near-infrared light band. Three effect nodes build below it, then the Laser/LED device pair enters on the right. |
| 34–51 s | How it may work | A statement, then study [3] enters large in the centre and shrinks into the right-hand column. "That means" arrows down to the caution. |
| 51–93 s | THE RESEARCH | A gallery with two headings. Each study enters in the centre, then docks top-right, bottom-right, top-left and bottom-left, and the full gallery holds at the end. The CrossFit study has a time-point strip (one hour vs 24 and 48 hours). |
| 93–118 s | Protocols and device choices | A 4-icon variables row ("because"), then a spectrum ruler marking only 630, 650 and 850 nm with what each was used for, then the transcranial caution. |
| 118–140 s | Safety, scope, and client talk | The safety study docks, then the scope chip, the do/don't split, and a three-step evidence scale. |
| 140–152 s | Key Takeaways | The main message with its "but", then a checklist of your role. |
| 152–160 s | Sources and next step | The title rises, then the two closing lines build. |

Every word on screen is a verbatim fragment of the approved narration or slides, or a
field of the approved reference list. Every number on screen is stated in the course.
The storyboard validator and the QA gate both check this; the tests include negative cases.

## Files

| File | What it is |
|---|---|
| `final.mp4` | 1920×1080, 30 fps, H.264 + AAC, 160.03 s. Captions burned in last. |
| `preview.mp4` | 960×540 review copy |
| `storyboard.json` | Beats with word timings, plus `boards[]`: every page, element, entrance time and dock slot |
| `edit/edl.json`, `edit/master.srt`, `edit/takes_packed.md` | Output timeline, 197 two-word caption cues, video-use transcript view |
| `qa/video_qa.json`, `qa/VIDEO_QA_REPORT.md` | QA gate: **pass**, no warnings, no errors |
| `qa/contact_sheet.png` | 22 frames from `final.mp4` |
| `qa/hyperframes_check.json` | HyperFrames layout, caption-band and contrast report |
| `qa/run.json` | Pipeline steps and timings (build 0.7 s, lint 2.6 s, render 367 s, captions 134 s, QA 57 s) |
| `render_metadata.json` | Tool versions, SHA-256 of every output and narration file |
| `attempts/1/` | Attempt 1's QA: **warn**, because small text on the bright accent was below 3:1 contrast |

## Attempts

| Attempt | QA | What changed |
|---|---|---|
| 1 | warn | Roadmap badges, the 650 nm label and the scope chip used white or orange on the bright accent (2.58–2.84:1). They now use the deep accent (4.64:1). |
| 2 | **pass** | None needed |

Before any full render, the layout engine rejected pages that did not fit and element
overlaps. Frame snapshots then caught early-visible labels, wrapped titles and colliding
ruler labels. All of those were fixed before these two attempts.

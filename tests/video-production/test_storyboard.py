"""Storyboard engine tests.

Positive cases prove the rules pick sensible treatments. The NEGATIVE cases matter
more: a storyboard that happily renders an invented citation, or lets an LLM
reword approved narration, is the failure this whole design exists to prevent.

    python tests/video-production/test_storyboard.py
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "video-production", "storyboard"))

from beats import (Beat, build_beats, sections_from_beats, split_sentences,  # noqa: E402
                   strip_markers, STATISTIC)
from rules import (StoryboardError, build_storyboard, decide_visual,  # noqa: E402
                   validate_storyboard, _reference_index)

REFERENCES = [
    {"n": 1, "citation": "Ferraresi C, et al. (2016). Photobiomodulation in human muscle tissue. J Biophotonics.",
     "year": 2016, "journal": "J Biophotonics", "design": "systematic_review",
     "population": "trained adults", "outcome": "reduced muscle fatigue"},
    {"n": 2, "citation": "Vanin AA, et al. (2018). Photobiomodulation therapy before exercise. Lasers Med Sci.",
     "year": 2018, "journal": "Lasers Med Sci", "design": "rct"},
]

SLIDES = [
    {"title": "Red Light Therapy for Recovery", "bullets": [], "kind": "title",
     "notes": "Welcome to this course on red light therapy for exercise recovery."},
    {"title": "How photobiomodulation works", "bullets": ["Light absorption", "Cellular energy", "Reduced fatigue"],
     "notes": "Photobiomodulation refers to the use of red and near-infrared light to influence cellular activity. "
              "A systematic review found reduced muscle fatigue in trained adults [1]. "
              "First the light is absorbed, then cellular energy production rises, and finally perceived fatigue falls. "
              "Sessions typically last 10 minutes."},
    {"title": "Evidence quality", "bullets": ["RCT", "Timing matters"],
     "notes": "A randomised trial compared treatment before exercise versus after exercise [2]. "
              "Treatment before exercise produced the larger effect."},
    {"title": "Key takeaways", "bullets": ["Light is not a cure", "Timing matters", "Evidence is growing"],
     "kind": "takeaways",
     "notes": "In summary, red light therapy is a supporting tool, not a replacement for training."},
]


def make_beat(**kw):
    base = dict(beat_id="B001", slide_index=1, text="Some narration.", spoken_text="Some narration.",
                start=0.0, end=3.0, citation_ids=[], beat_type="teaching", cues=[], statistics=[],
                word_count=3, slide_title="Slide", slide_bullets=[], is_slide_opening=False)
    base.update(kw)
    return Beat(**base)


class TestBeats(unittest.TestCase):
    def test_sentence_split_keeps_abbreviations_and_decimals(self):
        text = "Doses of 3.5 J were used, e.g. in trained adults. The next sentence starts here."
        self.assertEqual(len(split_sentences(text)), 2)

    def test_marker_before_full_stop_stays_with_its_sentence(self):
        s = split_sentences("Fatigue fell in trained adults [1]. Timing mattered more than dose.")
        self.assertIn("[1]", s[0])
        self.assertNotIn("[1]", s[1])

    def test_spoken_text_drops_markers(self):
        self.assertEqual(strip_markers("Fatigue fell [1]."), "Fatigue fell.")

    def test_statistic_matches_units_not_years_or_reference_numbers(self):
        self.assertTrue(STATISTIC.search("sessions last 10 minutes"))
        self.assertTrue(STATISTIC.search("a 12% reduction"))
        self.assertIsNone(STATISTIC.search("published in 2016"))
        self.assertIsNone(STATISTIC.search("see reference 2"))

    def test_beats_are_monotonic_and_carry_verbatim_text(self):
        beats = build_beats(SLIDES, durations={0: 6.0, 1: 30.0, 2: 14.0, 3: 8.0})
        self.assertGreater(len(beats), 6)
        for a, b in zip(beats, beats[1:]):
            self.assertLessEqual(a.end, b.start + 1e-6)
            self.assertLess(a.start, a.end)
        joined = " ".join(b.text for b in beats)
        self.assertIn("A systematic review found reduced muscle fatigue in trained adults [1].", joined)

    def test_word_timeline_is_used_when_a_transcript_exists(self):
        words = [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.4}
                 for i, w in enumerate("Welcome to this course on red light therapy for exercise recovery".split())]
        beats = build_beats(SLIDES[:1], transcripts={0: words})
        self.assertAlmostEqual(beats[0].start, 0.0, places=2)
        self.assertGreater(beats[0].end, 4.0)  # 11 words at 0.5s each, from the transcript

    def test_beat_types_are_recognised(self):
        beats = build_beats(SLIDES, durations={0: 6.0, 1: 30.0, 2: 14.0, 3: 8.0})
        kinds = {b.beat_type for b in beats}
        self.assertIn("opening", kinds)
        self.assertIn("evidence", kinds)
        self.assertIn("recap", kinds)


class TestVisualDecisions(unittest.TestCase):
    def setUp(self):
        self.refs = _reference_index(REFERENCES)

    def test_citation_becomes_an_evidence_card_with_the_real_source(self):
        beat = make_beat(spoken_text="A systematic review found reduced muscle fatigue in trained adults.",
                         text="A systematic review found reduced muscle fatigue in trained adults [1].",
                         citation_ids=[1], beat_type="evidence")
        out = decide_visual(beat, self.refs)
        self.assertEqual(out["visual_type"], "EVIDENCE_CARD")
        self.assertEqual(out["props"]["design"], "systematic_review")
        self.assertIn("Ferraresi", out["props"]["citation"])

    def test_unknown_citation_is_refused(self):
        beat = make_beat(text="Claim [9].", spoken_text="Claim.", citation_ids=[9], beat_type="evidence")
        with self.assertRaises(StoryboardError):
            decide_visual(beat, self.refs)

    def test_statistic_gets_a_readable_card(self):
        beat = make_beat(spoken_text="Sessions typically last 10 minutes.",
                         text="Sessions typically last 10 minutes.", statistics=["10 minutes"])
        out = decide_visual(beat, self.refs)
        self.assertEqual(out["visual_type"], "STATISTIC")
        self.assertEqual(out["props"]["value"], "10 minutes")

    def test_sequence_language_becomes_a_process(self):
        beat = make_beat(
            spoken_text="First the light is absorbed, then cellular energy production rises, and finally perceived fatigue falls.",
            text="First the light is absorbed, then cellular energy production rises, and finally perceived fatigue falls.",
            slide_bullets=["Light absorption", "Cellular energy", "Reduced fatigue"])
        out = decide_visual(beat, self.refs)
        self.assertEqual(out["visual_type"], "PROCESS")
        self.assertGreaterEqual(len(out["props"]["steps"]), 2)

    def test_contrast_becomes_a_comparison(self):
        beat = make_beat(spoken_text="Treatment before exercise was compared with treatment after exercise.",
                         text="Treatment before exercise was compared with treatment after exercise.")
        out = decide_visual(beat, self.refs)
        self.assertEqual(out["visual_type"], "COMPARISON")
        self.assertTrue(out["props"]["left"] and out["props"]["right"])

    def test_plain_teaching_sentence_stays_quiet(self):
        beat = make_beat(spoken_text="Most people tolerate the sessions comfortably.",
                         text="Most people tolerate the sessions comfortably.")
        out = decide_visual(beat, self.refs)
        self.assertEqual(out["visual_type"], "NONE")

    def test_every_decision_states_a_reason(self):
        for beat in (make_beat(), make_beat(citation_ids=[1], beat_type="evidence"),
                     make_beat(statistics=["12%"], spoken_text="A 12% change.", text="A 12% change.")):
            self.assertTrue(decide_visual(beat, self.refs)["reason"].strip())


class TestComposition(unittest.TestCase):
    def build(self, slides=SLIDES, config=None):
        beats = build_beats(slides, durations={i: 12.0 for i in range(len(slides))})
        sections = sections_from_beats(beats, slides)
        return build_storyboard(beats, REFERENCES, sections, config=config), beats

    def test_storyboard_validates_against_its_own_schema_rules(self):
        sb, _ = self.build()
        self.assertEqual(validate_storyboard(sb, REFERENCES), [])
        self.assertTrue(sb["segments"])
        self.assertEqual(sb["decided_by"], "rules")

    def test_no_more_than_two_identical_treatments_in_a_row(self):
        slides = [{"title": "Evidence", "bullets": [],
                   "notes": " ".join("A study found an effect in adults [1]." for _ in range(5))}]
        sb, _ = self.build(slides)
        run = best = 0
        last = None
        for seg in sb["segments"]:
            if seg["visual_type"] == "NONE":
                run, last = 0, None
                continue
            run = run + 1 if seg["visual_type"] == last else 1
            last = seg["visual_type"]
            best = max(best, run)
        self.assertLessEqual(best, 2)

    def test_short_beats_do_not_get_their_own_visual(self):
        sb, _ = self.build()
        for seg in sb["segments"]:
            if seg["visual_type"] != "NONE":
                self.assertGreaterEqual(round(seg["end"] - seg["start"], 2), 2.2)

    def test_some_beats_stay_quiet(self):
        sb, _ = self.build()
        quiet = [s for s in sb["segments"] if s["visual_type"] == "NONE"]
        self.assertTrue(quiet, "a storyboard with a visual on every beat is the failure mode we designed against")

    def test_transitions_only_at_section_boundaries(self):
        sb, _ = self.build()
        starts = {round(s["start"], 2) for s in sb["sections"]}
        for seg in sb["segments"]:
            if seg["visual_type"] == "SECTION_TRANSITION":
                self.assertIn(round(seg["start"], 2), starts)

    def test_emphasis_words_appear_in_the_narration(self):
        sb, _ = self.build()
        for seg in sb["segments"]:
            for w in seg["emphasis_words"]:
                self.assertIn(w.lower(), seg["narration"].lower())


class TestValidatorCatchesTampering(unittest.TestCase):
    """The validator is what an LLM or agent pass is checked against."""

    def setUp(self):
        beats = build_beats(SLIDES, durations={i: 12.0 for i in range(len(SLIDES))})
        sections = sections_from_beats(beats, SLIDES)
        self.sb = build_storyboard(beats, REFERENCES, sections)
        self.approved = {s["segment_id"]: s["narration"] for s in self.sb["segments"]}

    def test_rewritten_narration_is_caught(self):
        self.sb["segments"][1]["narration"] = "Red light therapy cures muscle damage."
        problems = validate_storyboard(self.sb, REFERENCES, self.approved)
        self.assertTrue(any("verbatim" in p for p in problems))

    def test_invented_citation_is_caught(self):
        self.sb["segments"][0]["citation_ids"] = ["7"]
        problems = validate_storyboard(self.sb, REFERENCES, self.approved)
        self.assertTrue(any("not in the approved reference list" in p for p in problems))

    def test_evidence_card_without_a_citation_is_caught(self):
        seg = self.sb["segments"][0]
        seg.update({"visual_type": "EVIDENCE_CARD", "citation_ids": []})
        self.assertTrue(any("evidence card with no citation" in p
                            for p in validate_storyboard(self.sb, REFERENCES, self.approved)))

    def test_emphasis_word_not_spoken_is_caught(self):
        self.sb["segments"][0]["emphasis_words"] = ["mitochondria"]
        problems = validate_storyboard(self.sb, REFERENCES, self.approved)
        self.assertTrue(any("not in the narration" in p for p in problems))

    def test_missing_reason_is_caught(self):
        self.sb["segments"][0]["visual_reason"] = ""
        self.assertTrue(any("no visual_reason" in p
                            for p in validate_storyboard(self.sb, REFERENCES, self.approved)))


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""On-screen text and QA content checks.

Found by looking at rendered frames, not by reading code: cards that ended in "...",
a definition card that highlighted "near-infrared" when the term being defined was
photobiomodulation. Each case below is one of those, plus the negative cases the QA
gate must refuse.

    python -m unittest discover -s tests/video-production
"""

import copy
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "video-production", "storyboard"))
sys.path.insert(0, os.path.join(ROOT, "video-production", "qa"))

from rules import _defined_term, screen_line, validate_storyboard  # noqa: E402

SOURCE = os.path.join(ROOT, "samples", "source")
STORYBOARD = os.path.join(ROOT, "samples", "faceless", "storyboard.json")

LONG = ("Reviews describe proposed effects on cellular metabolism, oxidative stress, and inflammatory "
        "signalling, but protocol differences make direct comparison difficult [2].")


class TestScreenLine(unittest.TestCase):
    def test_never_truncates(self):
        line = screen_line(LONG)
        self.assertIsNotNone(line)
        self.assertFalse(line["text"].endswith("..."))
        self.assertIn(line["text"], LONG)

    def test_cuts_only_at_a_clause_boundary(self):
        self.assertEqual(screen_line(LONG)["text"],
                         "Reviews describe proposed effects on cellular metabolism, oxidative stress, "
                         "and inflammatory signalling")

    def test_prefers_the_approved_bullet(self):
        line = screen_line("Protocol design matters because studies vary in wavelength, energy dose, "
                           "timing, and application target [1, 2].",
                           ["Key variables: wavelength, dose, timing, target [1, 2]"])
        self.assertEqual(line, {"text": "Key variables: wavelength, dose, timing, target",
                                "source": "slide_bullet"})

    def test_a_bullet_is_shown_once(self):
        used = set()
        bullets = ["Key variables: wavelength, dose, timing, target [1, 2]"]
        text = "Studies vary in wavelength, dose, timing and target."
        self.assertEqual(screen_line(text, bullets, used)["source"], "slide_bullet")
        self.assertEqual(screen_line(text, bullets, used)["source"], "narration")

    def test_nothing_showable_returns_none(self):
        run_on = " ".join(["word"] * 40)  # long, no clause boundary, no bullet
        self.assertIsNone(screen_line(run_on))


class TestDefinedTerm(unittest.TestCase):
    def test_subject_with_abbreviation(self):
        self.assertEqual(_defined_term("Photobiomodulation, or PBM, uses red or near-infrared light "
                                       "applied to the body [1, 2]."), "Photobiomodulation (PBM)")

    def test_plain_definition(self):
        self.assertEqual(_defined_term("Hormesis refers to a beneficial response to a low dose."), "Hormesis")

    def test_not_a_definition(self):
        self.assertIsNone(_defined_term("In this course, you will learn what red light therapy is."))


@unittest.skipUnless(os.path.exists(STORYBOARD), "no sample storyboard")
class TestValidatorOnTheRealStoryboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(STORYBOARD, encoding="utf-8") as fh:
            cls.sb = json.load(fh)
        with open(os.path.join(SOURCE, "package.json"), encoding="utf-8") as fh:
            cls.pkg = json.load(fh)
        cls.bullets = [b for s in cls.pkg["slides"] for b in s.get("bullets") or []]

    def problems(self, sb):
        return validate_storyboard(sb, self.pkg["references"], approved_bullets=self.bullets)

    def first(self, component):
        return next(s for s in self.sb["segments"] if s.get("component") == component)

    def test_sample_is_clean(self):
        self.assertEqual(self.problems(self.sb), [])

    def test_no_card_in_the_sample_is_cut_off(self):
        for s in self.sb["segments"]:
            for v in (s.get("props") or {}).values():
                if isinstance(v, str):
                    self.assertFalse(v.endswith("..."), s["segment_id"])

    def test_cut_off_card_is_caught(self):
        sb = copy.deepcopy(self.sb)
        seg = next(s for s in sb["segments"] if s.get("component") == "KeyTakeaway"
                   and s["props"].get("source") == "narration")
        seg["props"]["text"] = seg["props"]["text"][:30] + "..."
        self.assertTrue(any("cut off" in p for p in self.problems(sb)))

    def test_paraphrased_card_is_caught(self):
        sb = copy.deepcopy(self.sb)
        seg = next(s for s in sb["segments"] if s.get("component") == "KeyTakeaway"
                   and s["props"].get("source") == "narration")
        seg["props"]["text"] = "Red light therapy is proven to speed recovery."
        self.assertTrue(any("not verbatim" in p for p in self.problems(sb)))

    def test_fake_bullet_is_caught(self):
        sb = copy.deepcopy(self.sb)
        seg = next(s for s in sb["segments"] if s["props"].get("source") == "slide_bullet")
        seg["props"]["text"] = "Guaranteed faster recovery"
        self.assertTrue(any("not one" in p for p in self.problems(sb)))

    def test_unspoken_term_is_caught(self):
        sb = copy.deepcopy(self.sb)
        self.first_in(sb, "KeywordHighlight")["props"]["term"] = "Cryotherapy"
        self.assertTrue(any("not spoken" in p for p in self.problems(sb)))

    def test_headline_figure_missing_from_finding_is_caught(self):
        # The real defect: "48 hours" above a finding that, as shown, is about one hour.
        sb = copy.deepcopy(self.sb)
        seg = next(s for s in sb["segments"] if "CrossFit" in (s["props"].get("finding") or ""))
        seg["props"]["statistic"] = "48 hours"
        self.assertTrue(any("headline figure" in p for p in self.problems(sb)))

    def test_no_title_is_shown_twice_in_a_row(self):
        visuals = [s for s in self.sb["segments"] if s["visual_type"] != "NONE"]
        titles = [str(s["props"].get("title") or "").lower() for s in visuals]
        for a, b in zip(titles, titles[1:]):
            if a:
                self.assertNotEqual(a, b)

    @staticmethod
    def first_in(sb, component):
        return next(s for s in sb["segments"] if s.get("component") == component)


@unittest.skipUnless(os.path.exists(STORYBOARD), "no sample storyboard")
class TestQaContentChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import checks  # noqa: E402
        cls.checks = checks
        with open(STORYBOARD, encoding="utf-8") as fh:
            cls.sb = json.load(fh)
        with open(os.path.join(SOURCE, "package.json"), encoding="utf-8") as fh:
            cls.pkg = json.load(fh)

    def run_content(self, sb):
        r = self.checks.Report()
        self.checks.content(r, self.pkg, sb)
        return r

    def test_sample_passes(self):
        r = self.run_content(self.sb)
        self.assertEqual(r.status, "pass", r.errors)

    def test_invented_number_fails(self):
        sb = copy.deepcopy(self.sb)
        seg = next(s for s in sb["segments"] if s.get("component") == "KeyTakeaway")
        seg["props"]["text"] = "Recovery improved by 37 percent"
        r = self.run_content(sb)
        self.assertEqual(r.checks["no_new_claims"], "fail")

    def test_rewritten_narration_fails(self):
        sb = copy.deepcopy(self.sb)
        sb["segments"][3]["narration"] = "Red light therapy definitely works."
        r = self.run_content(sb)
        self.assertEqual(r.checks["approved_wording_intact"], "fail")

    def test_unknown_citation_fails(self):
        sb = copy.deepcopy(self.sb)
        sb["segments"][2]["citation_ids"] = ["99"]
        r = self.run_content(sb)
        self.assertEqual(r.checks["citations_supported"], "fail")


class TestSrtParsing(unittest.TestCase):
    def test_parse(self):
        import tempfile
        import checks
        with tempfile.NamedTemporaryFile("w", suffix=".srt", delete=False, encoding="utf-8") as fh:
            fh.write("1\n00:00:00,100 --> 00:00:00,500\nWELCOME.\n\n2\n00:01:02,000 --> 00:01:03,250\nIN THIS\n")
        try:
            self.assertEqual(checks.parse_srt(fh.name), [(0.1, 0.5, "WELCOME."), (62.0, 63.25, "IN THIS")])
        finally:
            os.unlink(fh.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)

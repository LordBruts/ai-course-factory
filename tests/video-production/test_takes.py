"""Take selection and cut planning (video-production/presenter/takes.py).

The "recording" here is assembled from REAL Scribe payloads (the cached transcripts
of the approved narration), laid end to end, and then edited the way a presenter's
take goes wrong: a false start, a full repeat, a skipped sentence. Words keep the
exact shape Scribe returns, spacing entries included.

    python -m unittest discover -s tests/video-production
"""

import copy
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "video-production", "storyboard"))
sys.path.insert(0, os.path.join(ROOT, "video-production", "presenter"))

from deck import to_slides, video_deck  # noqa: E402
import takes as tk  # noqa: E402
from sources import HeyGenSource, NotConfigured, source_for  # noqa: E402

SOURCE = os.path.join(ROOT, "samples", "source")
TRANSCRIPTS = os.path.join(SOURCE, "transcripts")


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _recording(slides):
    """Real per-slide Scribe words, shifted onto one timeline with a 1.5 s pause between."""
    durations = {int(k): float(v) for k, v in _load(os.path.join(SOURCE, "durations.json")).items()}
    words, clock = [], 12.0            # a silent lead-in, as in a real recording
    for s in slides:
        idx = s["audio_index"]
        for w in _load(os.path.join(TRANSCRIPTS, "audio_%02d.json" % idx))["words"]:
            w = dict(w)
            w["start"] = round(w["start"] + clock, 3)
            w["end"] = round(w["end"] + clock, 3)
            words.append(w)
        clock += durations[idx] + 1.5
    return words, clock


def _real_words(words):
    return [w for w in words if w.get("type") == "word"]


def _find(words, first_text, start_after=0.0):
    for i, w in enumerate(words):
        if w.get("type") == "word" and w["text"].strip(" .,").lower() == first_text.lower() and w["start"] >= start_after:
            return i
    raise AssertionError("word %r not found" % first_text)


def _span(words, i, n):
    """n real words from index i, with the spacing between them."""
    out, count, j = [], 0, i
    while count < n:
        out.append(words[j])
        count += words[j].get("type") == "word"
        j += 1
    return out, j


def _insert(words, at_index, chunk):
    """Insert a copy of `chunk` before words[at_index], pushing everything after it later."""
    first, last = chunk[0]["start"], chunk[-1]["end"]
    begin = words[at_index]["start"]
    length = last - first + 0.8
    shifted = []
    for w in chunk:
        w = dict(w)
        w["start"] = round(w["start"] - first + begin, 3)
        w["end"] = round(w["end"] - first + begin, 3)
        shifted.append(w)
    tail = []
    for w in words[at_index:]:
        w = dict(w)
        w["start"] = round(w["start"] + length, 3)
        w["end"] = round(w["end"] + length, 3)
        tail.append(w)
    return words[:at_index] + shifted + tail


@unittest.skipUnless(os.path.isdir(TRANSCRIPTS), "no cached transcripts")
class TestTakes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.slides = to_slides(video_deck(_load(os.path.join(SOURCE, "package.json")))[0])
        cls.words, cls.end = _recording(cls.slides)

    def select(self, words):
        heard = tk.heard_words({"words": words})
        takes = tk.select_takes(self.slides, heard)
        ranges = tk.plan_ranges(takes, heard, words[-1]["end"] + 2)
        return heard, takes, ranges

    def test_clean_recording_keeps_every_sentence_once(self):
        heard, takes, ranges = self.select(self.words)
        self.assertTrue(all(t.status == "ok" for t in takes), [(t.text, t.status) for t in takes if t.status != "ok"])
        self.assertEqual(sum(len(t.rejected) for t in takes), 0)
        # The silent lead-in and the pauses between slides are cut; the speech is not.
        self.assertGreater(ranges[0]["src_start"], 11.0)
        kept = sum(r["frames"] for r in ranges) / tk.FPS
        spoken = sum(w["end"] - w["start"] for w in heard.words)
        self.assertGreater(kept, spoken)
        self.assertLess(kept, self.end - 12.0)

    def test_false_start_is_cut_and_the_full_take_kept(self):
        i = _find(self.words, "Photobiomodulation")
        stumble, _ = _span(self.words, i, 4)           # "Photobiomodulation, or PBM, uses" ... then stops
        words = _insert(self.words, i, stumble)
        heard, takes, ranges = self.select(words)
        t = next(t for t in takes if t.text.startswith("Photobiomodulation"))
        self.assertEqual(t.status, "ok")
        full_start = words[_find(words, "Photobiomodulation", start_after=words[i]["end"] + 0.1)]["start"]
        self.assertAlmostEqual(heard.words[t.chosen.first]["start"], full_start, places=3)
        # The false start's words are in no kept range.
        stumble_start = words[i]["start"]
        for r in ranges:
            self.assertFalse(r["src_start"] <= stumble_start + 0.05 < r["src_end"],
                             "false start kept in range %s" % r)

    def test_repeated_sentence_keeps_the_last_take(self):
        i = _find(self.words, "Lasers")
        whole, j = _span(self.words, i, 7)             # "Lasers and LED devices also differ technically."
        words = _insert(self.words, j, whole)          # said twice in a row
        heard, takes, ranges = self.select(words)
        t = next(t for t in takes if t.text.startswith("Lasers"))
        self.assertEqual(len(t.rejected), 1)
        second = words[_find(words, "Lasers", start_after=words[i]["end"] + 0.1)]["start"]
        self.assertAlmostEqual(heard.words[t.chosen.first]["start"], second, places=3)
        self.assertTrue(all(x.status == "ok" for x in takes))

    def test_skipped_sentence_is_reported_missing(self):
        i = _find(self.words, "Lasers")
        _, j = _span(self.words, i, 7)
        words = copy.deepcopy(self.words[:i] + self.words[j:])
        heard, takes, _ = self.select(words)
        t = next(t for t in takes if t.text.startswith("Lasers"))
        self.assertEqual(t.status, "missing")
        self.assertIsNone(t.chosen)
        # One missing sentence does not derail the ones after it.
        self.assertTrue(all(x.status == "ok" for x in takes if x is not t))

    def test_cuts_land_between_words(self):
        heard, takes, ranges = self.select(self.words)
        tol = 1.0 / tk.FPS
        for r in ranges:
            first, last = heard.words[r["first_word"]], heard.words[r["last_word"]]
            self.assertLessEqual(r["src_start"], first["start"] + tol)
            self.assertGreaterEqual(r["src_end"], last["end"] - tol)
            if r["first_word"] > 0:
                self.assertGreaterEqual(r["src_start"], heard.words[r["first_word"] - 1]["end"] - tol)
            if r["last_word"] + 1 < len(heard.words):
                self.assertLessEqual(r["src_end"], heard.words[r["last_word"] + 1]["start"] + tol)

    def test_output_timeline_is_contiguous_whole_frames(self):
        heard, takes, ranges = self.select(self.words)
        clock = 0.0
        for r in ranges:
            self.assertAlmostEqual(r["out_start"], clock, places=6)
            self.assertAlmostEqual((r["out_end"] - r["out_start"]) * tk.FPS, r["frames"], places=6)
            self.assertAlmostEqual(r["src_start"] * tk.FPS, round(r["src_start"] * tk.FPS), places=6)
            clock = r["out_end"]

    def test_remapped_words_are_monotonic_and_inside_the_edit(self):
        heard, takes, ranges = self.select(self.words)
        words = tk.remap(ranges, heard)
        total = ranges[-1]["out_end"]
        self.assertEqual(len(words), sum(r["last_word"] - r["first_word"] + 1 for r in ranges))
        for a, b in zip(words, words[1:]):
            self.assertLessEqual(a["start"], b["start"])
        self.assertTrue(all(0 <= w["start"] <= w["end"] <= total for w in words))
        slides = tk.slide_timeline(ranges, words, self.slides)
        self.assertEqual([s["deck_position"] for s in slides], list(range(len(self.slides))))
        self.assertAlmostEqual(sum(s["seconds"] for s in slides), total, places=2)
        for s in slides:
            self.assertTrue(all(0 <= w["start"] <= s["seconds"] + 1e-6 for w in s["words"]))

    def test_slide_boundaries_are_never_jump_cuts(self):
        _, _, ranges = self.select(self.words)
        for a, b in zip(ranges, ranges[1:]):
            if a["slide"] != b["slide"]:
                self.assertFalse(b["jump_cut_before"])


PRESENTER = os.path.join(SOURCE, "presenter")


@unittest.skipUnless(os.path.exists(os.path.join(PRESENTER, "scribe.json")), "no presenter transcript")
class TestRealPresenterRecording(unittest.TestCase):
    """The first real recording (Phase 4): retakes, false starts, misreads, an aside."""

    @classmethod
    def setUpClass(cls):
        from beats import numbers_in
        from deck import video_script
        pkg = _load(os.path.join(SOURCE, "package.json"))
        cls.slides = to_slides(video_deck(pkg)[0])
        allowed = numbers_in(video_script(video_deck(pkg)[0]))
        meta = _load(os.path.join(PRESENTER, "ingest.json"))
        cls.heard = tk.heard_words(_load(os.path.join(PRESENTER, "scribe.json")),
                                   meta["scribe_trim_offset"], allowed)
        cls.takes = tk.select_takes(cls.slides, cls.heard, allowed)
        cls.ranges = tk.plan_ranges(cls.takes, cls.heard, meta["proxy_duration"])
        kept = {i for r in cls.ranges for i in range(r["first_word"], r["last_word"] + 1)}
        cls.cut = " ".join(w["text"] for i, w in enumerate(cls.heard.words) if i not in kept)

    def take(self, prefix):
        return next(t for t in self.takes if t.text.startswith(prefix))

    def test_unsaid_greeting_is_omitted_not_missing(self):
        self.assertEqual(self.take("Welcome").status, "omitted")
        self.assertFalse(any(t.status == "missing" for t in self.takes))

    def test_numbers_read_as_digit_groups_match(self):
        # "Eight oh eight" and "six thirty plus eight fifty" are the script's 808, 630 and 850.
        self.assertEqual(self.take("In chronic").status, "ok")
        self.assertEqual(self.take("Examples in the brief").chosen.score, 1.0)

    def test_triple_take_keeps_the_clean_read_and_reports_the_rest(self):
        t = self.take("But one human study")
        self.assertEqual(t.chosen.as_dict(self.heard)["text"].split()[-1], "tissues.")
        self.assertIn("muscle or", t.chosen.as_dict(self.heard)["text"])      # not the "muscles" misread
        self.assertEqual(len(t.rejected), 2)
        self.assertIn("PM--", self.cut)
        self.assertIn("skeletal muscles or skin tissues.", self.cut)

    def test_false_start_and_asides_are_cut(self):
        self.assertEqual(len(self.take("Present PBM").rejected), 1)
        self.assertIn("servi-service.", self.cut)
        self.assertIn("Key takeaways.", self.cut)                  # a slide title read aloud
        self.assertIn("When done, save the file anywhere", self.cut)   # an instruction read aloud

    def test_misheard_first_word_stays_in_the_take(self):
        text = self.take("Reviews describe").chosen.as_dict(self.heard)["text"]
        self.assertTrue(text.startswith("Review describe"), text)

    def test_misread_sentence_is_flagged_weak(self):
        t = self.take("Every claim in this course")
        self.assertEqual(t.status, "weak")
        self.assertIn("source", t.chosen.as_dict(self.heard)["text"])


class TestSources(unittest.TestCase):
    def test_heygen_is_inert_until_configured(self):
        with self.assertRaises(NotConfigured):
            HeyGenSource().prepare("/nonexistent")
        self.assertIsInstance(source_for("heygen_avatar"), HeyGenSource)

    def test_unknown_source_is_refused(self):
        with self.assertRaises(ValueError):
            source_for("deepfake")


if __name__ == "__main__":
    unittest.main()

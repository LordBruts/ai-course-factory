"""Transcript alignment against REAL Scribe output.

The first alignment implementation read a `word` key; Scribe writes `text`. A test
built on a hand-written fixture agreed with the bug and passed while every real beat
silently fell back to estimated timing. These tests read the cached transcripts the
pipeline actually produced, so the payload shape cannot drift from reality.

    python -m unittest discover -s tests/video-production
"""

import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "video-production", "storyboard"))

from beats import WordTimeline, build_beats, spoken_tokens, split_sentences, strip_markers  # noqa: E402
from deck import to_slides, video_deck  # noqa: E402

SOURCE = os.path.join(ROOT, "samples", "source")
TRANSCRIPTS = os.path.join(SOURCE, "transcripts")


def _load(name):
    with open(os.path.join(SOURCE, name), encoding="utf-8") as fh:
        return json.load(fh)


def _words(audio_index):
    with open(os.path.join(TRANSCRIPTS, "audio_%02d.json" % audio_index), encoding="utf-8") as fh:
        return json.load(fh)["words"]


@unittest.skipUnless(os.path.isdir(TRANSCRIPTS), "no cached transcripts")
class TestRealTranscriptAlignment(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.slides = to_slides(video_deck(_load("package.json"))[0])
        cls.durations = {int(k): v for k, v in _load("durations.json").items()}

    def test_payload_is_the_scribe_shape(self):
        w = _words(0)[0]
        self.assertIn("text", w)          # not "word": the shape the first version assumed
        self.assertIn("type", w)

    def test_every_sentence_aligns_to_its_own_transcript(self):
        for s in self.slides:
            sentences = [strip_markers(x) for x in split_sentences(s.get("notes") or "")]
            spans = WordTimeline(_words(s["audio_index"])).align(sentences)
            for sentence, span in zip(sentences, spans):
                self.assertIsNotNone(span, "unaligned: %r" % sentence[:60])

    def test_spans_move_forward_within_a_slide(self):
        for s in self.slides:
            sentences = [strip_markers(x) for x in split_sentences(s.get("notes") or "")]
            spans = WordTimeline(_words(s["audio_index"])).align(sentences)
            for a, b in zip(spans, spans[1:]):
                self.assertLessEqual(a["end"], b["start"] + 0.01)

    def test_british_script_matches_american_asr(self):
        # The approved script says "nanometre"; Scribe hears "nanometer".
        span = WordTimeline([{"text": "808", "type": "word", "start": 0.0, "end": 0.4},
                             {"text": " ", "type": "spacing", "start": 0.4, "end": 0.5},
                             {"text": "nanometer", "type": "word", "start": 0.5, "end": 1.0}]
                            ).align(["808 nanometre"])[0]
        self.assertEqual(span["matched"], 2)

    def test_script_digits_compare_as_spoken_words(self):
        # QA compared "650" with Scribe's "six hundred and fifty" and scored it an edit.
        self.assertEqual(spoken_tokens("650 nanometre signalling at 48 hours"),
                         spoken_tokens("six hundred and fifty nanometer signaling at forty eight hours"))

    def test_wrong_transcript_does_not_align(self):
        # Negative case: slide 1's sentences against the closing slide's audio must be
        # refused, not stretched over whatever words happen to be there.
        sentences = [strip_markers(x) for x in split_sentences(self.slides[1]["notes"])]
        spans = WordTimeline(_words(8)).align(sentences)
        self.assertTrue(all(sp is None for sp in spans))

    def test_all_beats_report_transcript_timing(self):
        transcripts = {i: _words(s["audio_index"]) for i, s in enumerate(self.slides)}
        durations = {i: self.durations[s["audio_index"]] for i, s in enumerate(self.slides)}
        beats = build_beats(self.slides, transcripts=transcripts, durations=durations)
        self.assertEqual({b.timing for b in beats}, {"transcript"})


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Infographic detectors: the picture must be built from the sentence's own words.

Positive cases use the approved course's real sentences. Negative cases prove a
detector stays silent on plain text and never produces a label or number the
sentence does not contain.

    python -m unittest discover -s tests/video-production
"""

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "video-production", "storyboard"))

import infographics as ig  # noqa: E402
from beats import strip_markers  # noqa: E402

REAL = {
    "roadmap": "In this course, you will learn what red light therapy is, what exercise recovery research reports, "
               "why protocols are hard to compare, and how to discuss this service honestly and within scope.",
    "effects": "Reviews describe proposed effects on cellular metabolism, oxidative stress, and inflammatory "
               "signalling, but protocol differences make simple explanations difficult [2].",
    "devices": "Lasers and LED devices also differ technically [1].",
    "variables": "Protocol design matters because studies vary in wavelength, energy dose, timing, and "
                 "application target [1, 2].",
    "wavelengths": "Examples in the brief include 650 nanometre LED use before exercise-induced muscle damage "
                   "and 630 plus 850 nanometre LED use in low back pain research [7, 9].",
    "crossfit": "In CrossFit athletes, PBMT-sMF did not beat other recovery methods for jump performance at one "
                "hour, but showed better jump results than passive recovery at 24 and 48 hours on secondary "
                "analysis [4].",
    "do_dont": "Present PBM as a wellness or recovery service, not a medical treatment.",
    "scale": "Be clear that evidence is promising in places, mixed in others, and not a guarantee [1, 4, 8].",
    "role": "Your role is to understand the protocol, stay in scope, and communicate uncertainty clearly.",
    "definition": "Photobiomodulation, or PBM, uses red or near-infrared light applied to the body [1, 2].",
    "means": "That means mechanism claims should stay cautious [3].",
}


class TestDetectorsOnRealSentences(unittest.TestCase):
    def labels_are_verbatim(self, sentence, spec):
        spoken = strip_markers(sentence)
        for label in ig.labels_of(spec):
            self.assertIn(label, spoken)
        for num in ig.numbers_of(spec):
            self.assertIn(num, spoken)

    def test_roadmap(self):
        spec = ig.detect(REAL["roadmap"])
        self.assertEqual(spec["kind"], "roadmap")
        self.assertEqual([i["label"] for i in spec["items"]], [
            "what red light therapy is", "what exercise recovery research reports",
            "why protocols are hard to compare", "how to discuss this service honestly and within scope"])
        self.labels_are_verbatim(REAL["roadmap"], spec)

    def test_enumeration_stops_before_the_but(self):
        spec = ig.detect(REAL["effects"])
        self.assertEqual([i["label"] for i in spec["items"]],
                         ["cellular metabolism", "oxidative stress", "inflammatory signalling"])
        self.labels_are_verbatim(REAL["effects"], spec)

    def test_because_becomes_a_link(self):
        spec = ig.detect(REAL["variables"])
        self.assertEqual(spec["lead"], "Protocol design matters")
        self.assertEqual(spec["link"], "because")
        self.assertEqual(len(spec["items"]), 4)
        self.assertEqual(spec["items"][1]["icon"], "gauge")

    def test_devices(self):
        spec = ig.detect(REAL["devices"])
        self.assertEqual(spec["kind"], "devices")
        self.assertEqual(spec["caption"], "differ technically")

    def test_wavelengths_mark_only_stated_values(self):
        spec = ig.detect(REAL["wavelengths"])
        self.assertEqual([m["values"] for m in spec["marks"]], [[650], [630, 850]])
        self.labels_are_verbatim(REAL["wavelengths"], spec)

    def test_time_points(self):
        spec = ig.detect(REAL["crossfit"])
        self.assertEqual([p["at"] for p in spec["points"]], ["one hour", "24 and 48 hours"])
        self.labels_are_verbatim(REAL["crossfit"], spec)

    def test_do_dont(self):
        spec = ig.detect(REAL["do_dont"])
        self.assertEqual((spec["do"], spec["dont"]), ("a wellness or recovery service", "a medical treatment"))

    def test_scale(self):
        spec = ig.detect(REAL["scale"])
        self.assertEqual([s["label"] for s in spec["steps"]],
                         ["promising in places", "mixed in others", "not a guarantee"])

    def test_checklist_items(self):
        spec = ig.detect(REAL["role"])
        self.assertEqual([i["label"] for i in spec["items"]],
                         ["understand the protocol", "stay in scope", "communicate uncertainty clearly"])

    def test_light_band(self):
        self.assertEqual(ig.detect(REAL["definition"])["labels"], ["red", "near-infrared"])

    def test_consequence(self):
        self.assertEqual(ig.consequence(REAL["means"]),
                         {"kind": "consequence", "link": "That means", "text": "mechanism claims should stay cautious"})

    def test_every_real_spec_is_verbatim(self):
        for sentence in REAL.values():
            spec = ig.detect(sentence)
            if spec:
                self.labels_are_verbatim(sentence, spec)


class TestDetectorsStaySilent(unittest.TestCase):
    def test_plain_sentences(self):
        for s in ("Welcome.", "Stay within scope.", "Evidence on pain is mixed across conditions.",
                  "Transcranial protocols are preliminary and not routine fitness-business practice."):
            self.assertIsNone(ig.detect(s), s)

    def test_two_items_are_not_a_list(self):
        self.assertIsNone(ig.enumeration("It affects strength and endurance."))

    def test_no_wavelength_without_a_unit(self):
        self.assertIsNone(ig.wavelengths("Sessions lasted 650 seconds in total."))

    def test_devices_need_both(self):
        self.assertIsNone(ig.devices("Lasers differ technically."))

    def test_unmapped_icon_is_a_dot_not_a_guess(self):
        self.assertEqual(ig.icon_for("quarterly zebra ledger"), "circle-dot")


if __name__ == "__main__":
    unittest.main(verbosity=2)

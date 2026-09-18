"""Boards: grouping, gallery docking, layout geometry and the approval gate.

Built from the real approved course and its real storyboard, so the plan under test
is the plan that renders.

    python -m unittest discover -s tests/video-production
"""

import copy
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for sub in ("storyboard", os.path.join("templates", "motion")):
    sys.path.insert(0, os.path.join(ROOT, "video-production", sub))

import boards as B  # noqa: E402
import board as L  # noqa: E402
from components import Tokens  # noqa: E402
from deck import to_slides, video_deck, video_script  # noqa: E402

SOURCE = os.path.join(ROOT, "samples", "source")
STORYBOARD = os.path.join(ROOT, "samples", "faceless", "storyboard.json")


@unittest.skipUnless(os.path.exists(STORYBOARD), "no sample storyboard")
class TestBoardPlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(SOURCE, "package.json"), encoding="utf-8") as fh:
            cls.pkg = json.load(fh)
        with open(STORYBOARD, encoding="utf-8") as fh:
            cls.sb = json.load(fh)
        cls.kept, _ = video_deck(cls.pkg)
        cls.slides = to_slides(cls.kept)
        cls.boards = B.plan_boards(cls.sb, cls.slides, cls.pkg["references"], cls.pkg["title"])
        cls.approved = " ".join([video_script(cls.kept), cls.pkg["title"]] + [s["title"] for s in cls.slides])
        cls.bullets = [b for s in cls.slides for b in s["bullets"]]

    def problems(self, boards):
        return B.validate_boards(boards, self.approved, self.bullets, self.pkg["references"])

    def test_board_sequence(self):
        self.assertEqual([b["kind"] for b in self.boards],
                         ["hero", "stack", "stack", "gallery", "stack", "stack", "recap", "outro"])

    def test_boards_are_contiguous(self):
        for a, b in zip(self.boards, self.boards[1:]):
            self.assertEqual(a["end"], b["start"])
        self.assertEqual(self.boards[0]["start"], 0.0)

    def test_research_slides_merge_into_one_gallery(self):
        gallery = next(b for b in self.boards if b["kind"] == "gallery")
        self.assertEqual(gallery["eyebrow"], "THE RESEARCH")
        self.assertEqual([t["text"] for t in gallery["titles"]],
                         ["Recovery and performance evidence", "Pain and related outcomes"])
        self.assertEqual(sum(1 for e in gallery["elements"] if e["kind"] == "study"), 4)

    def test_studies_dock_in_order_and_before_the_next_one(self):
        gallery = next(b for b in self.boards if b["kind"] == "gallery")
        studies = [e for e in gallery["elements"] if e["kind"] == "study"]
        self.assertEqual([s["slot"] for s in studies], [0, 1, 2, 3])
        for a, b in zip(studies, studies[1:]):
            self.assertLess(a["dock_at"], b["enter_at"])
        self.assertLessEqual(studies[-1]["dock_at"], gallery["end"] - 1.7)

    def test_lone_study_stays_in_its_stack(self):
        how = next(b for b in self.boards if b["titles"][0]["text"] == "How it may work")
        self.assertEqual([e["kind"] for e in how["elements"]], ["statement", "study", "statement"])
        self.assertEqual(how["elements"][2]["link"], "That means")

    def test_definition_keeps_the_light_band(self):
        term = self.boards[1]["elements"][0]
        self.assertEqual(term["kind"], "term")
        self.assertEqual(term["term"], "Photobiomodulation (PBM)")
        self.assertEqual(term["spec"]["kind"], "light_band")

    def test_short_citations_come_from_the_reference_list(self):
        ref = {"n": 1, "citation": "Lawrence, J., & Sorra, K. (2024). Photobiomodulation as Medicine. "
                                   "Journal of functional morphology and kinesiology. https://doi.org/x"}
        self.assertEqual(B.short_citation(ref),
                         {"short": "Lawrence & Sorra", "year": "2024",
                          "journal": "Journal of functional morphology and kinesiology"})

    def test_plan_is_clean(self):
        self.assertEqual(self.problems(self.boards), [])
        self.assertEqual(B.pace_gaps(self.boards, 14), [])

    # --- negative cases: the gate must refuse these ---------------------------------
    def test_invented_label_is_refused(self):
        boards = copy.deepcopy(self.boards)
        el = next(e for b in boards for e in b["elements"] if e["kind"] == "infographic")
        el["spec"]["items"][0]["label"] = "boosts testosterone"
        self.assertTrue(any("not approved wording" in p for p in self.problems(boards)))

    def test_invented_number_is_refused(self):
        boards = copy.deepcopy(self.boards)
        el = next(e for b in boards for e in b["elements"] if (e.get("spec") or {}).get("kind") == "wavelengths")
        el["spec"]["marks"][0]["values"] = [940]
        self.assertTrue(any("940" in p for p in self.problems(boards)))

    def test_unknown_citation_is_refused(self):
        boards = copy.deepcopy(self.boards)
        el = next(e for b in boards for e in b["elements"] if e["kind"] == "study")
        el["study"]["markers"] = [42]
        self.assertTrue(any("[42]" in p for p in self.problems(boards)))

    def test_shared_dock_slot_is_refused(self):
        boards = copy.deepcopy(self.boards)
        gallery = next(b for b in boards if b["kind"] == "gallery")
        studies = [e for e in gallery["elements"] if e["kind"] == "study"]
        studies[1]["slot"] = studies[0]["slot"]
        self.assertTrue(any("dock slot" in p for p in self.problems(boards)))

    def test_long_static_stretch_is_reported(self):
        boards = copy.deepcopy(self.boards)
        boards[-1]["end"] += 30
        self.assertTrue(B.pace_gaps(boards, 14))


@unittest.skipUnless(os.path.exists(STORYBOARD), "no sample storyboard")
class TestLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(STORYBOARD, encoding="utf-8") as fh:
            cls.boards = json.load(fh)["boards"]
        cls.t = Tokens()
        cls.clips, cls.report = L.render_boards(cls.t, cls.boards)

    def test_layout_is_clean(self):
        self.assertEqual(L.check_layout(self.report, self.t), [])

    def test_nothing_enters_the_caption_band(self):
        top = L.Geometry(self.t).caption_top
        for b in self.report:
            for r in b["rects"]:
                self.assertLessEqual(r["rect"]["y"] + r["rect"]["h"], top, r["element_id"])

    def test_gallery_dock_order(self):
        gallery = next(b for b in self.report if b["kind"] == "gallery")
        docks = [r["rect"] for r in gallery["rects"] if r["kind"] == "study_mini"]
        right, left = L.Geometry(self.t).right, L.Geometry(self.t).left
        self.assertEqual(docks[0]["x"] + docks[0]["w"], right)            # top right
        self.assertGreater(docks[1]["y"], docks[0]["y"])                  # bottom right
        self.assertEqual(docks[2]["x"], left)                             # top left
        self.assertEqual((docks[3]["x"], docks[3]["y"] > docks[2]["y"]), (left, True))  # bottom left

    def test_overlap_is_detected(self):
        report = copy.deepcopy(self.report)
        stack = next(b for b in report if b["kind"] == "stack" and len(b["rects"]) >= 3)
        items = [r for r in stack["rects"] if r["kind"] != "title"]
        items[1]["rect"] = dict(items[0]["rect"])
        items[1]["from"] = items[0]["from"]
        self.assertTrue(any("overlaps" in p for p in L.check_layout(report, self.t)))

    def test_caption_band_intrusion_is_detected(self):
        report = copy.deepcopy(self.report)
        report[1]["rects"][-1]["rect"]["y"] = 900
        self.assertTrue(any("caption band" in p for p in L.check_layout(report, self.t)))

    def test_elements_are_hidden_until_they_enter(self):
        # every placed element has a gate that starts hidden
        html = "".join(c.html for c in self.clips)
        tl = "\n".join(line for c in self.clips for line in c.timeline)
        for b in self.report:
            for r in b["rects"]:
                if r["kind"] in ("title", "study_mini"):
                    continue
                gate = r["element_id"].replace(":focus", "-focus").lower() + "-g"
                self.assertIn('id="%s"' % gate, html)
                self.assertIn('"#%s", {"autoAlpha":0}' % gate, tl)

    def test_too_much_content_is_refused(self):
        board = copy.deepcopy(next(b for b in self.boards if b["kind"] == "stack"))
        board["elements"] = board["elements"] * 6
        for i, e in enumerate(board["elements"]):
            e["element_id"] = "B99-E%02d" % i
        with self.assertRaises(L.LayoutError):
            L.BoardRenderer(self.t, board, 10, False, False).render()


if __name__ == "__main__":
    unittest.main(verbosity=2)

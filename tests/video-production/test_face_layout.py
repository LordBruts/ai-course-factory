"""Face template layout: pages beside the presenter, and the presenter's moves.

Uses the real Phase 3 boards (samples/faceless/storyboard.json) and a framing
shaped like presenter/ingest.py writes it.

    python -m unittest discover -s tests/video-production
"""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VP = os.path.join(ROOT, "video-production")
sys.path.insert(0, os.path.join(VP, "templates", "motion"))
sys.path.insert(0, os.path.join(VP, "templates", "face"))

from board import Rect, check_layout, render_boards  # noqa: E402
from components import Tokens  # noqa: E402
import layouts as lay  # noqa: E402
import face_composition as fc  # noqa: E402

STORYBOARD = os.path.join(ROOT, "samples", "faceless", "storyboard.json")
# Centre-left presenter, as measured on the first real recording.
FRAMING = {"subject_center_x": 0.3855, "subject_extent_x": [0.219, 0.469], "subject_center_y": 0.55}


@unittest.skipUnless(os.path.exists(STORYBOARD), "no Phase 3 storyboard")
class TestFaceLayout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(STORYBOARD, encoding="utf-8") as fh:
            cls.sb = json.load(fh)
        cls.boards = cls.sb["boards"]
        cls.t = Tokens()
        cls.modes = lay.build_modes(FRAMING)

    def names(self):
        return lay.mode_sequence(self.boards, self.modes, self.t)

    def test_mode_sequence_mixes_all_three(self):
        preferred = lay.mode_sequence(self.boards)
        kinds = [b["kind"] for b in self.boards]
        for k, n in zip(kinds, preferred):
            self.assertEqual(n, {"gallery": "pip", "hero": "glass", "recap": "glass",
                                 "outro": "glass"}.get(k, "split"))
        names = self.names()
        self.assertEqual(names[0], "glass")
        self.assertEqual(names[-1], "glass")
        self.assertEqual({"glass", "split", "pip"}, set(names))
        # Only a page that does not fit beside the presenter changes arrangement, and
        # only to the fallback.
        for p, n in zip(preferred, names):
            self.assertIn(n, (p, lay.FALLBACK.get(p)))
        self.assertEqual(names[kinds.index("gallery")], "pip")

    def test_dense_pages_fall_back_to_pip(self):
        names = dict(zip([b["board_id"] for b in self.boards], self.names()))
        # B02 (term, three effect nodes, device pair) and B05 (variables, ruler) need more
        # room than the page beside a presenter window; B03 and B06 fit.
        self.assertEqual((names["B02"], names["B05"]), ("pip", "pip"))
        self.assertEqual((names["B03"], names["B06"]), ("split", "split"))    # studies dock under the presenter

    def test_every_board_fits_its_panel_and_leaves_the_presenter_clear(self):
        names = self.names()
        _, report = render_boards(self.t, self.boards, modes=[self.modes[n].board_mode() for n in names])
        self.assertEqual(check_layout(report, self.t), [])
        for b, n in zip(report, names):
            self.assertEqual(b["mode"], n)
            win = self.modes[n].placement.window
            for r in b["rects"]:
                rr = Rect(**r["rect"])
                if r.get("beside_presenter"):
                    # a study docked under the presenter: clear of the shortened window
                    short = self.modes[self.modes[n].docked].placement.window
                    self.assertFalse(rr.overlaps(short), "%s dock covers the presenter" % b["board_id"])
                    self.assertLessEqual(rr.bottom, 790)
                elif n != "glass":
                    self.assertFalse(rr.overlaps(win), "%s %s covers the presenter" % (b["board_id"], r["element_id"]))

    def test_glass_panel_is_clear_of_the_presenter(self):
        g = self.modes["glass"]
        right_edge = FRAMING["subject_extent_x"][1] * lay.W
        self.assertGreater(g.backdrop.x, right_edge)
        self.assertGreaterEqual(g.panel.w, 700)

    def test_layout_check_refuses_content_over_the_presenter(self):
        names = self.names()
        bad = [self.modes[n].board_mode() for n in names]
        split = names.index("split")
        bad[split] = dict(bad[split], forbidden=[Rect(100, 100, 1700, 600)])
        _, report = render_boards(self.t, self.boards, modes=bad)
        problems = check_layout(report, self.t)
        self.assertTrue(any("covers the presenter" in p for p in problems))

    def test_study_on_a_split_page_shortens_the_window(self):
        names = self.names()
        moves = lay.transitions(self.boards, names, self.modes)
        inner = [mv for mv in moves if mv.get("within_board")]
        split_with_study = [b for b, n in zip(self.boards, names)
                            if n == "split" and any(e["kind"] == "study" for e in b["elements"])]
        self.assertEqual(len(inner), len(split_with_study))
        for mv, b in zip(inner, split_with_study):
            dock_at = next(e["dock_at"] for e in b["elements"] if e["kind"] == "study")
            self.assertAlmostEqual(mv["at"], dock_at - 0.05, places=3)
            self.assertEqual((mv["from"], mv["to"]), ("split", "split_docked"))
        # the move out of that page starts from the shortened window
        for mv in moves:
            prev = [x for x in moves if x["at"] < mv["at"]]
            if prev and not mv.get("within_board"):
                self.assertEqual(mv["from"], prev[-1]["to"])
        short = self.modes["split_docked"].placement
        self.assertLess(short.window.h, self.modes["split"].placement.window.h)
        self.assertAlmostEqual(short.x + FRAMING["subject_center_x"] * lay.W * short.scale, short.window.w / 2, delta=2)

    def test_video_never_upscaled_and_always_covers_its_window(self):
        for m in self.modes.values():
            p = m.placement
            self.assertLessEqual(p.scale, 1.0)
            self.assertLessEqual(p.x, 0.001)
            self.assertLessEqual(p.y, 0.001)
            self.assertGreaterEqual(lay.W * p.scale + p.x, p.window.w - 0.5)
            self.assertGreaterEqual(lay.H * p.scale + p.y, p.window.h - 0.5)

    def test_presenter_centred_in_split_window(self):
        p = self.modes["split"].placement
        centre = p.x + FRAMING["subject_center_x"] * lay.W * p.scale
        self.assertAlmostEqual(centre, p.window.w / 2, delta=2)

    def test_moves_happen_once_per_change_before_each_boundary(self):
        names = self.names()
        moves = lay.transitions(self.boards, names)
        changes = sum(1 for a, b in zip(names, names[1:]) if a != b)
        self.assertEqual(len(moves), changes)
        for mv in moves:
            b = next(x for x in self.boards if x["board_id"] == mv["board_id"])
            self.assertAlmostEqual(mv["at"] + lay.TRANSITION_LEAD, b["start"], places=3)
            self.assertLess(mv["at"], b["start"])

    def test_composition_builds_with_presenter_layers(self):
        with tempfile.TemporaryDirectory() as tmp:
            video = os.path.join(tmp, "edit.mp4")
            open(video, "wb").close()
            total = self.boards[-1]["end"]
            ranges = [{"out_start": 0.0, "jump_cut_before": False},
                      {"out_start": 40.0, "jump_cut_before": True},     # B03, split: punch
                      {"out_start": 45.0, "jump_cut_before": True},
                      {"out_start": 70.0, "jump_cut_before": True}]     # B04, pip: too small to punch
            out = os.path.join(tmp, "project")
            m = fc.build_face_composition(self.sb, out, presenter_video=video, edl={"ranges": ranges},
                                          framing=FRAMING, total_seconds=total)
            html = open(m["index"], encoding="utf-8").read()
            self.assertIn('id="pv"', html)
            self.assertIn('src="assets/presenter.mp4"', html)
            self.assertIn('<audio id="pa"', html)
            self.assertIn("class=\"glass\"", html)
            self.assertNotIn("http://", html.replace("http://www.w3.org", ""))
            self.assertEqual(m["punch_ins"], [40.0, 45.0])
            self.assertEqual(len(m["transitions"]), len(lay.transitions(self.boards, self.names(), self.modes)))
            self.assertIsNotNone(m["ending_hold"])


if __name__ == "__main__":
    unittest.main()

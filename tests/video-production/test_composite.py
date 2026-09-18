"""The pages-only render and the presenter track that replaces the in-page video.

The presenter is composited in afterwards, so the track has to reproduce what the browser
would have animated. These tests pin the two halves to each other: the manifest's
schedules, and the geometry the track derives from them.

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

import layouts as lay  # noqa: E402
import face_composition as fc  # noqa: E402

STORYBOARD = os.path.join(ROOT, "samples", "faceless", "storyboard.json")
FRAMING = {"subject_center_x": 0.3855, "subject_extent_x": [0.219, 0.469], "subject_center_y": 0.55}
RANGES = [{"out_start": 0.0, "jump_cut_before": False},
          {"out_start": 40.0, "jump_cut_before": True},
          {"out_start": 45.0, "jump_cut_before": True},
          {"out_start": 70.0, "jump_cut_before": True}]


def build(tmp, presenter_layer):
    with open(STORYBOARD, encoding="utf-8") as fh:
        sb = json.load(fh)
    video = os.path.join(tmp, "edit.mp4")
    open(video, "wb").close()
    out = os.path.join(tmp, "project")
    m = fc.build_face_composition(sb, out, presenter_video=video, edl={"ranges": RANGES},
                                  framing=FRAMING, total_seconds=sb["boards"][-1]["end"],
                                  presenter_layer=presenter_layer)
    return m, open(m["index"], encoding="utf-8").read()


@unittest.skipUnless(os.path.exists(STORYBOARD), "no Phase 3 storyboard")
class TestPagesOnlyComposition(unittest.TestCase):
    def test_pages_build_has_no_video_and_no_background(self):
        with tempfile.TemporaryDirectory() as tmp:
            m, html = build(tmp, presenter_layer=False)
            for gone in ('id="pv"', "id=\"pv-wrap\"", "id=\"pv-edge\"", "<audio", "presenter.mp4"):
                self.assertNotIn(gone, html, "%s survived into the pages build" % gone)
            # Nothing may paint the page colour: the presenter track paints it underneath.
            self.assertIn("body { margin:0; background:transparent; }", html)
            self.assertIn("#base { position:absolute; inset:0; background:transparent;", html)
            self.assertFalse(m["presenter_layer"])
            self.assertFalse(os.path.exists(os.path.join(tmp, "project", "assets", "presenter.mp4")))
            # The boards themselves are untouched by the split.
            self.assertIn('class="glass"', html)

    def test_both_builds_agree_on_every_schedule(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = os.path.join(tmp, "a"), os.path.join(tmp, "b")
            os.makedirs(a)
            os.makedirs(b)
            full, _ = build(a, presenter_layer=True)
            pages, _ = build(b, presenter_layer=False)
        for key in ("layout_modes", "transitions", "punch_ins", "ending_hold", "presenter_states",
                    "punch_steps", "punch_origins", "duration"):
            self.assertEqual(full[key], pages[key], "%s differs between the two builds" % key)

    def test_punch_steps_describe_the_step_function(self):
        with tempfile.TemporaryDirectory() as tmp:
            m, _ = build(tmp, presenter_layer=False)
        steps = m["punch_steps"]
        self.assertEqual([s["at"] for s in steps], sorted(s["at"] for s in steps))
        self.assertEqual({s["scale"] for s in steps}, {1.0, 1.06})
        # Every punch-in is a step, and every move resets the framing.
        for at in m["punch_ins"]:
            self.assertIn(at, [s["at"] for s in steps])
        for mv in m["transitions"]:
            self.assertTrue(any(abs(s["at"] - mv["at"]) < 1e-6 and s["scale"] == 1.0 for s in steps),
                            "move at %s does not reset the punch-in" % mv["at"])


@unittest.skipUnless(os.path.exists(STORYBOARD), "no Phase 3 storyboard")
class TestPresenterTrack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from presenter_track import PresenterTrack
        except ImportError as exc:                      # Pillow only lives in the worker
            raise unittest.SkipTest(str(exc))
        with tempfile.TemporaryDirectory() as tmp:
            cls.m, _ = build(tmp, presenter_layer=False)
        cls.track = PresenterTrack(cls.m)
        cls.modes = lay.build_modes(FRAMING)

    def placement(self, name):
        return self.m["presenter_states"][name]

    def test_between_moves_the_track_sits_exactly_on_the_mode(self):
        for lm in self.m["layout_modes"]:
            # a moment clear of the move that precedes the next board
            t = lm["end"] - 1.0
            if any(mv["at"] <= t <= mv["at"] + mv["duration"] for mv in self.m["transitions"]):
                continue
            st = self.track.state(t)
            # A study docking inside a split page shortens the window (split_docked), so
            # the state's own arrangement is the one to check against, not the board's.
            self.assertIn(st["mode"], (lm["mode"], "split_docked"))
            want = self.placement(st["mode"])
            w = want["window"]
            self.assertAlmostEqual(st["window"][0], w["x"], places=3)
            self.assertAlmostEqual(st["window"][1], w["y"], places=3)
            self.assertAlmostEqual(st["window"][2], w["w"], places=3)
            self.assertAlmostEqual(st["window"][3], w["h"], places=3)
            if abs(st["punch"] - 1.0) < 1e-9:
                self.assertAlmostEqual(st["scale"], want["scale"], places=4)
                self.assertAlmostEqual(st["x"], w["x"] + want["x"], places=3)
                self.assertAlmostEqual(st["y"], w["y"] + want["y"], places=3)

    def test_a_move_starts_and_ends_on_its_two_modes_and_is_monotonic(self):
        mv = self.m["transitions"][0]
        a, b = self.placement(mv["from"]), self.placement(mv["to"])
        start = self.track.state(mv["at"])
        end = self.track.state(mv["at"] + mv["duration"])
        self.assertAlmostEqual(start["window"][0], a["window"]["x"], places=2)
        self.assertAlmostEqual(end["window"][0], b["window"]["x"], places=2)
        xs = [self.track.state(mv["at"] + mv["duration"] * i / 20.0)["window"][0] for i in range(21)]
        direction = 1 if b["window"]["x"] > a["window"]["x"] else -1
        for p, q in zip(xs, xs[1:]):
            self.assertLessEqual(direction * (p - q), 1e-6, "the window reverses mid-move")

    def test_the_window_never_leaves_the_canvas(self):
        total = float(self.m["duration"])
        t = 0.0
        while t < total:
            x, y, w, h = self.track.state(t)["window"]
            self.assertGreaterEqual(x, -0.5)
            self.assertGreaterEqual(y, -0.5)
            self.assertLessEqual(x + w, lay.W + 0.5)
            self.assertLessEqual(y + h, lay.H + 0.5)
            t += 0.25

    def test_punch_in_zooms_about_the_window_and_only_at_cuts(self):
        at = self.m["punch_ins"][0]
        before, after = self.track.state(at - 0.01), self.track.state(at + 0.01)
        self.assertAlmostEqual(before["punch"], 1.0, places=6)
        self.assertAlmostEqual(after["punch"], 1.06, places=6)
        # The framing grows about the origin, so the window itself does not move.
        self.assertEqual(before["window"], after["window"])
        self.assertGreater(after["scale"], before["scale"])

    def test_edge_follows_the_rounded_window(self):
        """The white edge belongs to a rounded window, including the docked one."""
        for lm in self.m["layout_modes"]:
            t = lm["end"] - 1.0
            if any(mv["at"] <= t <= mv["at"] + mv["duration"] for mv in self.m["transitions"]):
                continue
            st = self.track.state(t)
            want = 1 if self.placement(st["mode"])["radius"] else 0
            self.assertAlmostEqual(st["edge"], want, places=6)
            self.assertEqual(want, 0 if st["mode"] in ("glass", "full") else 1)

    def test_frames_paint_the_page_colour_outside_the_window(self):
        from PIL import Image
        src = Image.new("RGB", (lay.W, lay.H), (10, 200, 10))
        split = next(lm for lm in self.m["layout_modes"] if lm["mode"] == "split")
        img = self.track.frame(src, split["end"] - 1.0)
        page = tuple(int(self.m["page_color"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        self.assertEqual(img.getpixel((40, 40)), page)                    # page area
        win = self.m["presenter_states"]["split"]["window"]
        inside = (int(win["x"] + win["w"] / 2), int(win["y"] + win["h"] / 2))
        self.assertEqual(img.getpixel(inside), (10, 200, 10))             # the presenter
        glass = next(lm for lm in self.m["layout_modes"] if lm["mode"] == "glass")
        full = self.track.frame(src, glass["end"] - 1.0)
        self.assertEqual(full.getpixel((40, 40)), (10, 200, 10))          # full frame


if __name__ == "__main__":
    unittest.main()

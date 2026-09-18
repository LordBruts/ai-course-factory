"""Unit tests for the pure parts of the worker. No network, no TTS spend.

    docker exec gymramp-course-worker python -m unittest discover -s /course/tests
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("JOBS_ROOT", tempfile.mkdtemp())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app  # noqa: E402

FIXTURE = Path(__file__).parent / "fixture_package.json"


class SpokenText(unittest.TestCase):
    def test_strips_markers(self):
        self.assertEqual(app.spoken("Red light may help [1]. Evidence is mixed [2, 3]."),
                         "Red light may help. Evidence is mixed.")

    def test_strips_ranges(self):
        self.assertEqual(app.spoken("Shown in trials [4-6]."), "Shown in trials.")

    def test_keeps_ordinary_brackets_text(self):
        # Only numeric markers are removed; words in brackets are spoken.
        self.assertEqual(app.spoken("Use a device [see manual]."), "Use a device [see manual].")


class Deck(unittest.TestCase):
    def setUp(self):
        self.pkg = app.CoursePackage.model_validate_json(FIXTURE.read_text())

    def test_order(self):
        kinds = [e["kind"] for e in app.narration_plan(self.pkg)]
        self.assertEqual(kinds[0], "title")
        self.assertEqual(kinds[-1], "references")
        self.assertEqual(kinds.count("content"), len(self.pkg.slides))

    def test_every_slide_has_narration(self):
        for e in app.narration_plan(self.pkg):
            self.assertTrue(app.spoken(e["notes"]), e["title"])


class ReferencePages(unittest.TestCase):
    def test_references_paginate(self):
        # Ten citations on one slide overflowed the canvas on the first real course.
        pkg = app.CoursePackage.model_validate_json(FIXTURE.read_text())
        pkg.references = [app.Reference(n=i, citation="Ref %d" % i) for i in range(1, 11)]
        pages = [e for e in app.narration_plan(pkg) if e["kind"] == "references"]
        self.assertEqual([len(p["references"]) for p in pages], [4, 4, 2])
        self.assertEqual(pages[1]["title"], "References (2 of 3)")


class SpendGuard(unittest.TestCase):
    def test_refuses_before_spending(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError) as ctx:
                app.synthesize_all(["x" * (app.MAX_TTS_CHARS + 1)], Path(d), "elevenlabs", "t")
            self.assertIn("No TTS characters were spent", str(ctx.exception))
            self.assertEqual(list(Path(d).iterdir()), [])


class Canvas(unittest.TestCase):
    def test_even_dimensions(self):
        # libx264 rejects odd frame sizes; this once shipped as 1919x1080.
        w, h = app.PngCanvas().img.size
        self.assertEqual((w % 2, h % 2), (0, 0))


class Documents(unittest.TestCase):
    def test_documents_and_pptx_build(self):
        from pptx import Presentation
        pkg = app.CoursePackage.model_validate_json(FIXTURE.read_text())
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            app.write_worksheet(pkg, d / "w.docx")
            app.write_assessment(pkg, pkg.exam, "Exam", d / "e.docx")
            app.write_answer_key(pkg, d / "k.docx")
            prs = Presentation()
            deck = app.narration_plan(pkg)
            for i, e in enumerate(deck):
                app.render_slide(e, prs, d / ("s%d.png" % i), pkg, len(deck), i + 1)
            prs.save(d / "c.pptx")
            back = Presentation(d / "c.pptx")
            self.assertEqual(len(back.slides), len(deck))
            for s in back.slides:
                self.assertTrue(s.notes_slide.notes_text_frame.text.strip())
            self.assertTrue((d / "s1.png").stat().st_size > 10000)


if __name__ == "__main__":
    unittest.main()

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import skillboard  # noqa: E402


class Hints(unittest.TestCase):
    def test_quoted_phrases_become_triggers(self):
        say, when = skillboard.hints('Plan trips. Use when you say "plan my trip" or "book a flight".')
        self.assertEqual(say, ["plan my trip", "book a flight"])
        self.assertTrue(when.startswith("Use when"))

    def test_user_is_not_mistaken_for_use(self):
        _, when = skillboard.hints("Interview the user relentlessly. Use when the user wants to stress-test.")
        self.assertTrue(when.startswith("Use when"))


class WordMap(unittest.TestCase):
    def test_reads_a_table_headed_owner_says(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "CLAUDE.md"
            p.write_text('| Owner says | Do this |\n|---|---|\n| "plan my trip" | `trip-planner` |\n', encoding="utf-8")
            rows = skillboard.word_maps(p, "Every project")
        self.assertEqual(rows, [dict(say='"plan my trip"', do="trip-planner", scope="Every project")])

    def test_ignores_other_tables(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "CLAUDE.md"
            p.write_text("| Phase | Skill |\n|---|---|\n| 0 | brief |\n", encoding="utf-8")
            self.assertEqual(skillboard.word_maps(p, "x"), [])


class Demo(unittest.TestCase):
    def test_demo_page_builds_and_has_no_personal_data(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "page.html"
            subprocess.run([sys.executable, str(ROOT / "skillboard.py"), "--demo", "--offline", "--no-open", "--out", str(out)],
                           check=True, capture_output=True)
            page = out.read_text(encoding="utf-8")
        self.assertIn("DEMO DATA", page)
        home = str(Path.home())
        for form in (home, home.replace("\\", "\\\\"), home.replace("\\", "/"), Path.home().name):
            self.assertNotIn(form, page)

    def test_plural(self):
        self.assertEqual(skillboard.plural(1, "skill"), "1 skill")
        self.assertEqual(skillboard.plural(3, "skill"), "3 skills")


if __name__ == "__main__":
    unittest.main()

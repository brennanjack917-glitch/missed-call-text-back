import tempfile
import unittest
from pathlib import Path

from scripts.env import load_env, require


class EnvTests(unittest.TestCase):
    def test_reads_values_and_skips_comments(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text('# note\nGMAIL_ADDRESS="a@b.com"\n\nALERT_TO=c@d.com\n', encoding="utf-8")
            env = load_env(p)
        self.assertEqual(env["GMAIL_ADDRESS"], "a@b.com")
        self.assertEqual(env["ALERT_TO"], "c@d.com")

    def test_require_reports_missing_keys(self):
        with self.assertRaises(SystemExit) as ctx:
            require({"A": "1"}, "A", "B")
        self.assertIn("B", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

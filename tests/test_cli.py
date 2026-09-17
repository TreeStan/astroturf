import io
import importlib.util
import unittest
from contextlib import redirect_stdout
from pathlib import Path

spec = importlib.util.spec_from_file_location("astroturf", Path(__file__).resolve().parent.parent / "astroturf.py")
at = importlib.util.module_from_spec(spec)
spec.loader.exec_module(at)


class Cli(unittest.TestCase):
    def test_explain_lists_every_weight(self):
        out = io.StringIO()
        with redirect_stdout(out):
            at.main(["explain"])
        for k in at.WEIGHTS:
            self.assertIn(k, out.getvalue())

    def test_parse_span(self):
        self.assertEqual(at.parse_span("90d"), 90)
        self.assertEqual(at.parse_span("2w"), 14)
        self.assertEqual(at.parse_span("6m"), 180)
        with self.assertRaises(SystemExit):
            at.parse_span("soon")


if __name__ == "__main__":
    unittest.main()

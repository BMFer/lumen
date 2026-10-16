"""Golden tests: each example's output must match tests/golden/<name>.out.

After an intentional change, regenerate with `make golden` and review the diff.
"""

import io
import pathlib
import unittest

from lumen import Interpreter

ROOT = pathlib.Path(__file__).resolve().parent.parent
EXAMPLES = sorted((ROOT / "examples").glob("*.lum"))


class Examples(unittest.TestCase):
    def test_examples_exist(self):
        self.assertGreaterEqual(len(EXAMPLES), 4)

    def test_examples_match_golden_output(self):
        for path in EXAMPLES:
            with self.subTest(example=path.name):
                out = io.StringIO()
                Interpreter(out=out).run(path.read_text(encoding="utf-8"), str(path))
                golden = ROOT / "tests" / "golden" / f"{path.stem}.out"
                self.assertEqual(out.getvalue(), golden.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

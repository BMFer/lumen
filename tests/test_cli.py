"""End-to-end tests of the command line and the REPL, run as real processes."""

import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def lumen(*args, stdin=""):
    with tempfile.TemporaryDirectory() as home:  # keep REPL history out of the real $HOME
        env = {**os.environ, "PYTHONPATH": str(ROOT), "NO_COLOR": "1", "HOME": home}
        return subprocess.run([sys.executable, "-m", "lumen", *args], input=stdin,
                              capture_output=True, text=True, env=env, timeout=30)


class Cli(unittest.TestCase):
    def test_eval_prints_value(self):
        r = lumen("-e", "(1..=4).map(fn(x) => x * x)")
        self.assertEqual((r.returncode, r.stdout), (0, "[1, 4, 9, 16]\n"))

    def test_runtime_error_exit_code_and_render(self):
        r = lumen("-e", "let xs = [1]\nxs[3]")
        self.assertEqual(r.returncode, 1)
        self.assertIn("runtime error: index 3 is out of bounds", r.stderr)
        self.assertIn("2 | xs[3]", r.stderr)

    def test_stdin_script(self):
        r = lumen("-", stdin='print("from stdin")')
        self.assertEqual(r.stdout, "from stdin\n")

    def test_missing_file(self):
        r = lumen("does-not-exist.lum")
        self.assertEqual(r.returncode, 2)
        self.assertIn("can't open", r.stderr)


class Repl(unittest.TestCase):
    def test_session(self):
        session = "\n".join([
            "let x = 20",
            "x + 1",
            "fn twice(f, v) {",       # multi-line input continues...
            "  f(f(v))",
            "}",                      # ...until the block closes
            "twice(fn(n) => n * 3, x)",
            "undefined_name",
            ":help",
            "x",
        ]) + "\n"
        r = lumen(stdin=session)
        self.assertEqual(r.returncode, 0)
        self.assertIn("21\n", r.stdout)
        self.assertIn("180\n", r.stdout)
        self.assertIn(":reset", r.stdout)
        self.assertIn("undefined variable 'undefined_name'", r.stderr)
        self.assertIn("lumen> 20\n", r.stdout)  # state survived the error

    def test_blank_line_abandons_unfinished_input(self):
        r = lumen(stdin="[1, 2\n\n3 * 3\n")
        self.assertIn("expected ',' or ']'", r.stderr)
        self.assertIn("9\n", r.stdout)


if __name__ == "__main__":
    unittest.main()

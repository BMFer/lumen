"""Hostile inputs must produce Lumen errors -- never hangs or Python tracebacks."""

import unittest

from helpers import LumenTestCase


class Limits(LumenTestCase):
    def test_huge_repetition_is_refused(self):
        self.assertRuntimeError('"x" * 10 ** 10', "result too large")
        self.assertRuntimeError("10 ** 10 * [0]", "result too large")

    def test_deep_nesting_is_a_syntax_error(self):
        self.assertSyntaxError("(" * 100_000 + "1" + ")" * 100_000, "nested too deeply")
        self.assertSyntaxError("[" * 100_000 + "]" * 100_000, "nested too deeply")

    def test_moderate_nesting_works(self):
        self.assertEval("(" * 2000 + "1" + ")" * 2000, 1)
        self.assertEval("-" * 2000 + "1", 1)

    def test_numeric_limits(self):
        self.assertRuntimeError("10.0 ** 400", "numeric overflow")
        self.assertRuntimeError("2 ** 100000", "number too large")
        self.assertRuntimeError("(-8) ** 0.5", "not a real number")

    def test_big_ints_round_trip_through_strings(self):
        self.assertEval('len(str(int("9" * 5000)))', 5000)

    def test_error_messages_truncate_values(self):
        err = self.assertRuntimeError('int("x" * 5000)', "can't parse")
        self.assertLess(len(err.message), 120)
        err = self.assertRuntimeError("match list(0..1000) { [] => 0 }", "no match arm matched")
        self.assertLess(len(err.message), 120)


if __name__ == "__main__":
    unittest.main()

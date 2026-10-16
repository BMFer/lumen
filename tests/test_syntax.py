import unittest

from helpers import LumenTestCase

from lumen.errors import LumenSyntaxError, Source
from lumen.parser import Parser


def parse_error(text: str) -> LumenSyntaxError:
    try:
        Parser(Source(text, "<t>")).parse_program()
    except LumenSyntaxError as e:
        return e
    raise AssertionError(f"expected a syntax error for {text!r}")


class StatementBoundaries(LumenTestCase):
    def test_newline_ends_statement(self):
        # Without newline sensitivity this would parse as `1(2)` or `1 - 1`.
        self.assertEval("let a = 1\n(2)", 2)
        self.assertEval("let a = 5\n-1", -1)

    def test_open_brackets_continue(self):
        self.assertEval("let xs = [\n  1,\n  2,\n]\nxs", [1, 2])
        self.assertEval("max(\n  3,\n  9\n)", 9)
        self.assertEval("(1\n + 2)", 3)

    def test_semicolons(self):
        self.assertEval("let a = 1; let b = 2; a + b", 3)

    def test_two_statements_on_one_line(self):
        self.assertSyntaxError("let x = 1 let y = 2", "expected end of statement")


class Errors(LumenTestCase):
    def test_helpful_hints(self):
        self.assertIn("'and'", parse_error("a && b").hint)
        self.assertIn("'or'", parse_error("a || b").hint)
        self.assertIn("'not'", parse_error("!a").hint)
        self.assertIn("double quotes", parse_error("'x'").hint)
        self.assertIn("a < b and b < c", parse_error("1 < 2 < 3").hint)

    def test_statements_are_not_expressions(self):
        e = parse_error("let x = let y = 1")
        self.assertIn("is a statement", e.hint)

    def test_misplaced_control_flow(self):
        self.assertSyntaxError("return 1", "'return' outside of a function")
        self.assertSyntaxError("break", "'break' outside of a loop")
        # A function body inside a loop is not itself in a loop.
        self.assertSyntaxError("while true { fn() { break } }", "'break' outside of a loop")

    def test_invalid_assignment_target(self):
        self.assertSyntaxError("1 + 2 = 3", "invalid assignment target")

    def test_bad_literals(self):
        self.assertSyntaxError("12abc", "invalid number literal '12abc'")
        self.assertSyntaxError('"{}"', "empty interpolation")
        self.assertSyntaxError('"a}"', "unmatched '}'")
        self.assertSyntaxError("@", "unexpected character '@'")

    def test_duplicate_param(self):
        self.assertSyntaxError("fn f(a, a) { }", "duplicate parameter 'a'")


class Incompleteness(unittest.TestCase):
    """The REPL relies on `incomplete` to decide whether to keep reading."""

    def test_unfinished_input_is_incomplete(self):
        for text in ["fn f() {", "[1, 2", "let x =", '"abc', '"{1 + ', "match x {", "f(1,", "1 +"]:
            with self.subTest(text=text):
                self.assertTrue(parse_error(text).incomplete)

    def test_real_errors_are_not_incomplete(self):
        for text in ["let = 1", "1 < 2 < 3", "fn f() { ) }", "@"]:
            with self.subTest(text=text):
                self.assertFalse(parse_error(text).incomplete)


class Rendering(unittest.TestCase):
    def test_caret_points_at_span(self):
        e = parse_error("let total = 1\nlet x = total &&  2")
        self.assertEqual(e.render().splitlines(), [
            "syntax error: unexpected '&&'",
            " --> <t>:2:15",
            "  |",
            "2 | let x = total &&  2",
            "  |               ^^",
            "  = hint: Lumen spells this 'and'",
        ])

    def test_caret_respects_tabs(self):
        e = parse_error("\tlet x = @")
        caret_line = e.render().splitlines()[4]
        self.assertTrue(caret_line.endswith("\t        ^"), repr(caret_line))


if __name__ == "__main__":
    unittest.main()

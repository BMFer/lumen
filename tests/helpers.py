import io
import unittest

from lumen import Interpreter, LumenError, LumenRuntimeError, LumenSyntaxError


class LumenTestCase(unittest.TestCase):
    def run_lumen(self, source: str):
        """Run source; return (last value, printed output)."""
        out = io.StringIO()
        value = Interpreter(out=out).run(source, "<test>")
        return value, out.getvalue()

    def eval(self, source: str):
        return self.run_lumen(source)[0]

    def output(self, source: str) -> str:
        return self.run_lumen(source)[1]

    def assertEval(self, source: str, expected):
        value = self.eval(source)
        self.assertEqual(value, expected, msg=f"\nsource: {source}")
        self.assertIs(type(value), type(expected), msg=f"\nsource: {source}")

    def assertError(self, source: str, fragment: str, kind=LumenError) -> LumenError:
        with self.assertRaises(kind) as ctx:
            self.run_lumen(source)
        self.assertIn(fragment, ctx.exception.message)
        return ctx.exception

    def assertSyntaxError(self, source: str, fragment: str) -> LumenSyntaxError:
        return self.assertError(source, fragment, LumenSyntaxError)

    def assertRuntimeError(self, source: str, fragment: str) -> LumenRuntimeError:
        return self.assertError(source, fragment, LumenRuntimeError)

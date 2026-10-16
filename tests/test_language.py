import unittest

from helpers import LumenTestCase


class Arithmetic(LumenTestCase):
    def test_precedence(self):
        self.assertEval("1 + 2 * 3", 7)
        self.assertEval("(1 + 2) * 3", 9)
        self.assertEval("2 ** 3 ** 2", 512)       # right-associative
        self.assertEval("-2 ** 2", -4)            # unary binds looser than **
        self.assertEval("10 - 4 - 3", 3)          # left-associative

    def test_division(self):
        self.assertEval("7 / 2", 3.5)
        self.assertEval("7 // 2", 3)
        self.assertEval("-7 % 3", 2)
        self.assertRuntimeError("1 / 0", "division by zero")
        self.assertRuntimeError("1 % 0", "division by zero")

    def test_numbers(self):
        self.assertEval("1_000_000", 1000000)
        self.assertEval("1.5e3", 1500.0)
        self.assertEval("0.1 + 0.2 == 0.3", False)
        self.assertEval("1 == 1.0", True)

    def test_strings_and_lists(self):
        self.assertEval('"ab" + "cd"', "abcd")
        self.assertEval('"ab" * 3', "ababab")
        self.assertEval("[1] + [2, 3]", [1, 2, 3])
        self.assertEval("[0] * 3", [0, 0, 0])
        self.assertEval('"apple" < "banana"', True)

    def test_type_errors(self):
        err = self.assertRuntimeError('"n = " + 5', "can't add string and int")
        self.assertIn("interpolate", err.hint)
        self.assertRuntimeError("[1] < [2]", "unsupported operand types for '<'")
        self.assertRuntimeError('-"x"', "can't negate string")


class Logic(LumenTestCase):
    def test_truthiness(self):
        # Only false and nil are falsy.
        self.assertEval("if 0 { 1 } else { 2 }", 1)
        self.assertEval('if "" { 1 } else { 2 }', 1)
        self.assertEval("if nil { 1 } else { 2 }", 2)
        self.assertEval("not nil", True)

    def test_short_circuit_returns_operand(self):
        self.assertEval('nil or "default"', "default")
        self.assertEval("1 and 2", 2)
        self.assertEval("false and undefined_thing", False)
        self.assertEval("true or undefined_thing", True)

    def test_not_precedence(self):
        self.assertEval("not 1 == 2", True)
        self.assertEval("not false and false", False)

    def test_equality_is_deep_and_strict(self):
        self.assertEval("[1, [2, {a: 3}]] == [1, [2, {a: 3}]]", True)
        self.assertEval("1 == true", False)
        self.assertEval("0 == false", False)
        self.assertEval("nil == false", False)


class Bindings(LumenTestCase):
    def test_let_and_assign(self):
        self.assertEval("let x = 1\nx = x + 1\nx", 2)
        self.assertEval("let x = 10\nx += 5\nx -= 3\nx *= 2\nx /= 4\nx", 6.0)

    def test_assign_requires_declaration(self):
        err = self.assertRuntimeError("y = 1", "undefined variable 'y'")
        self.assertIn("let y", err.hint)

    def test_block_scoping_and_shadowing(self):
        self.assertEval("let x = 1\nif true { let x = 2 }\nx", 1)
        self.assertEval("let x = 1\nif true { x = 2 }\nx", 2)

    def test_destructuring_let(self):
        self.assertEval("let [a, b] = [1, 2]\na * 10 + b", 12)
        self.assertEval("let [head, ..tail] = [1, 2, 3]\ntail", [2, 3])
        self.assertEval('let {name, age: years} = {name: "Ada", age: 36}\n"{name}/{years}"', "Ada/36")
        self.assertRuntimeError("let [a, b] = [1]", "pattern doesn't match [1]")

    def test_undefined_variable_suggestion(self):
        err = self.assertRuntimeError("let counter = 0\ncountr", "undefined variable 'countr'")
        self.assertEqual(err.hint, "did you mean 'counter'?")


class Functions(LumenTestCase):
    def test_forms(self):
        self.assertEval("fn add(a, b) { a + b }\nadd(2, 3)", 5)
        self.assertEval("let sq = fn(x) => x * x\nsq(7)", 49)
        self.assertEval("(fn() { 42 })()", 42)

    def test_return(self):
        src = """
        fn sign(n) {
          if n < 0 { return -1 }
          if n == 0 { return 0 }
          1
        }
        [sign(-5), sign(0), sign(9)]
        """
        self.assertEval(src, [-1, 0, 1])
        self.assertEval("fn f() { return }\nf()", None)

    def test_recursion(self):
        self.assertEval("fn fact(n) { if n <= 1 { 1 } else { n * fact(n - 1) } }\nfact(20)", 2432902008176640000)

    def test_deep_recursion_is_supported(self):
        self.assertEval("fn down(n) { if n == 0 { 0 } else { down(n - 1) } }\ndown(1400)", 0)

    def test_closures_capture_and_mutate(self):
        src = """
        fn counter() {
          let n = 0
          fn() { n += 1; n }
        }
        let a = counter()
        let b = counter()
        a(); a()
        [a(), b()]
        """
        self.assertEval(src, [3, 1])

    def test_closures_in_loops_capture_each_iteration(self):
        src = """
        let fns = []
        for i in 0..3 { push(fns, fn() => i) }
        fns.map(fn(f) => f())
        """
        self.assertEval(src, [0, 1, 2])

    def test_destructuring_parameters(self):
        self.assertEval("let add = fn([a, b]) => a + b\nadd([2, 3])", 5)
        self.assertEval('[{x: 1}, {x: 2}].map(fn({x}) => x * 10)', [10, 20])
        self.assertEval("fn f(_, b) { b }\nf(1, 2)", 2)
        self.assertRuntimeError("let f = fn([a, b]) => a\nf([1])", "pattern doesn't match [1]")
        self.assertSyntaxError("fn f(a, [b, a]) { }", "duplicate parameter 'a'")

    def test_arity(self):
        self.assertRuntimeError("fn f(a) { a }\nf(1, 2)", "takes 1 argument, but got 2")
        self.assertRuntimeError("len()", "len() takes 1 argument, but got 0")

    def test_not_callable(self):
        self.assertRuntimeError("let x = 5\nx()", "int is not callable")

    def test_stack_overflow_is_reported(self):
        err = self.assertRuntimeError("fn f() { f() }\nf()", "stack overflow")
        rendered = err.render()
        self.assertIn("repeated", rendered)
        self.assertLess(len(rendered.splitlines()), 20)

    def test_traceback(self):
        src = "fn inner() { 1 / 0 }\nfn outer() { inner() }\nouter()"
        err = self.assertRuntimeError(src, "division by zero")
        self.assertEqual([name for name, _ in err.trace], ["outer", "inner"])


class Pipelines(LumenTestCase):
    def test_pipe(self):
        self.assertEval("[3, 1, 2] |> sort", [1, 2, 3])
        self.assertEval("[1, 2, 3] |> map(fn(x) => x * 2) |> sum", 12)

    def test_pipe_across_lines(self):
        src = """
        let total = 1..=10
          |> filter(fn(n) => n % 2 == 0)
          |> map(fn(n) => n * n)
          |> sum
        total
        """
        self.assertEval(src, 220)

    def test_method_syntax(self):
        self.assertEval("[1, 2, 3, 4].filter(fn(x) => x > 2).len()", 2)
        self.assertEval('"a,b,c".split(",").reverse().join("-")', "c-b-a")
        self.assertEval("fn double(x) { x * 2 }\n21.double()", 42)

    def test_method_chain_across_lines(self):
        self.assertEval('"  Hello  "\n  .trim()\n  .upper()', "HELLO")

    def test_map_fields_take_priority(self):
        self.assertEval("let obj = {len: fn() => 99}\nobj.len()", 99)

    def test_method_missing(self):
        self.assertRuntimeError("5.frobnicate()", "int has no method or field 'frobnicate'")


class Collections(LumenTestCase):
    def test_indexing(self):
        self.assertEval("[10, 20, 30][1]", 20)
        self.assertEval("[10, 20, 30][-1]", 30)
        self.assertEval('"hello"[1..4]', "ell")
        self.assertEval("[1, 2, 3, 4, 5][1..=3]", [2, 3, 4])
        self.assertRuntimeError("[1, 2][5]", "index 5 is out of bounds for a list of length 2")

    def test_index_assignment(self):
        self.assertEval("let xs = [1, 2, 3]\nxs[0] = 9\nxs[-1] += 10\nxs", [9, 2, 13])
        self.assertEval("let m = {}\nm.a = 1\nm[\"b\"] = 2\nm.a += 5\nm", {"a": 6, "b": 2})
        self.assertRuntimeError('let s = "abc"\ns[0] = "x"', "strings are immutable")

    def test_compound_index_assignment_evaluates_index_once(self):
        src = """
        let calls = 0
        fn i() { calls += 1; 0 }
        let xs = [1]
        xs[i()] += 1
        [xs, calls]
        """
        self.assertEval(src, [[2], 1])

    def test_maps(self):
        self.assertEval('let name = "x"\n{name, "k": 1, 2: true}', {"name": "x", "k": 1, 2: True})
        self.assertEval('{a: 1}.a', 1)
        self.assertEval('get({a: 1}, "b", 0)', 0)
        self.assertRuntimeError('{a: 1}["b"]', 'key "b" not found')
        self.assertRuntimeError("{[1]: 2}", "map keys must be strings or numbers")

    def test_ranges(self):
        self.assertEval("list(0..4)", [0, 1, 2, 3])
        self.assertEval("list(1..=3)", [1, 2, 3])
        self.assertEval("len(0..100)", 100)
        self.assertRuntimeError("1.5..3", "range bounds must be integers")


class ControlFlow(LumenTestCase):
    def test_if_is_an_expression(self):
        self.assertEval('let n = 5\nlet size = if n > 3 { "big" } else { "small" }\nsize', "big")
        self.assertEval("if false { 1 }", None)
        self.assertEval("let x = 2\nif x == 1 { \"a\" } else if x == 2 { \"b\" } else { \"c\" }", "b")

    def test_else_on_next_line(self):
        self.assertEval("if false {\n  1\n}\nelse {\n  2\n}", 2)

    def test_while_break_continue(self):
        src = """
        let i = 0
        let seen = []
        while true {
          i += 1
          if i % 2 == 0 { continue }
          if i > 7 { break }
          push(seen, i)
        }
        seen
        """
        self.assertEval(src, [1, 3, 5, 7])

    def test_for_over_everything(self):
        self.assertEval("let s = 0\nfor x in [1, 2, 3] { s += x }\ns", 6)
        self.assertEval('let s = ""\nfor c in "abc" { s = c + s }\ns', "cba")
        self.assertEval('let ks = []\nfor k in {a: 1, b: 2} { push(ks, k) }\nks', ["a", "b"])
        self.assertEval("let out = []\nfor [i, x] in enumerate([\"a\", \"b\"]) { push(out, \"{i}{x}\") }\nout",
                        ["0a", "1b"])
        self.assertRuntimeError("for x in 5 { }", "can't iterate over int")

    def test_mutating_list_during_iteration_is_safe(self):
        self.assertEval("let xs = [1, 2]\nfor x in xs { push(xs, x) }\nxs", [1, 2, 1, 2])


class Matching(LumenTestCase):
    def test_literals_ranges_wildcards(self):
        src = """
        fn describe(n) {
          match n {
            0 => "zero"
            1 | 2 | 3 => "small"
            4..10 => "medium"
            -5..=-1 => "negative"
            _ => "other"
          }
        }
        [0, 2, 7, -3, 99].map(describe)
        """
        self.assertEval(src, ["zero", "small", "medium", "negative", "other"])

    def test_list_patterns(self):
        src = """
        fn shape(xs) {
          match xs {
            [] => "empty"
            [x] => "one: {x}"
            [first, ..middle, last] => "{first}..{last} ({len(middle)} between)"
          }
        }
        [shape([]), shape([7]), shape([1, 2, 3, 4])]
        """
        self.assertEval(src, ["empty", "one: 7", "1..4 (2 between)"])

    def test_map_patterns_and_guards(self):
        src = """
        fn greet(p) {
          match p {
            {name, age} if age < 18 => "hi {name}"
            {name, title: "Dr"} => "good day, Dr. {name}"
            {name} => "hello {name}"
            _ => "who?"
          }
        }
        [greet({name: "Sam", age: 12}), greet({name: "Lee", title: "Dr"}), greet({name: "Kim", age: 40}), greet(5)]
        """
        self.assertEval(src, ["hi Sam", "good day, Dr. Lee", "hello Kim", "who?"])

    def test_nested_and_block_arms(self):
        src = """
        let expr = ["add", ["num", 2], ["mul", ["num", 3], ["num", 4]]]
        fn ev(e) {
          match e {
            ["num", n] => n
            ["add", a, b] => ev(a) + ev(b)
            ["mul", a, b] => {
              let x = ev(a)
              x * ev(b)
            }
          }
        }
        ev(expr)
        """
        self.assertEval(src, 14)

    def test_no_match(self):
        err = self.assertRuntimeError('match 5 { 1 => "one" }', "no match arm matched 5")
        self.assertIn("_ =>", err.hint)

    def test_or_patterns_cannot_bind(self):
        self.assertSyntaxError("match 1 { x | 2 => x }", "can't bind variables")


class Strings(LumenTestCase):
    def test_interpolation(self):
        self.assertEval('let n = 3\n"n={n}, n²={n * n}"', "n=3, n²=9")
        self.assertEval('"nested: {"inner {1 + 1}"}"', "nested: inner 2")
        self.assertEval('"{[1, "a"]}"', '[1, "a"]')
        self.assertEval('"escaped \\{braces\\}"', "escaped {braces}")

    def test_escapes(self):
        self.assertEval('"a\\tb\\n"', "a\tb\n")
        self.assertSyntaxError('"\\q"', "unknown escape sequence")

    def test_interpolation_error_points_into_string(self):
        err = self.assertRuntimeError('let name = 1\n"hi {nmae}"', "undefined variable 'nmae'")
        line, col = err.span.source.line_col(err.span.start)
        self.assertEqual((line, col), (2, 6))


class Printing(LumenTestCase):
    def test_print_formats(self):
        out = self.output('print(1, 2.5, "s", nil, true, [1, "a", nil], {k: [1]}, 1..3, print)')
        self.assertEqual(out, 's'.join(['1 2.5 ', ' nil true [1, "a", nil] {"k": [1]} 1..3 <builtin print>\n']))

    def test_cyclic_values_print(self):
        self.assertEqual(self.output("let xs = [1]\npush(xs, xs)\nprint(xs)"), "[1, [...]]\n")


if __name__ == "__main__":
    unittest.main()

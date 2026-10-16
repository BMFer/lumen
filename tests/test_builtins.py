import unittest

from helpers import LumenTestCase


class Builtins(LumenTestCase):
    def test_higher_order(self):
        self.assertEval("map([1, 2], fn(x) => x + 1)", [2, 3])
        self.assertEval("filter(1..10, fn(x) => x % 3 == 0)", [3, 6, 9])
        self.assertEval("reject([1, 2, 3], fn(x) => x == 2)", [1, 3])
        self.assertEval("reduce([1, 2, 3], fn(acc, x) => acc * 10 + x, 0)", 123)
        self.assertEval("find([1, 5, 8], fn(x) => x > 4)", 5)
        self.assertEval("find([1], fn(x) => x > 4)", None)
        self.assertEval("count(1..=10, fn(x) => x > 7)", 3)
        self.assertEval("[any([1, 3], fn(x) => x > 2), all([1, 3], fn(x) => x > 2)]", [True, False])

    def test_builtins_accept_builtins(self):
        self.assertEval('["1", "22"].map(len)', [1, 2])
        self.assertEval('[" a ", "b "].map(trim).join()', "ab")

    def test_sorting(self):
        self.assertEval("sort([3, 1.5, 2])", [1.5, 2, 3])
        self.assertEval('sort(["pear", "fig", "apple"], len)', ["fig", "pear", "apple"])
        self.assertEval("sort([[2, 1], [1, 9], [1, 2]])", [[1, 2], [1, 9], [2, 1]])
        self.assertRuntimeError('sort([1, "a"])', "can't compare number and string values")
        self.assertRuntimeError("sort([{}, {}])", "can't order values of type map")

    def test_grouping(self):
        self.assertEval('group_by(["ant", "bee", "cow", "ape"], fn(w) => w[0])',
                        {"a": ["ant", "ape"], "b": ["bee"], "c": ["cow"]})
        self.assertEval('tally(chars("hello"))', {"h": 1, "e": 1, "l": 2, "o": 1})
        self.assertEval("uniq([1, 2, 1, [3], [3]])", [1, 2, [3]])
        self.assertEval("chunks(1..=5, 2)", [[1, 2], [3, 4], [5]])
        self.assertEval("zip([1, 2, 3], \"ab\")", [[1, "a"], [2, "b"]])
        self.assertEval("flatten([[1], 2, [3, 4]])", [1, 2, 3, 4])

    def test_collections(self):
        self.assertEval("let xs = [1]\npush(xs, 2)\n[pop(xs), xs]", [2, [1]])
        self.assertEval("let m = {a: 1, b: 2}\n[remove(m, \"a\"), m]", [1, {"b": 2}])
        self.assertEval('[keys({a: 1}), values({a: 1}), entries({a: 1})]', [["a"], [1], [["a", 1]]])
        self.assertEval('[contains([1, [2]], [2]), contains("team", "ea"), contains({a: 1}, "a")]',
                        [True, True, True])
        self.assertEval('[index_of([5, 6], 6), index_of("abc", "z")]', [1, None])
        self.assertEval("[take(1..10, 2), drop([1, 2, 3], 2)]", [[1, 2], [3]])
        self.assertRuntimeError("pop([])", "pop(): can't pop from an empty list")

    def test_numbers(self):
        self.assertEval("[min(3, 1, 2), max([4, 9]), sum(1..=100)]", [1, 9, 5050])
        self.assertEval("[abs(-3), floor(2.7), ceil(2.1), round(2.567, 2), sqrt(16)]", [3, 2, 3, 2.57, 4.0])
        self.assertEval('[int("42"), int(3.9), float("2.5")]', [42, 3, 2.5])
        self.assertRuntimeError('int("nope")', "can't parse \"nope\" as an int")
        self.assertRuntimeError("max([])", "max of an empty list")

    def test_random_is_seedable(self):
        a = self.eval("seed(7)\n[random(100), random(1, 6)]")
        b = self.eval("seed(7)\n[random(100), random(1, 6)]")
        self.assertEqual(a, b)
        self.assertTrue(0 <= a[0] < 100 and 1 <= a[1] <= 6)

    def test_strings(self):
        self.assertEval('split("a b  c")', ["a", "b", "c"])
        self.assertEval('split("a,b", ",")', ["a", "b"])
        self.assertEval('split("abc", "")', ["a", "b", "c"])
        self.assertEval('join([1, "x", nil], "-")', "1-x-nil")
        self.assertEval('[upper("a"), lower("B"), replace("aXa", "a", "b")]', ["A", "b", "bXb"])
        self.assertEval('[starts_with("lumen", "lu"), ends_with("lumen", "x")]', [True, False])
        self.assertEval('[pad_left(7, 3, "0"), pad_right("a", 3) + "|"]', ["007", "a  |"])
        self.assertEval('[ord("A"), chr(97), is_digit("123"), is_digit(""), is_alpha("ab")]',
                        [65, "a", True, False, True])
        self.assertEval('lines("a\\nb")', ["a", "b"])

    def test_type_and_repr(self):
        self.assertEval("[1, 1.0, \"s\", nil, true, [], {}, 0..1, len, fn() => 1].map(type)",
                        ["int", "float", "string", "nil", "bool", "list", "map", "range", "function", "function"])
        self.assertEval('repr("a\\n")', '"a\\n"')
        self.assertEval('str("a")', "a")

    def test_argument_errors(self):
        self.assertRuntimeError("len(5)", "len(): argument must be a list or a string or a map or a range")
        self.assertRuntimeError("map([1], 5)", "map(): second argument must be a function")
        self.assertRuntimeError('upper(1)', "upper(): argument must be a string")

    def test_error_and_assert(self):
        err = self.assertRuntimeError('fn check(x) { if x < 0 { error("negative: {x}") } }\ncheck(-2)',
                                      "negative: -2")
        self.assertEqual(err.message, "negative: -2")
        self.assertRuntimeError('assert(1 == 2, "math broke")', "assertion failed: math broke")
        self.assertEval("assert(true)", None)

    def test_errors_in_callbacks_carry_trace(self):
        err = self.assertRuntimeError("let f = fn(x) => x / 0\nmap([1], f)", "division by zero")
        self.assertEqual([name for name, _ in err.trace], ["f"])


if __name__ == "__main__":
    unittest.main()

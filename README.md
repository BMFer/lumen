# Lumen

A small, expression-oriented scripting language with pattern matching,
pipelines, closures, and error messages that tell you what went wrong and
how to fix it. It is written in about 2,500 lines of pure Python with
no dependencies.

```lumen
fn fizzbuzz(n) {
  match [n % 3, n % 5] {
    [0, 0] => "FizzBuzz"
    [0, _] => "Fizz"
    [_, 0] => "Buzz"
    _ => str(n)
  }
}

(1..=15).map(fizzbuzz).join(" ") |> print
```

```
$ bin/lumen -e 'let total = 5
print("total: " + total)'
runtime error: can't add string and int
 --> <eval>:2:7
  |
2 | print("total: " + total)
  |       ^^^^^^^^^^^^^^^^^
  = hint: convert with str(x), or interpolate: "total: {x}"
```

## Getting started

Lumen needs Python 3.10 or newer.

```sh
bin/lumen                      # interactive REPL (multi-line input, history)
bin/lumen examples/tour.lum    # run a script
bin/lumen -e '2 ** 100'        # evaluate an expression and print it
echo 'print("hi")' | bin/lumen -
make test                      # run the test suite
```

To get a `lumen` command on your PATH, symlink the launcher:
`ln -s "$PWD/bin/lumen" ~/.local/bin/lumen`. You can also run
`pip install -e .` inside a virtualenv.

## The language in five minutes

**Values:** `nil`, `true`/`false`, ints (arbitrary precision), floats, strings,
lists `[1, 2]`, maps `{name: "Ada", "key with spaces": 1}`, ranges `0..10` and
`1..=10`, and functions. Only `false` and `nil` are falsy.

**Bindings:** `let x = 1`, then `x = 2`, `x += 1`. Blocks introduce scope.
There are no semicolons. A newline ends a statement unless a bracket is still
open or the next line begins with `|>` or `.`.

**Everything is an expression:** `if`/`else`, `match` and blocks produce values.

```lumen
let label = if n > 100 { "big" } else { "small" }
```

**Functions** are closures. A function returns its last expression, and
`return` exits early.

```lumen
fn add(a, b) { a + b }
let square = fn(x) => x * x
fn counter() {
  let n = 0
  fn() { n += 1; n }
}
```

**Strings** interpolate any expression: `"{user.name} has {len(items)} items"`.
Escape a literal brace with `\{`.

**Pipelines and method syntax:** `x |> f(a)` means `f(x, a)`, and `x.f(a)`
means the same thing. As a result, every function works as a method:

```lumen
let total = orders
  |> filter(fn(o) => o.paid)
  |> map(fn(o) => o.amount)
  |> sum

"  hello ".trim().upper()      # "HELLO"
```

If `x` is a map with a field `f`, then `x.f(a)` calls that field instead.

**Pattern matching** supports literals, ranges, `_`, bindings, list patterns
with a rest element, map patterns, `|` alternatives and `if` guards:

```lumen
match value {
  0 => "zero"
  1 | 2 | 3 => "small"
  4..100 => "medium"
  [] => "empty list"
  [first, ..rest] => "list starting with {first}"
  {name, age} if age < 18 => "minor named {name}"
  {name} => "someone named {name}"
  _ => "something else"
}
```

The same patterns destructure in `let`, `for`, and function parameters:

```lumen
let [x, y] = point
for [i, item] in enumerate(items) { print("{i}: {item}") }
pairs.map(fn([k, v]) => "{k}={v}")
```

**Loops:** `while cond { }` and `for pattern in iterable { }` iterate over lists,
ranges, strings and map keys, with `break` and `continue`. Each iteration
gets a fresh scope, so closures made inside a loop capture that iteration's
values.

## Standard library

| Area        | Functions |
|-------------|-----------|
| I/O         | `print` `input` `clock` |
| Types       | `type` `str` `repr` `int` `float` |
| Collections | `len` `list` `range` `push` `pop` `insert` `get` `remove` `contains` `index_of` `keys` `values` `entries` `reverse` `sort` `uniq` `take` `drop` `flatten` `zip` `enumerate` `chunks` |
| Functional  | `map` `filter` `reject` `reduce` `each` `find` `any` `all` `count` `group_by` `tally` |
| Numbers     | `sum` `min` `max` `abs` `sqrt` `floor` `ceil` `round` `random` `seed` `PI` `E` |
| Strings     | `join` `split` `lines` `chars` `trim` `upper` `lower` `replace` `starts_with` `ends_with` `pad_left` `pad_right` `ord` `chr` `is_digit` `is_alpha` |
| Errors      | `error` `assert` |

`sort(xs, key)` sorts with a key function. It refuses mixed types instead of
guessing an order.

## Errors

Diagnostics point at the exact source span. This works inside string
interpolations and across REPL inputs, because every span keeps a reference
to its own source text. Runtime errors carry a Lumen call stack, and
identical frames from deep recursion are folded into one line. Many errors
include a hint:

- Misspelled names get a "did you mean 'count'?" suggestion.
- Habits from other languages (`&&`, `||`, `!`, `'single quotes'`) are
  pointed at the Lumen spelling.
- `1 < x < 3` is a syntax error with the fix spelled out, instead of
  silently meaning something else.
- `break` outside a loop and `return` outside a function are compile-time errors.

Hostile input is contained. Inputs like `"x" * 10**10`, 100,000 levels of
nesting, and runaway recursion all produce ordinary Lumen errors, never a hang
or a Python traceback. The parser and interpreter were fuzzed with 52,000
random and mutated programs without a crash.

## How it works

```
source ─▶ lexer.py ─▶ parser.py ─▶ AST (nodes.py) ─▶ interpreter.py
           tokens      Pratt          dataclasses       tree-walking evaluator
         + newline     parser                           + builtins.py
           flags
```

- **`lexer.py`** records whether a newline came before each token, which is
  how the parser handles semicolon-free code. String interpolations are kept
  as offsets into the original source. The parser parses them in place, so
  errors inside `"{...}"` report true line and column numbers.
- **`parser.py`** is a Pratt parser. It handles operator precedence with
  binding powers, flags unfinished input so the REPL knows to keep reading,
  and catches misplaced `break` and `return` at parse time.
- **`interpreter.py`** dispatches on node type through a dictionary and uses
  a chain of `Env` dictionaries for lexical scope. `return`, `break` and
  `continue` are implemented as exceptions. A call to a function whose
  parameters are all plain names binds them with one `dict(zip(...))`.
- **`errors.py`** renders diagnostics in the style of rustc.

Performance: `fib(25)` makes about 250,000 calls and finishes in roughly 0.5s.

## Project layout

```
lumen/        the implementation
examples/     tour, a self-hosted calculator, Game of Life, data pipelines
tests/        unit, golden-output, CLI/REPL, and resource-limit tests
bin/lumen     run from a checkout without installing
```

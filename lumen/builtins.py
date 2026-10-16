"""The standard library.

Every builtin receives the interpreter and the call-site span first, so
higher-order builtins like `map` can call back into Lumen functions and any
error they raise points at the call that caused it. Thanks to uniform call
syntax, every builtin also works as a method: `xs.map(f)` is `map(xs, f)`.
"""

from __future__ import annotations

import math
import random as _random
import time

from .values import Builtin, Function, brief, equal, is_num, show, to_str, truthy, type_name

REGISTRY: dict[str, Builtin] = {}


class BuiltinError(Exception):
    def __init__(self, message: str, hint: str | None = None, raw: bool = False):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.raw = raw  # if set, the message isn't prefixed with the builtin's name


def builtin(name: str, min_args: int, max_args: int | None | str = "same"):
    def register(fn):
        hi = min_args if max_args == "same" else max_args
        REGISTRY[name] = Builtin(name, fn, min_args, hi)
        return fn
    return register


def install(interp) -> None:
    interp.globals.vars.update(REGISTRY)
    interp.globals.vars["PI"] = math.pi
    interp.globals.vars["E"] = math.e


# --- argument checking ----------------------------------------------------------

def need(value, kinds: tuple, what: str):
    if type(value) not in kinds:
        names = " or ".join(dict.fromkeys(_KIND_NAMES[k] for k in kinds))
        raise BuiltinError(f"{what} must be {names}, not {type_name(value)}")
    return value


_KIND_NAMES = {int: "a number", float: "a number", str: "a string", list: "a list",
               dict: "a map", range: "a range", Function: "a function", Builtin: "a function"}
NUM = (int, float)
FUNC = (Function, Builtin)
SEQ = (list, range, str)


def items_of(value, what: str = "argument") -> list:
    t = type(value)
    if t is list:
        return value
    if t in (range, str):
        return list(value)
    if t is dict:
        return list(value.keys())
    raise BuiltinError(f"{what} must be a list, range, string or map, not {type_name(value)}")


def sort_key(value):
    """Order numbers among numbers and strings among strings; refuse mixtures."""
    if is_num(value):
        return (0, value)
    if type(value) is str:
        return (1, value)
    if type(value) is list:
        return (2, [sort_key(v) for v in value])
    raise BuiltinError(f"can't order values of type {type_name(value)}")


# --- I/O ------------------------------------------------------------------------

@builtin("print", 0, None)
def _print(rt, span, *args):
    rt.out.write(" ".join(to_str(a) for a in args) + "\n")


@builtin("input", 0, 1)
def _input(rt, span, prompt=""):
    try:
        return input(to_str(prompt))
    except EOFError:
        return None


@builtin("clock", 0)
def _clock(rt, span):
    return time.perf_counter()


# --- types & conversion ---------------------------------------------------------

@builtin("type", 1)
def _type(rt, span, v):
    return type_name(v)


@builtin("str", 1)
def _str(rt, span, v):
    return to_str(v)


@builtin("repr", 1)
def _repr(rt, span, v):
    return show(v)


@builtin("int", 1)
def _int(rt, span, v):
    if type(v) is int:
        return v
    if type(v) is float:
        if math.isnan(v) or math.isinf(v):
            raise BuiltinError(f"can't convert {brief(v)} to an int")
        return int(v)
    if type(v) is str:
        try:
            return int(v.strip().replace("_", ""))
        except ValueError:
            raise BuiltinError(f"can't parse {brief(v)} as an int") from None
    raise BuiltinError(f"can't convert {type_name(v)} to an int")


@builtin("float", 1)
def _float(rt, span, v):
    if is_num(v):
        return float(v)
    if type(v) is str:
        try:
            return float(v.strip())
        except ValueError:
            raise BuiltinError(f"can't parse {brief(v)} as a float") from None
    raise BuiltinError(f"can't convert {type_name(v)} to a float")


# --- collections ----------------------------------------------------------------

@builtin("len", 1)
def _len(rt, span, v):
    return len(need(v, (list, str, dict, range), "argument"))


@builtin("list", 1)
def _list(rt, span, v):
    return list(items_of(v))


@builtin("range", 1, 3)
def _range(rt, span, *args):
    for a in args:
        need(a, (int,), "range bounds")
    if len(args) == 3 and args[2] == 0:
        raise BuiltinError("step can't be zero")
    return range(*args)


@builtin("push", 2)
def _push(rt, span, xs, value):
    need(xs, (list,), "first argument").append(value)
    return xs


@builtin("pop", 1)
def _pop(rt, span, xs):
    if not need(xs, (list,), "argument"):
        raise BuiltinError("can't pop from an empty list")
    return xs.pop()


@builtin("insert", 3)
def _insert(rt, span, xs, index, value):
    need(xs, (list,), "first argument").insert(need(index, (int,), "index"), value)
    return xs


@builtin("keys", 1)
def _keys(rt, span, m):
    return list(need(m, (dict,), "argument").keys())


@builtin("values", 1)
def _values(rt, span, m):
    return list(need(m, (dict,), "argument").values())


@builtin("entries", 1)
def _entries(rt, span, m):
    return [[k, v] for k, v in need(m, (dict,), "argument").items()]


@builtin("get", 2, 3)
def _get(rt, span, coll, key, default=None):
    if type(coll) is dict:
        return coll.get(key, default) if type(key) in (str, int, float) else default
    if type(coll) in SEQ and type(key) is int:
        return coll[key] if -len(coll) <= key < len(coll) else default
    raise BuiltinError(f"can't get from {type_name(coll)}")


@builtin("remove", 2)
def _remove(rt, span, m, key):
    if type(m) is dict:
        if key not in m:
            raise BuiltinError(f"key {brief(key)} not found")
        return m.pop(key)
    if type(m) is list:
        need(key, (int,), "index")
        if not -len(m) <= key < len(m):
            raise BuiltinError(f"index {key} out of bounds")
        return m.pop(key)
    raise BuiltinError(f"can't remove from {type_name(m)}")


@builtin("contains", 2)
def _contains(rt, span, coll, item):
    t = type(coll)
    if t is str:
        return need(item, (str,), "second argument") in coll
    if t is dict:
        return type(item) in (str, int, float) and item in coll
    if t is range:
        return type(item) is int and item in coll
    return any(equal(x, item) for x in need(coll, (list,), "first argument"))


@builtin("index_of", 2)
def _index_of(rt, span, coll, item):
    if type(coll) is str:
        i = coll.find(need(item, (str,), "second argument"))
        return None if i < 0 else i
    for i, x in enumerate(items_of(coll)):
        if equal(x, item):
            return i
    return None


@builtin("reverse", 1)
def _reverse(rt, span, v):
    if type(v) is str:
        return v[::-1]
    return items_of(v)[::-1]


@builtin("sort", 1, 2)
def _sort(rt, span, xs, key=None):
    items = items_of(xs)
    if key is not None:
        need(key, FUNC, "key")
    # Compute every key up front (each key function runs exactly once per item).
    keys = [sort_key(x if key is None else rt.call(key, [x], span)) for x in items]
    kinds = {k[0] for k in keys}
    if len(kinds) > 1:
        names = sorted({["number", "string", "list"][k] for k in kinds})
        raise BuiltinError(f"can't compare {' and '.join(names)} values")
    order = sorted(range(len(items)), key=keys.__getitem__)
    return [items[i] for i in order]


@builtin("uniq", 1)
def _uniq(rt, span, xs):
    out: list = []
    for x in items_of(xs):
        if not any(equal(x, y) for y in out):
            out.append(x)
    return out


@builtin("take", 2)
def _take(rt, span, xs, n):
    return items_of(xs)[:max(0, need(n, (int,), "count"))]


@builtin("drop", 2)
def _drop(rt, span, xs, n):
    return items_of(xs)[max(0, need(n, (int,), "count")):]


@builtin("flatten", 1)
def _flatten(rt, span, xs):
    out: list = []
    for x in items_of(xs):
        if type(x) is list:
            out.extend(x)
        else:
            out.append(x)
    return out


@builtin("zip", 2)
def _zip(rt, span, a, b):
    return [[x, y] for x, y in zip(items_of(a), items_of(b))]


@builtin("enumerate", 1)
def _enumerate(rt, span, xs):
    return [[i, x] for i, x in enumerate(items_of(xs))]


@builtin("chunks", 2)
def _chunks(rt, span, xs, size):
    if need(size, (int,), "size") <= 0:
        raise BuiltinError("size must be positive")
    items = items_of(xs)
    return [items[i:i + size] for i in range(0, len(items), size)]


# --- higher-order ---------------------------------------------------------------

@builtin("map", 2)
def _map(rt, span, xs, f):
    need(f, FUNC, "second argument")
    return [rt.call(f, [x], span) for x in items_of(xs, "first argument")]


@builtin("filter", 2)
def _filter(rt, span, xs, f):
    need(f, FUNC, "second argument")
    return [x for x in items_of(xs, "first argument") if truthy(rt.call(f, [x], span))]


@builtin("reject", 2)
def _reject(rt, span, xs, f):
    need(f, FUNC, "second argument")
    return [x for x in items_of(xs, "first argument") if not truthy(rt.call(f, [x], span))]


@builtin("reduce", 3)
def _reduce(rt, span, xs, f, acc):
    need(f, FUNC, "second argument")
    for x in items_of(xs, "first argument"):
        acc = rt.call(f, [acc, x], span)
    return acc


@builtin("each", 2)
def _each(rt, span, xs, f):
    need(f, FUNC, "second argument")
    for x in items_of(xs, "first argument"):
        rt.call(f, [x], span)


@builtin("find", 2)
def _find(rt, span, xs, f):
    need(f, FUNC, "second argument")
    for x in items_of(xs, "first argument"):
        if truthy(rt.call(f, [x], span)):
            return x
    return None


@builtin("any", 1, 2)
def _any(rt, span, xs, f=None):
    items = items_of(xs)
    return any(truthy(rt.call(f, [x], span) if f else x) for x in items)


@builtin("all", 1, 2)
def _all(rt, span, xs, f=None):
    items = items_of(xs)
    return all(truthy(rt.call(f, [x], span) if f else x) for x in items)


@builtin("count", 2)
def _count(rt, span, xs, f):
    need(f, FUNC, "second argument")
    return sum(1 for x in items_of(xs) if truthy(rt.call(f, [x], span)))


@builtin("group_by", 2)
def _group_by(rt, span, xs, f):
    need(f, FUNC, "second argument")
    groups: dict = {}
    for x in items_of(xs):
        key = rt.call(f, [x], span)
        if type(key) not in (str, int, float):
            raise BuiltinError(f"group key must be a string or number, not {type_name(key)}")
        groups.setdefault(key, []).append(x)
    return groups


@builtin("tally", 1)
def _tally(rt, span, xs):
    counts: dict = {}
    for x in items_of(xs):
        if type(x) not in (str, int, float):
            raise BuiltinError(f"can only tally strings and numbers, not {type_name(x)}")
        counts[x] = counts.get(x, 0) + 1
    return counts


# --- numbers --------------------------------------------------------------------

def _numbers(args, fname):
    values = items_of(args[0]) if len(args) == 1 else list(args)
    for v in values:
        if not is_num(v):
            raise BuiltinError(f"expected numbers, found {type_name(v)}")
    return values


@builtin("sum", 1)
def _sum(rt, span, xs):
    return sum(_numbers([xs], "sum"))


@builtin("min", 1, None)
def _min(rt, span, *args):
    values = _numbers(args, "min")
    if not values:
        raise BuiltinError("min of an empty list")
    return min(values)


@builtin("max", 1, None)
def _max(rt, span, *args):
    values = _numbers(args, "max")
    if not values:
        raise BuiltinError("max of an empty list")
    return max(values)


@builtin("abs", 1)
def _abs(rt, span, x):
    return abs(need(x, NUM, "argument"))


@builtin("sqrt", 1)
def _sqrt(rt, span, x):
    if need(x, NUM, "argument") < 0:
        raise BuiltinError("square root of a negative number")
    return math.sqrt(x)


@builtin("floor", 1)
def _floor(rt, span, x):
    return math.floor(need(x, NUM, "argument"))


@builtin("ceil", 1)
def _ceil(rt, span, x):
    return math.ceil(need(x, NUM, "argument"))


@builtin("round", 1, 2)
def _round(rt, span, x, digits=None):
    need(x, NUM, "argument")
    if digits is None:
        return round(x)
    return round(x, need(digits, (int,), "digits"))


@builtin("random", 0, 2)
def _random_(rt, span, lo=None, hi=None):
    """random() -> float in [0, 1); random(n) -> int in [0, n); random(a, b) -> int in [a, b]."""
    if lo is None:
        return _random.random()
    if hi is None:
        if need(lo, (int,), "argument") <= 0:
            raise BuiltinError("argument must be positive")
        return _random.randrange(lo)
    return _random.randint(need(lo, (int,), "lower bound"), need(hi, (int,), "upper bound"))


@builtin("seed", 1)
def _seed(rt, span, n):
    _random.seed(n)


# --- strings --------------------------------------------------------------------

@builtin("join", 1, 2)
def _join(rt, span, xs, sep=""):
    return need(sep, (str,), "separator").join(to_str(x) for x in items_of(xs))


@builtin("split", 1, 2)
def _split(rt, span, s, sep=None):
    need(s, (str,), "first argument")
    if sep is None:
        return s.split()
    if need(sep, (str,), "separator") == "":
        return list(s)
    return s.split(sep)


@builtin("lines", 1)
def _lines(rt, span, s):
    return need(s, (str,), "argument").splitlines()


@builtin("chars", 1)
def _chars(rt, span, s):
    return list(need(s, (str,), "argument"))


@builtin("trim", 1)
def _trim(rt, span, s):
    return need(s, (str,), "argument").strip()


@builtin("upper", 1)
def _upper(rt, span, s):
    return need(s, (str,), "argument").upper()


@builtin("lower", 1)
def _lower(rt, span, s):
    return need(s, (str,), "argument").lower()


@builtin("replace", 3)
def _replace(rt, span, s, old, new):
    return need(s, (str,), "first argument").replace(need(old, (str,), "pattern"), need(new, (str,), "replacement"))


@builtin("starts_with", 2)
def _starts_with(rt, span, s, prefix):
    return need(s, (str,), "first argument").startswith(need(prefix, (str,), "prefix"))


@builtin("ends_with", 2)
def _ends_with(rt, span, s, suffix):
    return need(s, (str,), "first argument").endswith(need(suffix, (str,), "suffix"))


@builtin("pad_left", 2, 3)
def _pad_left(rt, span, s, width, fill=" "):
    return to_str(s).rjust(need(width, (int,), "width"), _fill(fill))


@builtin("pad_right", 2, 3)
def _pad_right(rt, span, s, width, fill=" "):
    return to_str(s).ljust(need(width, (int,), "width"), _fill(fill))


def _fill(fill):
    if type(fill) is not str or len(fill) != 1:
        raise BuiltinError("fill must be a single character")
    return fill


@builtin("ord", 1)
def _ord(rt, span, s):
    if type(s) is not str or len(s) != 1:
        raise BuiltinError("argument must be a single character")
    return ord(s)


@builtin("chr", 1)
def _chr(rt, span, n):
    try:
        return chr(need(n, (int,), "argument"))
    except (ValueError, OverflowError):
        raise BuiltinError(f"{n} is not a valid code point") from None


@builtin("is_digit", 1)
def _is_digit(rt, span, s):
    return need(s, (str,), "argument") != "" and all(c in "0123456789" for c in s)


@builtin("is_alpha", 1)
def _is_alpha(rt, span, s):
    return need(s, (str,), "argument").isalpha()


# --- errors ---------------------------------------------------------------------

@builtin("error", 1)
def _error(rt, span, message):
    raise BuiltinError(to_str(message), raw=True)


@builtin("assert", 1, 2)
def _assert(rt, span, cond, message=None):
    if not truthy(cond):
        raise BuiltinError("assertion failed" + (f": {to_str(message)}" if message is not None else ""), raw=True)

"""Runtime values and the operations every part of the interpreter shares.

Lumen values map directly onto Python objects:

    nil -> None     bool -> bool     int/float -> int/float
    string -> str   list -> list     map -> dict     range -> range
    function -> Function | Builtin
"""

from __future__ import annotations

from typing import Callable

from .nodes import PBind


class Function:
    __slots__ = ("name", "params", "body", "closure", "simple")

    def __init__(self, name, params, body, closure):
        self.name = name
        self.params = params  # list of patterns
        self.body = body
        self.closure = closure
        # Fast path: when every parameter is a plain name, calls bind with a dict(zip()).
        self.simple = [p.name for p in params] if all(type(p) is PBind for p in params) else None

    def describe(self) -> str:
        return f"function '{self.name}'" if self.name else "anonymous function"


class Builtin:
    __slots__ = ("name", "fn", "min_args", "max_args")

    def __init__(self, name: str, fn: Callable, min_args: int, max_args: int | None):
        self.name = name
        self.fn = fn
        self.min_args = min_args
        self.max_args = max_args  # None means variadic

    def describe(self) -> str:
        return f"{self.name}()"


def is_num(v) -> bool:
    # `type(...) in` rather than isinstance: bool is a subclass of int in Python.
    return type(v) in (int, float)


def truthy(v) -> bool:
    return v is not None and v is not False


def type_name(v) -> str:
    if v is None:
        return "nil"
    t = type(v)
    return {
        bool: "bool", int: "int", float: "float", str: "string",
        list: "list", dict: "map", range: "range",
        Function: "function", Builtin: "function",
    }.get(t, t.__name__)


def equal(a, b) -> bool:
    ta, tb = type(a), type(b)
    if ta is bool or tb is bool:
        return ta is tb and a == b
    if is_num(a) and is_num(b):
        return a == b
    if ta is not tb:
        return False
    if ta is list:
        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
    if ta is dict:
        return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
    return a == b


def to_str(v) -> str:
    """How a value prints: strings bare, everything else as its repr."""
    return v if type(v) is str else show(v)


def show(v, _seen: set[int] | None = None) -> str:
    """Source-like representation; strings are quoted. Cycle-safe."""
    if v is None:
        return "nil"
    if v is True:
        return "true"
    if v is False:
        return "false"
    t = type(v)
    if t is int:
        return str(v)
    if t is float:
        if v != v:
            return "nan"
        if v in (float("inf"), float("-inf")):
            return "inf" if v > 0 else "-inf"
        return repr(v)
    if t is str:
        return quote(v)
    if t is range:
        if v.step == 1:
            return f"{v.start}..{v.stop}"
        return f"range({v.start}, {v.stop}, {v.step})"
    if t is Function:
        return f"<fn {v.name or 'anonymous'}>"
    if t is Builtin:
        return f"<builtin {v.name}>"
    if t is list or t is dict:
        seen = _seen if _seen is not None else set()
        if id(v) in seen:
            return "[...]" if t is list else "{...}"
        seen.add(id(v))
        try:
            if t is list:
                return "[" + ", ".join(show(x, seen) for x in v) + "]"
            return "{" + ", ".join(f"{show(k, seen)}: {show(x, seen)}" for k, x in v.items()) + "}"
        finally:
            seen.discard(id(v))
    return repr(v)


_QUOTE_ESCAPES = {"\n": "\\n", "\t": "\\t", "\r": "\\r", "\0": "\\0",
                  "\\": "\\\\", '"': '\\"', "{": "\\{", "}": "\\}"}


def brief(v, limit: int = 60) -> str:
    """`show(v)` cut down to size, for quoting values inside error messages."""
    text = show(v)
    return text if len(text) <= limit else text[:limit - 3] + "..."


def quote(s: str) -> str:
    return '"' + "".join(_QUOTE_ESCAPES.get(c, c) for c in s) + '"'

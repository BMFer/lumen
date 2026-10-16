"""Tree-walking evaluator.

Scoping is lexical: each block, loop iteration, match arm and call gets a fresh
`Env` whose parent is the enclosing scope. A per-iteration scope means
closures created inside a loop capture that iteration's variables, not the
last value the loop variable held.
"""

from __future__ import annotations

import difflib
import operator
import sys

from .errors import LumenError, LumenRuntimeError, LumenSyntaxError, Source, Span
from .nodes import (
    Assign, Binary, Block, Break, Call, Continue, FnExpr, For, If, Index, Interp,
    Let, ListLit, Literal, Logical, MapLit, Match, Member, Node, Pattern, PBind,
    PList, PLit, PMap, POr, PRange, PWild, Range, Return, Unary, Var, While,
)
from .parser import Parser
from .values import Builtin, Function, brief, equal, is_num, show, to_str, truthy, type_name

MAX_CALL_DEPTH = 1500
MAX_REPEAT_SIZE = 50_000_000  # elements/characters produced by `seq * n`

_MISSING = object()

_NUMERIC = {
    "+": operator.add, "-": operator.sub, "*": operator.mul,
    "/": operator.truediv, "//": operator.floordiv, "%": operator.mod,
    "**": operator.pow,
    "<": operator.lt, "<=": operator.le, ">": operator.gt, ">=": operator.ge,
}
_ORDERING = {"<", "<=", ">", ">="}


class ReturnSignal(Exception):
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value


class BreakSignal(Exception):
    pass


class ContinueSignal(Exception):
    pass


class Env:
    __slots__ = ("vars", "parent")

    def __init__(self, parent: Env | None = None, vars: dict | None = None):
        self.vars = {} if vars is None else vars
        self.parent = parent

    def lookup(self, name: str):
        env = self
        while env is not None:
            value = env.vars.get(name, _MISSING)
            if value is not _MISSING:
                return value
            env = env.parent
        return _MISSING

    def assign(self, name: str, value) -> bool:
        env = self
        while env is not None:
            if name in env.vars:
                env.vars[name] = value
                return True
            env = env.parent
        return False

    def visible_names(self) -> set[str]:
        names: set[str] = set()
        env = self
        while env is not None:
            names.update(env.vars)
            env = env.parent
        return names


def error(message: str, span: Span | None, hint: str | None = None) -> LumenRuntimeError:
    return LumenRuntimeError(message, span, hint)


class Interpreter:
    def __init__(self, out=None):
        from .builtins import install

        self.out = out if out is not None else sys.stdout
        # Lumen ints are arbitrary precision; lift CPython's int<->str digit cap (3.11+).
        if hasattr(sys, "set_int_max_str_digits"):
            sys.set_int_max_str_digits(0)
        self.globals = Env()
        self.frames: list[tuple[str, Span]] = []
        install(self)
        self._dispatch = {
            Literal: self.eval_literal, Interp: self.eval_interp, Var: self.eval_var,
            ListLit: self.eval_list, MapLit: self.eval_map, Unary: self.eval_unary,
            Binary: self.eval_binary, Logical: self.eval_logical, Range: self.eval_range,
            Call: self.eval_call, Index: self.eval_index, Member: self.eval_member,
            Assign: self.eval_assign, FnExpr: self.eval_fn, If: self.eval_if,
            Match: self.eval_match, Block: self.eval_block, Let: self.exec_let,
            While: self.exec_while, For: self.exec_for, Return: self.exec_return,
            Break: self.exec_break, Continue: self.exec_continue,
        }

    # --- entry points -----------------------------------------------------------

    def run(self, text: str, name: str = "<input>"):
        """Parse and execute a program in the global scope; return the last value."""
        return self.execute(parse_program(Source(text, name)))

    def execute(self, program: Block):
        limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(limit, 60_000))
        try:
            return self.exec_stmts(program.stmts, self.globals)
        except RecursionError:
            raise error("stack overflow: expression nested too deeply", None) from None
        finally:
            self.frames.clear()
            sys.setrecursionlimit(limit)

    def eval(self, node: Node, env: Env):
        return self._dispatch[node.__class__](node, env)

    def exec_stmts(self, stmts: list[Node], env: Env):
        result = None
        for stmt in stmts:
            result = self.eval(stmt, env)
        return result

    # --- calls ------------------------------------------------------------------

    def call(self, fn, args: list, span: Span):
        if type(fn) is Function:
            if len(args) != len(fn.params):
                n = len(fn.params)
                raise error(f"{fn.describe()} takes {n} argument{'s' * (n != 1)}, but got {len(args)}", span)
            if len(self.frames) >= MAX_CALL_DEPTH:
                raise error(f"stack overflow: more than {MAX_CALL_DEPTH} nested calls", span,
                            hint="check that the recursion has a base case that is reached")
            self.frames.append((fn.name or "anonymous function", span))
            try:
                if fn.simple is not None:
                    env = Env(fn.closure, dict(zip(fn.simple, args)))
                else:
                    env = Env(fn.closure)
                    for pattern, arg in zip(fn.params, args):
                        self.bind(pattern, arg, env, pattern.span)
                body = fn.body
                if type(body) is Block:
                    return self.exec_stmts(body.stmts, env)
                return self.eval(body, env)
            except ReturnSignal as ret:
                return ret.value
            except LumenRuntimeError as e:
                if e.trace is None:
                    e.trace = list(self.frames)
                raise
            finally:
                self.frames.pop()

        if type(fn) is Builtin:
            n = len(args)
            if n < fn.min_args or (fn.max_args is not None and n > fn.max_args):
                if fn.max_args is None:
                    want = f"at least {fn.min_args}"
                elif fn.min_args == fn.max_args:
                    want = str(fn.min_args)
                else:
                    want = f"{fn.min_args} to {fn.max_args}"
                raise error(f"{fn.name}() takes {want} argument{'s' * (want != '1')}, but got {n}", span)
            from .builtins import BuiltinError
            try:
                return fn.fn(self, span, *args)
            except BuiltinError as e:
                raise error(e.message if e.raw else f"{fn.name}(): {e.message}", span, e.hint) from None

        hint = None
        if type(fn) is dict:
            hint = "to call a function stored in a map, use map.key(...)"
        raise error(f"{type_name(fn)} is not callable", span, hint)

    def eval_call(self, node: Call, env: Env):
        callee = node.callee
        if type(callee) is Member:
            # Uniform call syntax: `x.f(a)` calls the map field `f` if x is a map
            # that has one, otherwise the function `f` in scope as `f(x, a)`.
            obj = self.eval(callee.obj, env)
            name = callee.name
            if type(obj) is dict and name in obj:
                fn = obj[name]
                args = [self.eval(a, env) for a in node.args]
            else:
                fn = env.lookup(name)
                if fn is _MISSING or type(fn) not in (Function, Builtin):
                    hint = self.suggest(name, env)
                    raise error(f"{type_name(obj)} has no method or field '{name}'",
                                callee.name_span, hint)
                args = [obj, *(self.eval(a, env) for a in node.args)]
        else:
            fn = self.eval(callee, env)
            args = [self.eval(a, env) for a in node.args]
        return self.call(fn, args, node.span)

    # --- expressions ------------------------------------------------------------

    def eval_literal(self, node: Literal, env: Env):
        return node.value

    def eval_interp(self, node: Interp, env: Env):
        return "".join(to_str(self.eval(p, env)) for p in node.parts)

    def eval_var(self, node: Var, env: Env):
        value = env.lookup(node.name)
        if value is _MISSING:
            raise error(f"undefined variable '{node.name}'", node.span, self.suggest(node.name, env))
        return value

    def suggest(self, name: str, env: Env) -> str | None:
        close = difflib.get_close_matches(name, env.visible_names(), n=1, cutoff=0.7)
        return f"did you mean '{close[0]}'?" if close else None

    def eval_list(self, node: ListLit, env: Env):
        return [self.eval(item, env) for item in node.items]

    def eval_map(self, node: MapLit, env: Env):
        result = {}
        for key_node, value_node in node.entries:
            key = self.eval(key_node, env)
            check_key(key, key_node.span)
            result[key] = self.eval(value_node, env)
        return result

    def eval_unary(self, node: Unary, env: Env):
        value = self.eval(node.operand, env)
        if node.op == "not":
            return not truthy(value)
        if is_num(value):
            return -value
        raise error(f"can't negate {type_name(value)}", node.span)

    def eval_binary(self, node: Binary, env: Env):
        left = self.eval(node.left, env)
        right = self.eval(node.right, env)
        return self.binop(node.op, left, right, node.span)

    def binop(self, op: str, left, right, span: Span):
        if op == "==":
            return equal(left, right)
        if op == "!=":
            return not equal(left, right)

        if is_num(left) and is_num(right):
            if op == "**" and type(left) is int and type(right) is int and right > 10_000 and abs(left) > 1:
                raise error("number too large", span)
            try:
                result = _NUMERIC[op](left, right)
            except ZeroDivisionError:
                raise error("division by zero", span) from None
            except OverflowError:
                raise error("numeric overflow", span) from None
            if type(result) is complex:
                raise error("result is not a real number", span)
            return result

        tl, tr = type(left), type(right)
        if op == "+":
            if tl is tr and tl in (str, list):
                return left + right
            if str in (tl, tr):
                other = right if tl is str else left
                raise error(f"can't add string and {type_name(other)}", span,
                            hint='convert with str(x), or interpolate: "total: {x}"')
        elif op == "*":
            if (tl in (str, list) and tr is int) or (tl is int and tr in (str, list)):
                seq, n = (left, right) if tr is int else (right, left)
                if len(seq) * n > MAX_REPEAT_SIZE:
                    raise error(f"result too large ({len(seq)} x {n} elements)", span)
                return left * right
        elif op in _ORDERING and tl is str and tr is str:
            return _NUMERIC[op](left, right)

        raise error(f"unsupported operand types for '{op}': {type_name(left)} and {type_name(right)}", span)

    def eval_logical(self, node: Logical, env: Env):
        left = self.eval(node.left, env)
        if node.op == "and":
            return self.eval(node.right, env) if truthy(left) else left
        return left if truthy(left) else self.eval(node.right, env)

    def eval_range(self, node: Range, env: Env):
        start = self.eval(node.start, env)
        end = self.eval(node.end, env)
        if type(start) is not int or type(end) is not int:
            raise error(f"range bounds must be integers, not {type_name(start)} and {type_name(end)}", node.span)
        return range(start, end + 1 if node.inclusive else end)

    def eval_index(self, node: Index, env: Env):
        obj = self.eval(node.obj, env)
        key = self.eval(node.index, env)
        return index_get(obj, key, node.span)

    def eval_member(self, node: Member, env: Env):
        obj = self.eval(node.obj, env)
        if type(obj) is dict:
            if node.name in obj:
                return obj[node.name]
            raise error(f"map has no field '{node.name}'", node.name_span,
                        hint=f'use get(m, "{node.name}", default) if the field is optional')
        raise error(f"{type_name(obj)} has no field '{node.name}'", node.name_span)

    def eval_assign(self, node: Assign, env: Env):
        target = node.target

        if type(target) is Var:
            if node.op is None:
                value = self.eval(node.value, env)
            else:
                value = self.binop(node.op, self.eval_var(target, env), self.eval(node.value, env), node.span)
            if not env.assign(target.name, value):
                raise error(f"undefined variable '{target.name}'", target.span,
                            hint=f"declare it first with 'let {target.name} = ...'")
            return value

        if type(target) is Index:
            obj = self.eval(target.obj, env)
            key = self.eval(target.index, env)
            span = target.span
        else:
            obj = self.eval(target.obj, env)
            key = target.name
            span = target.name_span
            if type(obj) is not dict:
                raise error(f"{type_name(obj)} has no field '{key}'", span)

        if node.op is None:
            value = self.eval(node.value, env)
        else:
            value = self.binop(node.op, index_get(obj, key, span), self.eval(node.value, env), node.span)
        index_set(obj, key, value, span)
        return value

    def eval_fn(self, node: FnExpr, env: Env):
        return Function(node.name, node.params, node.body, env)

    def eval_if(self, node: If, env: Env):
        if truthy(self.eval(node.cond, env)):
            return self.eval_block(node.then, env)
        if node.else_ is not None:
            return self.eval(node.else_, env)
        return None

    def eval_block(self, node: Block, env: Env):
        return self.exec_stmts(node.stmts, Env(env))

    def eval_match(self, node: Match, env: Env):
        value = self.eval(node.subject, env)
        for arm in node.arms:
            bindings: dict = {}
            if not self.match_pattern(arm.pattern, value, bindings):
                continue
            scope = Env(env, bindings)
            if arm.guard is not None and not truthy(self.eval(arm.guard, scope)):
                continue
            return self.eval(arm.body, scope)
        raise error(f"no match arm matched {brief(value)}", node.subject.span,
                    hint="add a catch-all arm: `_ => ...`")

    def match_pattern(self, pat: Pattern, value, binds: dict) -> bool:
        t = type(pat)
        if t is PBind:
            binds[pat.name] = value
            return True
        if t is PWild:
            return True
        if t is PLit:
            return equal(pat.value, value)
        if t is PRange:
            if not is_num(value):
                return False
            return pat.lo <= value <= pat.hi if pat.inclusive else pat.lo <= value < pat.hi
        if t is PList:
            if type(value) is not list:
                return False
            nb, na = len(pat.before), len(pat.after)
            if len(value) < nb + na or (not pat.has_rest and len(value) != nb):
                return False
            for p, v in zip(pat.before, value):
                if not self.match_pattern(p, v, binds):
                    return False
            tail_start = len(value) - na
            for p, v in zip(pat.after, value[tail_start:]):
                if not self.match_pattern(p, v, binds):
                    return False
            if pat.rest is not None:
                binds[pat.rest] = value[nb:tail_start]
            return True
        if t is PMap:
            if type(value) is not dict:
                return False
            for key, p in pat.entries:
                if key not in value or not self.match_pattern(p, value[key], binds):
                    return False
            return True
        if t is POr:
            return any(self.match_pattern(alt, value, binds) for alt in pat.alts)
        raise AssertionError(f"unknown pattern {pat!r}")

    def bind(self, pat: Pattern, value, env: Env, span: Span) -> None:
        if type(pat) is PBind:
            env.vars[pat.name] = value
            return
        binds: dict = {}
        if not self.match_pattern(pat, value, binds):
            raise error(f"pattern doesn't match {brief(value)}", span)
        env.vars.update(binds)

    # --- statements -------------------------------------------------------------

    def exec_let(self, node: Let, env: Env):
        self.bind(node.pattern, self.eval(node.value, env), env, node.pattern.span)
        return None

    def exec_while(self, node: While, env: Env):
        body = node.body.stmts
        while truthy(self.eval(node.cond, env)):
            try:
                self.exec_stmts(body, Env(env))
            except BreakSignal:
                break
            except ContinueSignal:
                continue
        return None

    def exec_for(self, node: For, env: Env):
        iterable = self.eval(node.iterable, env)
        t = type(iterable)
        if t is list:
            items = list(iterable)  # snapshot: mutating the list inside the loop is safe
        elif t is dict:
            items = list(iterable.keys())
        elif t in (range, str):
            items = iterable
        else:
            raise error(f"can't iterate over {type_name(iterable)}", node.iterable.span)

        body = node.body.stmts
        pattern = node.pattern
        for item in items:
            scope = Env(env)
            self.bind(pattern, item, scope, pattern.span)
            try:
                self.exec_stmts(body, scope)
            except BreakSignal:
                break
            except ContinueSignal:
                continue
        return None

    def exec_return(self, node: Return, env: Env):
        raise ReturnSignal(None if node.value is None else self.eval(node.value, env))

    def exec_break(self, node: Break, env: Env):
        raise BreakSignal()

    def exec_continue(self, node: Continue, env: Env):
        raise ContinueSignal()


def parse_program(source: Source) -> Block:
    """Parse, turning Python recursion exhaustion into a Lumen syntax error."""
    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(max(limit, 60_000))
    try:
        return Parser(source).parse_program()
    except RecursionError:
        raise LumenSyntaxError("expression nested too deeply", Span(0, 0, source)) from None
    finally:
        sys.setrecursionlimit(limit)


# --- indexing -------------------------------------------------------------------

def check_key(key, span: Span) -> None:
    if type(key) not in (str, int, float):
        raise error(f"map keys must be strings or numbers, not {type_name(key)}", span)


def index_get(obj, key, span: Span):
    t = type(obj)
    if t in (list, str, range):
        if type(key) is int:
            n = len(obj)
            if -n <= key < n:
                return obj[key]
            raise error(f"index {key} is out of bounds for a {type_name(obj)} of length {n}", span)
        if type(key) is range:
            return obj[key.start:key.stop:key.step]
        raise error(f"{type_name(obj)} indices must be integers or ranges, not {type_name(key)}", span)
    if t is dict:
        if type(key) not in (str, int, float):
            raise error(f"map keys must be strings or numbers, not {type_name(key)}", span)
        if key in obj:
            return obj[key]
        raise error(f"key {brief(key)} not found in map", span,
                    hint="use get(m, key, default) if the key is optional")
    raise error(f"can't index into {type_name(obj)}", span)


def index_set(obj, key, value, span: Span) -> None:
    t = type(obj)
    if t is list:
        if type(key) is not int:
            raise error(f"list indices must be integers, not {type_name(key)}", span)
        n = len(obj)
        if not -n <= key < n:
            raise error(f"index {key} is out of bounds for a list of length {n}", span,
                        hint="use push(xs, value) to append")
        obj[key] = value
    elif t is dict:
        check_key(key, span)
        obj[key] = value
    elif t is str:
        raise error("strings are immutable", span)
    else:
        raise error(f"can't assign into {type_name(obj)}", span)


__all__ = ["Interpreter", "Env", "LumenError"]

"""AST node definitions.

Lumen is expression-oriented: `if`, `match` and blocks all produce values.
`let`, `while`, `for`, `return`, `break` and `continue` are statements, which
may only appear directly inside a block or at the top level.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import Span

node = dataclass(slots=True, eq=False)


@node
class Node:
    span: Span


# --- expressions ---------------------------------------------------------------

@node
class Literal(Node):
    value: object


@node
class Interp(Node):
    """A string with `{expr}` interpolations; parts are Literal or expressions."""
    parts: list[Node]


@node
class Var(Node):
    name: str


@node
class ListLit(Node):
    items: list[Node]


@node
class MapLit(Node):
    entries: list[tuple[Node, Node]]


@node
class Unary(Node):
    op: str
    operand: Node


@node
class Binary(Node):
    op: str
    left: Node
    right: Node


@node
class Logical(Node):
    op: str  # 'and' | 'or'
    left: Node
    right: Node


@node
class Range(Node):
    start: Node
    end: Node
    inclusive: bool


@node
class Call(Node):
    callee: Node
    args: list[Node]


@node
class Index(Node):
    obj: Node
    index: Node


@node
class Member(Node):
    obj: Node
    name: str
    name_span: Span


@node
class Assign(Node):
    target: Node      # Var | Index | Member
    op: str | None    # None for '=', '+' for '+=', ...
    value: Node


@node
class FnExpr(Node):
    name: str | None
    params: list[Pattern]  # usually PBind, but `fn([a, b]) => a + b` destructures
    body: Node             # Block, or a bare expression for `fn(x) => x`


@node
class If(Node):
    cond: Node
    then: Block
    else_: Node | None  # Block | If | None


@node
class MatchArm(Node):
    pattern: Pattern
    guard: Node | None
    body: Node


@node
class Match(Node):
    subject: Node
    arms: list[MatchArm]


@node
class Block(Node):
    stmts: list[Node]


# --- statements ----------------------------------------------------------------

@node
class Let(Node):
    pattern: Pattern
    value: Node


@node
class While(Node):
    cond: Node
    body: Block


@node
class For(Node):
    pattern: Pattern
    iterable: Node
    body: Block


@node
class Return(Node):
    value: Node | None


@node
class Break(Node):
    pass


@node
class Continue(Node):
    pass


# --- patterns ------------------------------------------------------------------

@node
class Pattern(Node):
    pass


@node
class PWild(Pattern):
    pass


@node
class PBind(Pattern):
    name: str


@node
class PLit(Pattern):
    value: object


@node
class PRange(Pattern):
    lo: int | float
    hi: int | float
    inclusive: bool


@node
class PList(Pattern):
    before: list[Pattern]
    after: list[Pattern]     # elements after a `..rest`
    has_rest: bool
    rest: str | None         # name bound to the middle slice, if any


@node
class PMap(Pattern):
    entries: list[tuple[str, Pattern]]


@node
class POr(Pattern):
    alts: list[Pattern]


def pattern_names(p: Pattern) -> set[str]:
    """Names a pattern binds."""
    if isinstance(p, PBind):
        return {p.name}
    if isinstance(p, PList):
        names = set().union(*(pattern_names(q) for q in p.before + p.after))
        return names | ({p.rest} if p.rest else set())
    if isinstance(p, PMap):
        return set().union(*(pattern_names(q) for _, q in p.entries))
    if isinstance(p, POr):
        return set().union(*(pattern_names(q) for q in p.alts))
    return set()

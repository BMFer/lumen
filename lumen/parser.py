"""Pratt parser producing the AST in `nodes`.

Statement boundaries: Lumen needs no semicolons. A statement ends at a
newline, unless the expression is visibly unfinished (inside parentheses,
brackets or a map literal) or the next line starts with `|>` or `.`, which
lets pipelines and method chains flow over several lines:

    let total = orders
      |> filter(fn(o) => o.paid)
      |> map(fn(o) => o.amount)
      |> sum
"""

from __future__ import annotations

from .errors import LumenSyntaxError, Source, Span
from .lexer import Lexer, Token
from .nodes import (
    Assign, Binary, Block, Break, Call, Continue, FnExpr, For, If, Index, Interp,
    Let, ListLit, Literal, Logical, MapLit, Match, MatchArm, Member, Node, Pattern,
    PBind, PList, PLit, PMap, POr, PRange, PWild, Range, Return, Unary, Var, While,
    pattern_names,
)

# Binding powers (higher binds tighter).
ASSIGN_OPS = {"=", "+=", "-=", "*=", "/="}
COMPARISONS = {"==", "!=", "<", "<=", ">", ">="}
INFIX_BP = {
    **{op: 1 for op in ASSIGN_OPS},
    "|>": 2,
    "or": 3,
    "and": 4,
    **{op: 6 for op in COMPARISONS},
    "..": 7, "..=": 7,
    "+": 8, "-": 8,
    "*": 9, "/": 9, "//": 9, "%": 9,
    "**": 11,
    "(": 12, "[": 12, ".": 12,
}
NOT_BP = 5       # `not a == b` is `not (a == b)`
UNARY_BP = 10    # `-x ** 2` is `-(x ** 2)`
CONTINUES_LINE = {"|>", "."}


def describe(tok: Token) -> str:
    if tok.kind == "eof":
        return "end of input"
    if tok.kind == "str":
        return "a string"
    if tok.kind == "num":
        return f"number {tok.value!r}"
    if tok.kind == "ident":
        return f"'{tok.value}'"
    return f"'{tok.kind}'"


def parse(text: str, name: str = "<input>") -> Block:
    return Parser(Source(text, name)).parse_program()


class Parser:
    def __init__(self, source: Source, start: int = 0, end: int | None = None):
        self.source = source
        self.toks = Lexer(source, start, end).tokenize()
        self.i = 0
        self.depth = 0       # > 0 inside (), [] or a map literal: newlines don't end anything
        self.loop_depth = 0
        self.fn_depth = 0

    # --- token helpers ----------------------------------------------------------

    def peek(self, ahead: int = 0) -> Token:
        return self.toks[min(self.i + ahead, len(self.toks) - 1)]

    def advance(self) -> Token:
        tok = self.toks[self.i]
        if tok.kind != "eof":
            self.i += 1
        return tok

    def check(self, kind: str) -> bool:
        return self.toks[self.i].kind == kind

    def match(self, kind: str) -> Token | None:
        return self.advance() if self.check(kind) else None

    def expect(self, kind: str, what: str) -> Token:
        if self.check(kind):
            return self.advance()
        tok = self.peek()
        raise self.error(f"expected {what}, found {describe(tok)}", tok)

    def error(self, message: str, tok: Token, hint: str | None = None) -> LumenSyntaxError:
        return LumenSyntaxError(message, tok.span, hint, incomplete=tok.kind == "eof")

    # --- statements -------------------------------------------------------------

    def parse_program(self) -> Block:
        stmts = []
        while not self.check("eof"):
            stmts.append(self.statement())
            self.end_statement()
        return Block(Span(0, len(self.source.text), self.source), stmts)

    def end_statement(self) -> None:
        if self.match(";"):
            return
        tok = self.peek()
        if tok.kind in ("}", "eof") or tok.nl_before:
            return
        raise self.error(f"expected end of statement, found {describe(tok)}", tok,
                         hint="put each statement on its own line, or separate them with ';'")

    def block(self) -> Block:
        open_tok = self.expect("{", "'{'")
        saved, self.depth = self.depth, 0
        stmts = []
        while not self.check("}"):
            if self.check("eof"):
                line, _ = self.source.line_col(open_tok.span.start)
                raise self.error(f"expected '}}' to close the block opened on line {line}", self.peek())
            stmts.append(self.statement())
            self.end_statement()
        close = self.advance()
        self.depth = saved
        return Block(open_tok.span.to(close.span), stmts)

    def statement(self) -> Node:
        tok = self.peek()
        kind = tok.kind

        if kind == "let":
            self.advance()
            pattern = self.pattern()
            self.expect("=", "'=' after the name in 'let'")
            value = self.expression()
            if isinstance(pattern, PBind) and isinstance(value, FnExpr) and value.name is None:
                value.name = pattern.name
            return Let(tok.span.to(value.span), pattern, value)

        if kind == "fn" and self.peek(1).kind == "ident":
            self.advance()
            name = self.advance()
            fn = self.function_rest(tok, name.value)
            return Let(tok.span.to(fn.span), PBind(name.span, name.value), fn)

        if kind == "return":
            self.advance()
            if not self.fn_depth:
                raise self.error("'return' outside of a function", tok)
            nxt = self.peek()
            if nxt.nl_before or nxt.kind in ("}", ";", "eof"):
                return Return(tok.span, None)
            value = self.expression()
            return Return(tok.span.to(value.span), value)

        if kind in ("break", "continue"):
            self.advance()
            if not self.loop_depth:
                raise self.error(f"'{kind}' outside of a loop", tok)
            return Break(tok.span) if kind == "break" else Continue(tok.span)

        if kind == "while":
            self.advance()
            cond = self.expression()
            body = self.loop_body()
            return While(tok.span.to(body.span), cond, body)

        if kind == "for":
            self.advance()
            pattern = self.pattern()
            self.expect("in", "'in' after the loop variable")
            iterable = self.expression()
            body = self.loop_body()
            return For(tok.span.to(body.span), pattern, iterable, body)

        return self.expression()

    def loop_body(self) -> Block:
        self.loop_depth += 1
        try:
            return self.block()
        finally:
            self.loop_depth -= 1

    # --- expressions ------------------------------------------------------------

    def expression(self, min_bp: int = 0) -> Node:
        left = self.prefix(self.advance())
        while True:
            tok = self.peek()
            lbp = INFIX_BP.get(tok.kind)
            if lbp is None or lbp <= min_bp:
                break
            if tok.nl_before and self.depth == 0 and tok.kind not in CONTINUES_LINE:
                break
            self.advance()
            left = self.infix(tok, left, lbp)
        return left

    def prefix(self, tok: Token) -> Node:
        kind = tok.kind
        if kind == "num":
            return Literal(tok.span, tok.value)
        if kind == "str":
            return self.string_literal(tok)
        if kind == "ident":
            return Var(tok.span, tok.value)
        if kind in ("true", "false", "nil"):
            return Literal(tok.span, {"true": True, "false": False, "nil": None}[kind])
        if kind == "(":
            self.depth += 1
            expr = self.expression()
            self.expect(")", "')'")
            self.depth -= 1
            return expr
        if kind == "[":
            items, close = self.comma_list("]", self.expression)
            return ListLit(tok.span.to(close.span), items)
        if kind == "{":
            entries, close = self.comma_list("}", self.map_entry)
            return MapLit(tok.span.to(close.span), entries)
        if kind == "-":
            operand = self.expression(UNARY_BP)
            return Unary(tok.span.to(operand.span), "-", operand)
        if kind == "not":
            operand = self.expression(NOT_BP)
            return Unary(tok.span.to(operand.span), "not", operand)
        if kind == "fn":
            return self.function_rest(tok, None)
        if kind == "if":
            return self.if_expr(tok)
        if kind == "match":
            return self.match_expr(tok)
        if kind == "eof":
            raise self.error("unexpected end of input", tok)
        hint = None
        if kind in ("let", "while", "for", "return", "break", "continue"):
            hint = f"'{kind}' is a statement and can't be used where a value is expected"
        raise self.error(f"expected an expression, found {describe(tok)}", tok, hint)

    def infix(self, tok: Token, left: Node, lbp: int) -> Node:
        kind = tok.kind

        if kind == "(":
            args, close = self.comma_list(")", self.expression)
            return Call(left.span.to(close.span), left, args)

        if kind == "[":
            self.depth += 1
            index = self.expression()
            close = self.expect("]", "']'")
            self.depth -= 1
            return Index(left.span.to(close.span), left, index)

        if kind == ".":
            name = self.expect("ident", "a field or method name after '.'")
            return Member(left.span.to(name.span), left, name.value, name.span)

        if kind in ASSIGN_OPS:
            if not isinstance(left, (Var, Index, Member)):
                raise LumenSyntaxError(
                    "invalid assignment target", left.span,
                    hint="only variables (x), indexes (xs[i]) and fields (m.key) can be assigned")
            value = self.expression(lbp - 1)  # right-associative
            return Assign(left.span.to(value.span), left, kind[:-1] or None, value)

        if kind == "|>":
            # `x |> f(a)` is `f(x, a)`; `x |> f` is `f(x)`.
            right = self.expression(lbp)
            if isinstance(right, Call):
                return Call(left.span.to(right.span), right.callee, [left, *right.args])
            return Call(left.span.to(right.span), right, [left])

        if kind in ("and", "or"):
            right = self.expression(lbp)
            return Logical(left.span.to(right.span), kind, left, right)

        if kind in ("..", "..="):
            right = self.expression(lbp)
            if self.peek().kind in ("..", "..="):
                raise self.error("ranges can't be chained", self.peek())
            return Range(left.span.to(right.span), left, right, kind == "..=")

        if kind == "**":
            right = self.expression(lbp - 1)  # right-associative
            return Binary(left.span.to(right.span), kind, left, right)

        right = self.expression(lbp)
        if kind in COMPARISONS and self.peek().kind in COMPARISONS:
            raise self.error("comparison operators can't be chained", self.peek(),
                             hint="write 'a < b and b < c'")
        return Binary(left.span.to(right.span), kind, left, right)

    def comma_list(self, close: str, parse_item):
        self.depth += 1
        items = []
        while not self.check(close):
            items.append(parse_item())
            if not self.match(","):
                break
        end = self.expect(close, f"',' or '{close}'")
        self.depth -= 1
        return items, end

    def map_entry(self) -> tuple[Node, Node]:
        tok = self.peek()
        if tok.kind == "ident" and self.peek(1).kind in (":", ",", "}"):
            # `{name: v}` uses the bare word as a string key; `{name}` is `{name: name}`.
            self.advance()
            key = Literal(tok.span, tok.value)
            value = self.expression() if self.match(":") else Var(tok.span, tok.value)
            return key, value
        key = self.expression()
        self.expect(":", "':' after map key")
        return key, self.expression()

    def string_literal(self, tok: Token) -> Node:
        parts: list[Node] = []
        for part in tok.value:
            if isinstance(part, str):
                parts.append(Literal(tok.span, part))
                continue
            start, end = part
            sub = Parser(self.source, start, end)
            sub.depth = 1
            if sub.check("eof"):
                raise LumenSyntaxError("empty interpolation '{}'", Span(start - 1, end + 1, self.source),
                                       hint="write \\{ for a literal brace")
            expr = sub.expression()
            if not sub.check("eof"):
                raise sub.error(f"unexpected {describe(sub.peek())} in interpolation", sub.peek())
            parts.append(expr)
        if len(parts) == 1 and isinstance(parts[0], Literal):
            return parts[0]
        return Interp(tok.span, parts)

    def function_rest(self, start: Token, name: str | None) -> FnExpr:
        self.expect("(", "'(' to start the parameter list")
        self.depth += 1
        params: list[Pattern] = []
        seen: set[str] = set()
        while not self.check(")"):
            param = self.pattern()
            names = pattern_names(param)
            if names & seen:
                raise LumenSyntaxError(f"duplicate parameter '{min(names & seen)}'", param.span)
            seen |= names
            params.append(param)
            if not self.match(","):
                break
        self.expect(")", "')' to close the parameter list")
        self.depth -= 1

        saved_loop, self.loop_depth = self.loop_depth, 0
        self.fn_depth += 1
        try:
            if self.match("=>"):
                body = self.expression()
            else:
                body = self.block()
        finally:
            self.fn_depth -= 1
            self.loop_depth = saved_loop
        return FnExpr(start.span.to(body.span), name, params, body)

    def if_expr(self, tok: Token) -> If:
        cond = self.expression()
        then = self.block()
        else_: Node | None = None
        if self.match("else"):
            if self.check("if"):
                else_ = self.if_expr(self.advance())
            else:
                else_ = self.block()
        end = (else_ or then).span
        return If(tok.span.to(end), cond, then, else_)

    def match_expr(self, tok: Token) -> Match:
        subject = self.expression()
        open_tok = self.expect("{", "'{' to start the match arms")
        saved, self.depth = self.depth, 0
        arms: list[MatchArm] = []
        while not self.check("}"):
            if self.check("eof"):
                line, _ = self.source.line_col(open_tok.span.start)
                raise self.error(f"expected '}}' to close the match opened on line {line}", self.peek())
            pattern = self.pattern()
            guard = self.expression() if self.match("if") else None
            self.expect("=>", "'=>' after the match pattern")
            body = self.block() if self.check("{") else self.expression()
            arms.append(MatchArm(pattern.span.to(body.span), pattern, guard, body))
            if self.match(","):
                continue
            nxt = self.peek()
            if nxt.kind != "}" and not nxt.nl_before:
                raise self.error(f"expected ',' or a newline between match arms, found {describe(nxt)}", nxt)
        close = self.advance()
        self.depth = saved
        if not arms:
            raise LumenSyntaxError("a match needs at least one arm", tok.span.to(close.span))
        return Match(tok.span.to(close.span), subject, arms)

    # --- patterns ---------------------------------------------------------------

    def pattern(self) -> Pattern:
        first = self.pattern_atom()
        if not self.check("|"):
            return first
        alts = [first]
        while self.match("|"):
            alts.append(self.pattern_atom())
        for alt in alts:
            if pattern_names(alt):
                raise LumenSyntaxError("alternatives joined with '|' can't bind variables", alt.span,
                                       hint="use a guard instead: `x if x == 1 or x == 2 => ...`")
        return POr(alts[0].span.to(alts[-1].span), alts)

    def number_pattern(self, tok: Token) -> tuple[int | float, Span]:
        if tok.kind == "-":
            num = self.expect("num", "a number after '-'")
            return -num.value, tok.span.to(num.span)
        if tok.kind != "num":
            raise self.error(f"expected a number in range pattern, found {describe(tok)}", tok)
        return tok.value, tok.span

    def pattern_atom(self) -> Pattern:
        tok = self.advance()
        kind = tok.kind

        if kind == "ident":
            return PWild(tok.span) if tok.value == "_" else PBind(tok.span, tok.value)

        if kind == "num" or (kind == "-" and self.check("num")):
            lo, span = self.number_pattern(tok)
            if self.check("..") or self.check("..="):
                inclusive = self.advance().kind == "..="
                hi, hi_span = self.number_pattern(self.advance())
                return PRange(span.to(hi_span), lo, hi, inclusive)
            return PLit(span, lo)

        if kind == "str":
            if any(not isinstance(p, str) for p in tok.value):
                raise self.error("interpolated strings can't be used as patterns", tok)
            return PLit(tok.span, "".join(tok.value))

        if kind in ("true", "false", "nil"):
            return PLit(tok.span, {"true": True, "false": False, "nil": None}[kind])

        if kind == "[":
            self.depth += 1
            before: list[Pattern] = []
            after: list[Pattern] = []
            has_rest, rest = False, None
            while not self.check("]"):
                if self.check(".."):
                    dots = self.advance()
                    if has_rest:
                        raise self.error("only one '..' is allowed in a list pattern", dots)
                    has_rest = True
                    if self.check("ident"):
                        name = self.advance().value
                        rest = None if name == "_" else name
                else:
                    (after if has_rest else before).append(self.pattern())
                if not self.match(","):
                    break
            close = self.expect("]", "',' or ']'")
            self.depth -= 1
            return PList(tok.span.to(close.span), before, after, has_rest, rest)

        if kind == "{":
            self.depth += 1
            entries: list[tuple[str, Pattern]] = []
            while not self.check("}"):
                key_tok = self.advance()
                if key_tok.kind == "ident":
                    key = key_tok.value
                    sub = self.pattern() if self.match(":") else PBind(key_tok.span, key)
                elif key_tok.kind == "str" and all(isinstance(p, str) for p in key_tok.value):
                    key = "".join(key_tok.value)
                    self.expect(":", "':' after map pattern key")
                    sub = self.pattern()
                else:
                    raise self.error(f"expected a map pattern key, found {describe(key_tok)}", key_tok)
                entries.append((key, sub))
                if not self.match(","):
                    break
            close = self.expect("}", "',' or '}'")
            self.depth -= 1
            return PMap(tok.span.to(close.span), entries)

        raise self.error(f"expected a pattern, found {describe(tok)}", tok)

"""Tokenizer: turns source text into a flat list of tokens.

Two details matter to the parser:

* Each token records whether a newline preceded it (`nl_before`). Lumen has
  no mandatory semicolons; the parser uses this flag to decide where a
  statement ends.
* String literals are split into parts here. Literal text is kept as `str`,
  and each `{...}` interpolation is kept as a (start, end) offset pair into
  the original source, so the parser can parse it in place and every error
  inside an interpolation still points at the right column.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import LumenSyntaxError, Source, Span

KEYWORDS = frozenset({
    "let", "fn", "if", "else", "while", "for", "in", "return", "break",
    "continue", "true", "false", "nil", "and", "or", "not", "match",
})

# Longest first, so '..=' wins over '..' and '.'.
OPERATORS = sorted([
    "..=", "**", "//", "==", "!=", "<=", ">=", "|>", "=>", "..",
    "+=", "-=", "*=", "/=",
    "(", ")", "[", "]", "{", "}", ",", ":", ".", ";",
    "+", "-", "*", "/", "%", "<", ">", "=", "|",
], key=len, reverse=True)

ESCAPES = {
    "n": "\n", "t": "\t", "r": "\r", "0": "\0",
    "\\": "\\", '"': '"', "{": "{", "}": "}",
}

DIGITS = frozenset("0123456789")


@dataclass(slots=True)
class Token:
    kind: str       # 'num', 'str', 'ident', 'eof', a keyword, or an operator
    value: object
    span: Span
    nl_before: bool = False


class Lexer:
    def __init__(self, source: Source, start: int = 0, end: int | None = None):
        self.source = source
        self.src = source.text
        self.start = start
        self.pos = start
        self.end = len(self.src) if end is None else end

    def error(self, message, start, end=None, hint=None, incomplete=False):
        span = Span(start, self.pos if end is None else end, self.source)
        return LumenSyntaxError(message, span, hint, incomplete)

    def tokenize(self) -> list[Token]:
        tokens: list[Token] = []
        src, end = self.src, self.end
        newline = False
        while True:
            while self.pos < end:
                c = src[self.pos]
                if c == "\n":
                    newline = True
                    self.pos += 1
                elif c in " \t\r":
                    self.pos += 1
                elif c == "#":
                    nl = src.find("\n", self.pos, end)
                    self.pos = end if nl == -1 else nl
                else:
                    break

            if self.pos >= end:
                # Anchor end-of-input errors just after the last real character.
                eof = end
                while eof > self.start and src[eof - 1].isspace():
                    eof -= 1
                tokens.append(Token("eof", None, Span(eof, eof, self.source), True))
                return tokens

            c = src[self.pos]
            if c in DIGITS:
                tok = self.number()
            elif c.isalpha() or c == "_":
                tok = self.word()
            elif c == '"':
                tok = self.string()
            else:
                tok = self.operator()
            tok.nl_before = newline
            newline = False
            tokens.append(tok)

    def span(self, start: int) -> Span:
        return Span(start, self.pos, self.source)

    def word(self) -> Token:
        start = self.pos
        src, end = self.src, self.end
        while self.pos < end and (src[self.pos].isalnum() or src[self.pos] == "_"):
            self.pos += 1
        text = src[start:self.pos]
        kind = text if text in KEYWORDS else "ident"
        return Token(kind, text, self.span(start))

    def number(self) -> Token:
        start = self.pos
        src, end = self.src, self.end

        def digits():
            while self.pos < end and (src[self.pos] in DIGITS or src[self.pos] == "_"):
                self.pos += 1

        digits()
        is_float = False
        # '1..5' is a range, not the float '1.' -- require a digit after '.'.
        if self.pos + 1 < end and src[self.pos] == "." and src[self.pos + 1] in DIGITS:
            is_float = True
            self.pos += 1
            digits()
        if self.pos < end and src[self.pos] in "eE":
            mark = self.pos
            self.pos += 1
            if self.pos < end and src[self.pos] in "+-":
                self.pos += 1
            if self.pos < end and src[self.pos] in DIGITS:
                is_float = True
                digits()
            else:
                self.pos = mark
        if self.pos < end and (src[self.pos].isalpha() or src[self.pos] == "_"):
            while self.pos < end and (src[self.pos].isalnum() or src[self.pos] == "_"):
                self.pos += 1
            raise self.error(f"invalid number literal '{src[start:self.pos]}'", start)

        text = src[start:self.pos].replace("_", "")
        value = float(text) if is_float else int(text)
        return Token("num", value, self.span(start))

    def string(self) -> Token:
        start = self.pos
        src, end = self.src, self.end
        self.pos += 1
        parts: list[str | tuple[int, int]] = []
        buf: list[str] = []

        while True:
            if self.pos >= end:
                raise self.error("unterminated string", start, incomplete=True)
            c = src[self.pos]
            if c == '"':
                self.pos += 1
                break
            if c == "\\":
                if self.pos + 1 >= end:
                    raise self.error("unterminated string", start, incomplete=True)
                esc = src[self.pos + 1]
                if esc not in ESCAPES:
                    raise self.error(f"unknown escape sequence '\\{esc}'", self.pos, self.pos + 2,
                                     hint="valid escapes are \\n \\t \\r \\0 \\\\ \\\" \\{ \\}")
                buf.append(ESCAPES[esc])
                self.pos += 2
                continue
            if c == "{":
                if buf:
                    parts.append("".join(buf))
                    buf = []
                parts.append(self.interpolation())
                continue
            if c == "}":
                raise self.error("unmatched '}' in string", self.pos, self.pos + 1,
                                 hint="write \\} for a literal brace")
            buf.append(c)
            self.pos += 1

        if buf or not parts:
            parts.append("".join(buf))
        return Token("str", parts, self.span(start))

    def interpolation(self) -> tuple[int, int]:
        """Scan a `{...}` inside a string; return the offsets of its contents."""
        src, end = self.src, self.end
        open_pos = self.pos
        self.pos += 1
        depth = 1
        while self.pos < end:
            ch = src[self.pos]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    break
            elif ch == '"':
                self.skip_nested_string()
            elif ch == "\n":
                raise self.error("unterminated interpolation; expected '}'", open_pos)
            self.pos += 1
        else:
            raise self.error("unterminated interpolation; expected '}'", open_pos, incomplete=True)
        contents = (open_pos + 1, self.pos)
        self.pos += 1  # the closing '}'
        return contents

    def skip_nested_string(self) -> None:
        """Advance from an opening quote to its closing quote."""
        src, end = self.src, self.end
        opening = self.pos
        self.pos += 1
        while self.pos < end and src[self.pos] != '"':
            self.pos += 2 if src[self.pos] == "\\" else 1
        if self.pos >= end:
            raise self.error("unterminated string", opening, incomplete=True)

    def operator(self) -> Token:
        start = self.pos
        src = self.src
        pair = src[start:start + 2]
        if pair in ("&&", "||"):
            word = "and" if pair == "&&" else "or"
            raise self.error(f"unexpected '{pair}'", start, start + 2, hint=f"Lumen spells this '{word}'")
        for op in OPERATORS:
            if src.startswith(op, start, self.end):
                self.pos += len(op)
                return Token(op, op, self.span(start))
        c = src[start]
        hint = {
            "!": "Lumen spells logical negation 'not'",
            "'": 'strings use double quotes: "like this"',
        }.get(c)
        raise self.error(f"unexpected character {c!r}", start, start + 1, hint=hint)

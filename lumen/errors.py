"""Source tracking and human-friendly diagnostics.

Every token and AST node carries a `Span` that points back into the `Source`
it came from, so an error raised anywhere -- lexer, parser or a runtime
failure deep inside a call stack -- can render the offending line with a
caret underneath it.
"""

from __future__ import annotations

from dataclasses import dataclass


class Source:
    """A named piece of program text."""

    __slots__ = ("text", "name")

    def __init__(self, text: str, name: str = "<input>"):
        self.text = text
        self.name = name

    def line_col(self, offset: int) -> tuple[int, int]:
        line = self.text.count("\n", 0, offset) + 1
        col = offset - (self.text.rfind("\n", 0, offset) + 1) + 1
        return line, col

    def line_bounds(self, offset: int) -> tuple[int, int]:
        start = self.text.rfind("\n", 0, offset) + 1
        end = self.text.find("\n", offset)
        return start, len(self.text) if end == -1 else end


@dataclass(frozen=True, slots=True)
class Span:
    start: int
    end: int
    source: Source

    def to(self, other: Span) -> Span:
        return Span(self.start, other.end, self.source)

    def location(self) -> str:
        line, col = self.source.line_col(self.start)
        return f"{self.source.name}:{line}:{col}"


class LumenError(Exception):
    label = "error"

    def __init__(self, message: str, span: Span | None = None, hint: str | None = None):
        super().__init__(message)
        self.message = message
        self.span = span
        self.hint = hint
        # Runtime errors get the Lumen call stack attached as they unwind:
        # a list of (function name, call-site span), outermost first.
        self.trace: list[tuple[str, Span]] | None = None

    def __str__(self) -> str:
        if self.span is None:
            return self.message
        return f"{self.span.location()}: {self.message}"

    def render(self, color: bool = False) -> str:
        def paint(text: str, code: str) -> str:
            return f"\033[{code}m{text}\033[0m" if color else text

        out = [paint(self.label, "1;31") + paint(": " + self.message, "1")]
        gutter = ""
        if self.span is not None:
            src = self.span.source
            line, col = src.line_col(self.span.start)
            line_start, line_end = src.line_bounds(self.span.start)
            text = src.text[line_start:line_end]
            width = max(1, min(self.span.end, line_end) - self.span.start)
            # Preserve tabs so the caret lines up under tab-indented code.
            pad = "".join("\t" if ch == "\t" else " " for ch in text[: col - 1])
            gutter = " " * len(str(line))
            bar = paint("|", "1;34")
            out.append(f"{gutter}{paint('-->', '1;34')} {self.span.location()}")
            out.append(f"{gutter} {bar}")
            out.append(f"{paint(str(line), '1;34')} {bar} {text}")
            out.append(f"{gutter} {bar} {pad}{paint('^' * width, '1;31')}")
        eq = paint("=", "1;34")
        if self.hint:
            out.append(f"{gutter} {eq} {paint('hint', '1')}: {self.hint}")
        out.extend(f"{gutter} {eq} {line}" for line in self.trace_lines())
        return "\n".join(out)

    def trace_lines(self, max_lines: int = 20) -> list[str]:
        """Innermost call first, with runs of identical frames folded (deep recursion)."""
        frames = [f"in {name}, called from {span.location()}" for name, span in reversed(self.trace or [])]
        lines: list[str] = []
        i = 0
        while i < len(frames):
            j = i
            while j < len(frames) and frames[j] == frames[i]:
                j += 1
            run = j - i
            lines.extend([frames[i]] * min(run, 3))
            if run > 3:
                lines.append(f"... the frame above repeated {run - 3} more times")
            i = j
        if len(lines) > max_lines:
            lines = lines[:max_lines] + [f"... {len(lines) - max_lines} more frames"]
        return lines


class LumenSyntaxError(LumenError):
    label = "syntax error"

    def __init__(self, message, span=None, hint=None, incomplete=False):
        super().__init__(message, span, hint)
        # True when the error is "ran out of input" -- the REPL uses this to
        # keep reading lines instead of reporting an error.
        self.incomplete = incomplete


class LumenRuntimeError(LumenError):
    label = "runtime error"

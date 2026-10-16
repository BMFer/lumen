"""Interactive prompt with multi-line input and persistent history."""

from __future__ import annotations

import os
import sys

from . import __version__
from .errors import LumenError, LumenSyntaxError, Source
from .interpreter import Interpreter, parse_program
from .nodes import Assign, For, Let, While
from .values import show

HISTORY = os.path.expanduser("~/.lumen_history")

HELP = """\
  :help         show this message
  :reset        forget all definitions
  :quit         exit (or press Ctrl-D)

Input continues on the next line while brackets or strings are open.
Press Enter on an empty continuation line to force evaluation.
Try:  [1, 2, 3, 4].map(fn(x) => x * x).sum()"""


def setup_history() -> None:
    try:
        import readline
    except ImportError:
        return
    try:
        readline.read_history_file(HISTORY)
    except (FileNotFoundError, OSError):
        pass
    readline.set_history_length(2000)
    import atexit

    def save():
        try:
            readline.write_history_file(HISTORY)
        except OSError:
            pass

    atexit.register(save)


def run_repl(color: bool) -> int:
    setup_history()

    def paint(text, code):
        return f"\033[{code}m{text}\033[0m" if color else text

    interp = Interpreter()
    print(f"Lumen {__version__} -- :help for help, Ctrl-D to exit")
    buffer: list[str] = []
    count = 0

    while True:
        prompt = "...... " if buffer else paint("lumen> ", "1;35")
        try:
            line = input(prompt)
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print("^C")
            buffer = []
            continue

        if not buffer:
            command = line.strip()
            if command in (":quit", ":q", ":exit"):
                return 0
            if command == ":help":
                print(HELP)
                continue
            if command == ":reset":
                interp = Interpreter()
                print("environment reset")
                continue
            if not command:
                continue

        buffer.append(line)
        text = "\n".join(buffer)
        count += 1
        source = Source(text, f"<repl:{count}>")
        try:
            program = parse_program(source)
        except LumenSyntaxError as e:
            # Keep reading if the input is merely unfinished; a blank line gives up.
            if e.incomplete and line.strip():
                count -= 1
                continue
            print(e.render(color), file=sys.stderr)
            buffer = []
            continue
        buffer = []

        try:
            value = interp.execute(program)
        except LumenError as e:
            print(e.render(color), file=sys.stderr)
            continue
        except KeyboardInterrupt:
            print(paint("interrupted", "33"), file=sys.stderr)
            continue

        last = program.stmts[-1] if program.stmts else None
        if value is not None and not isinstance(last, (Let, While, For, Assign)):
            print(paint(show(value), "36"))

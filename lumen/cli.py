"""Command-line entry point: `lumen [file | -e code]`."""

from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .errors import LumenError
from .interpreter import Interpreter


def use_color(stream) -> bool:
    return stream.isatty() and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lumen", description="The Lumen programming language.")
    ap.add_argument("file", nargs="?", help="script to run (omit to start the REPL)")
    ap.add_argument("-e", "--eval", metavar="CODE", help="run CODE and print its value")
    ap.add_argument("--version", action="version", version=f"lumen {__version__}")
    args = ap.parse_args(argv)

    if args.eval is None and args.file is None:
        from .repl import run_repl
        return run_repl(use_color(sys.stdout))

    if args.eval is not None:
        text, name = args.eval, "<eval>"
    elif args.file == "-":
        text, name = sys.stdin.read(), "<stdin>"
    else:
        try:
            with open(args.file, encoding="utf-8") as f:
                text, name = f.read(), args.file
        except OSError as e:
            print(f"lumen: can't open {args.file}: {e.strerror}", file=sys.stderr)
            return 2

    interp = Interpreter()
    try:
        value = interp.run(text, name)
    except LumenError as e:
        sys.stdout.flush()
        print(e.render(use_color(sys.stderr)), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    if args.eval is not None and value is not None:
        from .values import show
        print(show(value))
    return 0

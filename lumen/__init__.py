"""Lumen: a small, expression-oriented scripting language."""

__version__ = "1.0.0"

from .errors import LumenError, LumenRuntimeError, LumenSyntaxError  # noqa: E402
from .interpreter import Interpreter  # noqa: E402


def run(text: str, name: str = "<input>"):
    """Run a Lumen program in a fresh interpreter and return its last value."""
    return Interpreter().run(text, name)


__all__ = ["Interpreter", "LumenError", "LumenRuntimeError", "LumenSyntaxError", "run", "__version__"]

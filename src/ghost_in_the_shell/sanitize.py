"""Checks on untrusted text before it reaches a model or the user's screen.

Requests, file names, commands and model replies are all treated as untrusted.

Qwen's chat template marks roles with special tokens such as <|im_start|>, and
llama-server turns those strings into real special tokens even inside message
text. A request containing "<|im_end|><|im_start|>system ..." therefore opens a
new system message, and in testing the model obeyed it. These strings are
removed from requests and rejected in commands.

Invisible characters (zero-width spaces, bidirectional overrides, control
codes) are removed or rejected for the same reason: they can hide text from
the person reading it, or split a special token so that a simple filter misses
it.
"""

import re
import unicodedata

MAX_REQUEST_CHARS = 400
MAX_COMMAND_CHARS = 1000

_SPECIAL_TOKEN = re.compile(r"<\|[^<>|]{0,40}\|>|</?(?:tool_call|tool_response|think)>", re.IGNORECASE)
_INVISIBLE_CATEGORIES = {"Cc", "Cf", "Co", "Cs", "Cn"}


class InputRejected(ValueError):
    """Raised when text cannot be used safely. The message is shown to the user."""


def strip_special_tokens(text: str) -> str:
    # Repeat until nothing changes, so that removing one token cannot join the
    # remaining pieces into another one ("<|im_<|x|>start|>").
    previous = None
    while previous != text:
        previous, text = text, _SPECIAL_TOKEN.sub("", text)
    return text


def _remove_invisible(text: str, keep_newlines: bool) -> str:
    kept = []
    for char in text:
        if char == "\n" and keep_newlines:
            kept.append(char)
        elif char in "\t\n\r":
            kept.append(" ")
        elif unicodedata.category(char) not in _INVISIBLE_CATEGORIES:
            kept.append(char)
    return "".join(kept)


def manipulation_signs(text: str) -> str | None:
    """Describe hidden content in a request, or None.

    Ordinary typing never produces model control tokens or invisible
    formatting characters, so their presence is itself a strong sign of an
    attack, even after clean_request has removed them.
    """
    normal = unicodedata.normalize("NFKC", text)
    if strip_special_tokens(_remove_invisible(normal, keep_newlines=True)) != _remove_invisible(normal, keep_newlines=True):
        return "model control codes"
    if any(unicodedata.category(c) == "Cf" for c in text):
        return "hidden characters"
    return None


def clean_request(text: str) -> str:
    """Normalise a plain-English request. Returns the cleaned text or raises InputRejected."""
    # NFKC first, so that look-alike characters (a full-width "｜") become the
    # ASCII characters the special-token filter looks for.
    text = unicodedata.normalize("NFKC", text)
    text = _remove_invisible(text, keep_newlines=False)
    text = strip_special_tokens(text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise InputRejected("The request is empty.")
    if len(text) > MAX_REQUEST_CHARS:
        raise InputRejected(f"The request is too long (over {MAX_REQUEST_CHARS} characters).")
    return text


def check_command(command: str) -> str:
    """Validate a shell command without changing it.

    A command is not rewritten, because the text that is explained, checked
    and run must be exactly the text the user sees. Anything suspicious is
    rejected instead.
    """
    command = command.strip()
    if not command:
        raise InputRejected("The command is empty.")
    if len(command) > MAX_COMMAND_CHARS:
        raise InputRejected(f"The command is too long (over {MAX_COMMAND_CHARS} characters).")
    if "\n" in command or "\r" in command:
        raise InputRejected("The command spans several lines; only single-line commands are supported.")
    for char in command:
        if char != "\t" and unicodedata.category(char) in _INVISIBLE_CATEGORIES:
            raise InputRejected(f"The command contains a hidden character (U+{ord(char):04X}).")
    if strip_special_tokens(unicodedata.normalize("NFKC", command)) != unicodedata.normalize("NFKC", command):
        raise InputRejected("The command contains model control tokens.")
    return command


def clean_model_text(text: str) -> str:
    """Make a model's prose reply safe to display as plain text."""
    text = unicodedata.normalize("NFKC", text)
    text = _remove_invisible(text, keep_newlines=True)
    return strip_special_tokens(text).strip()


_ANSI_ESCAPE = re.compile(r"\x1b(\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(\x07|\x1b\\)|[@-Z\\-_])")


def clean_terminal_output(text: str) -> str:
    """Make program output safe to display.

    Terminal escape sequences are removed so that output cannot recolour,
    hide or overwrite other text on the screen, or fake a prompt.
    """
    text = _ANSI_ESCAPE.sub("", text)
    return "".join(
        char for char in text
        if char in "\n\t" or unicodedata.category(char) not in _INVISIBLE_CATEGORIES
    )

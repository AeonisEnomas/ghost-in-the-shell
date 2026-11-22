# Checks on untrusted text before it reaches a model or the user's screen.

import re
import unicodedata

MAX_REQUEST_CHARS = 400
MAX_COMMAND_CHARS = 1000

_SPECIAL_TOKEN = re.compile(r"<\|[^<>|]{0,40}\|>|</?(?:tool_call|tool_response|think)>", re.IGNORECASE)
_INVISIBLE_CATEGORIES = {"Cc", "Cf", "Co", "Cs", "Cn"}


class InputRejected(ValueError):
    # Raised when text cannot be used safely. The message is shown to the user.
    pass


def strip_special_tokens(text: str) -> str:
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
    # Describe hidden content in a request, or None.
    normal = unicodedata.normalize("NFKC", text)
    if strip_special_tokens(_remove_invisible(normal, keep_newlines=True)) != _remove_invisible(normal, keep_newlines=True):
        return "model control codes"
    if any(unicodedata.category(c) == "Cf" for c in text):
        return "hidden characters"
    return None


def clean_request(text: str) -> str:
    # Normalise a plain-English request. Returns the cleaned text or raises InputRejected.
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
    # Validate a shell command without changing it.
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
    # Make a model's prose reply safe to display as plain text.
    text = unicodedata.normalize("NFKC", text)
    text = _remove_invisible(text, keep_newlines=True)
    return strip_special_tokens(text).strip()


_ANSI_ESCAPE = re.compile(r"\x1b(\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(\x07|\x1b\\)|[@-Z\\-_])")


def clean_terminal_output(text: str) -> str:
    # Make program output safe to display.
    text = _ANSI_ESCAPE.sub("", text)
    return "".join(
        char for char in text
        if char in "\n\t" or unicodedata.category(char) not in _INVISIBLE_CATEGORIES
    )

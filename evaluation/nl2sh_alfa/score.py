"""Decide whether a predicted command does the same thing as a reference.

A prediction is correct when, run on a fresh copy of the test filesystem, it
leaves the same files behind as one of the two reference commands and prints
the same lines of output, in any order.
"""

import json

import sandbox


def effect(command: str, fs_num: int) -> dict:
    """What a command did: the lines it printed, the files it left, its exit code."""
    result = sandbox.run(command, fs_num)
    lines = [line.rstrip() for line in result.output.strip().splitlines()]
    return {"lines": sorted(lines), "fs": json.dumps(sorted(result.manifest.items())), "exit": result.exit_code}


def same(a: dict, b: dict) -> bool:
    return a["lines"] == b["lines"] and a["fs"] == b["fs"]


def is_correct(command: str, fs_num: int, references: list[dict]) -> bool:
    if not command.strip():
        return False
    result = effect(command, fs_num)
    return any(same(result, reference) for reference in references)

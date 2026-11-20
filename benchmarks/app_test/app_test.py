"""App test: short, everyday requests of the kind the app is built for.

Each request in prompts.json is run in the folder built by fixture.py and
judged by what the command does, compared with a set of reference commands:

- if the reference changes files, the prediction must leave the same files
  behind (path, type, permissions, content); what it prints is ignored;
- otherwise the prediction must print the same lines and change nothing.
  Line order is ignored unless the request is about ordering.

References are run again in every scoring session, never cached, so results do
not depend on the day or on an earlier run.

Usage, from this folder:
  uv run python app_test.py check                                  validate the test set
  uv run python app_test.py generate NAME path/to/model.gguf       write results/preds/NAME.jsonl
  uv run python app_test.py score results/preds/*.jsonl            accuracy and paired tests
  uv run python app_test.py overlap path/to/train.csv              requests too close to training data
"""

import atexit
import bz2
import functools
import gzip
import hashlib
import io
import json
import lzma
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "model_selection"))

import fixture  # noqa: E402
import sandbox  # noqa: E402  (bubblewrap arguments shared with the model-selection benchmark)

PROMPTS = HERE / "prompts.json"
RESULTS = HERE / "results"
TIMEOUT_S = 10
MAX_OUTPUT = 20_000


def load_prompts() -> list[dict]:
    return json.loads(PROMPTS.read_text())


# ---------------------------------------------------------------- running a command

@functools.cache
def template() -> Path:
    """The test folder, built once per session and copied for every run."""
    root = Path(tempfile.mkdtemp(prefix="ghost-apptest-"))
    atexit.register(shutil.rmtree, root, ignore_errors=True)
    fixture.build(root / "fs", time.time())
    return root / "fs"


def _content_digest(data: bytes) -> str:
    """Hash of a file's content. Archives are compared by what they contain, so the
    compression level or the order files were added in does not matter."""
    for magic, unpack in ((b"\x1f\x8b", gzip.decompress), (b"BZh", bz2.decompress),
                          (b"\xfd7zXZ", lzma.decompress)):
        if data.startswith(magic):
            try:
                data = unpack(data)
            except (OSError, EOFError, lzma.LZMAError):
                pass
            break
    try:
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            members = sorted(
                (m.name.rstrip("/"), m.type.decode(), m.mode,
                 hashlib.md5(tar.extractfile(m).read()).hexdigest() if m.isfile() else "")
                for m in tar.getmembers())
        data = json.dumps(members).encode()
    except (tarfile.TarError, EOFError):
        pass
    return hashlib.md5(data).hexdigest()


def manifest(fs_root: Path) -> str:
    """Every file, folder and link the command could have touched, as one string."""
    entries = []
    for top in sorted(fs_root.iterdir()):
        if top.name in sandbox.HOST_MOUNTS:
            continue
        stack = [top]
        while stack:
            path = stack.pop()
            st = path.lstat()
            rel, mode = "/" + str(path.relative_to(fs_root)), stat.S_IMODE(st.st_mode)
            if stat.S_ISLNK(st.st_mode):
                entries.append((rel, "l", os.readlink(path)))
            elif stat.S_ISDIR(st.st_mode):
                entries.append((rel, "d", mode))
                os.chmod(path, mode | 0o700)      # the command may have locked the folder
                stack.extend(path.iterdir())
            else:
                os.chmod(path, mode | 0o400)
                entries.append((rel, "f", mode, _content_digest(path.read_bytes())))
    return json.dumps(sorted(entries))


def normalise(output: str) -> list[str]:
    """Printed lines without layout differences: spacing, blank lines, a leading './'."""
    lines = []
    for line in output.splitlines():
        line = re.sub(r"(?<![\w./-])\./", "", " ".join(line.split()))
        if line:
            lines.append(line)
    return lines


def run(command: str) -> dict:
    """Run a command in a fresh copy of the test folder."""
    with tempfile.TemporaryDirectory(prefix="ghost-apptest-run-") as tmp:
        fs_root = Path(tmp) / "fs"
        shutil.copytree(template(), fs_root, symlinks=True)
        args = sandbox._bwrap_args(fs_root, {"HOME": fixture.HOME})[:-1] + [fixture.CWD]
        wrapped = f"ulimit -u 4096 -v 2097152 2>/dev/null; {command}"
        try:
            proc = subprocess.run(args + ["bash", "-c", wrapped], stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=TIMEOUT_S)
            out, code = proc.stdout, proc.returncode
        except subprocess.TimeoutExpired as exc:
            out, code = exc.stdout or b"", -1
        lines = normalise(out.decode("utf-8", errors="replace")[:MAX_OUTPUT])
        return {"lines": lines, "fs": manifest(fs_root), "exit": code}


# ---------------------------------------------------------------- scoring

@functools.cache
def untouched() -> str:
    return run("true")["fs"]


def same_effect(prediction: dict, reference: dict, ordered: bool) -> bool:
    if reference["fs"] != untouched():
        return prediction["fs"] == reference["fs"]
    if prediction["fs"] != reference["fs"]:
        return False
    if ordered:
        return prediction["lines"] == reference["lines"]
    return sorted(prediction["lines"]) == sorted(reference["lines"])


def reference_runs(prompts: list[dict]) -> list[list[dict]]:
    return [[run(command) for command in p["references"]] for p in prompts]


def is_correct(command: str, prompt: dict, references: list[dict]) -> bool:
    if not command.strip():
        return False
    result = run(command)
    return any(same_effect(result, ref, prompt.get("ordered", False)) for ref in references)


# ---------------------------------------------------------------- commands

def check() -> int:
    """Every reference must work, give the same result twice, and not be matched by doing nothing."""
    prompts = load_prompts()
    problems = []
    ids = [p["id"] for p in prompts]
    if len(ids) != len(set(ids)):
        problems.append("duplicate ids")
    requests = [p["request"].lower() for p in prompts]
    if len(requests) != len(set(requests)):
        problems.append("duplicate requests")
    nothing = run("true")
    for p in prompts:
        ordered = p.get("ordered", False)
        runs = [run(c) for c in p["references"]]
        for command, first in zip(p["references"], runs):
            if first["exit"] != 0 and not p.get("allow_nonzero"):
                problems.append(f"{p['id']}: exit {first['exit']}: {command}\n      {first['lines'][:2]}")
            if not same_effect(run(command), first, ordered):
                problems.append(f"{p['id']}: not repeatable: {command}")
            if same_effect(nothing, first, ordered):
                problems.append(f"{p['id']}: passed by doing nothing: {command}")
        distinct = []
        for r in runs:
            if not any(same_effect(r, d, ordered) for d in distinct):
                distinct.append(r)
        p["_outcomes"] = len(distinct)
    by_category: dict[str, int] = {}
    for p in prompts:
        by_category[p["category"]] = by_category.get(p["category"], 0) + 1
    words = sorted(len(p["request"].split()) for p in prompts)
    print(f"{len(prompts)} requests, {sum(len(p['references']) for p in prompts)} reference commands, "
          f"median request length {words[len(words) // 2]} words")
    print("by category:", dict(sorted(by_category.items())))
    print("requests whose references describe more than one accepted result:",
          sum(p["_outcomes"] > 1 for p in prompts))
    for problem in problems:
        print("PROBLEM", problem)
    print("ok" if not problems else f"{len(problems)} problems")
    return 1 if problems else 0


def generate(name: str, gguf: str) -> None:
    from generate import SYSTEM_PROMPT        # the prompt used in every round and by the app
    from round2 import run_task, with_server

    out = RESULTS / "preds" / f"{name}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    items = [{"index": i, "id": p["id"], "nl": p["request"]} for i, p in enumerate(load_prompts())]
    with_server(None, str(Path(gguf).resolve()),
                lambda: run_task(out, items, lambda it: (SYSTEM_PROMPT, it["nl"], 128, True)))
    print(f"wrote {out}")


def score(paths: list[str]) -> None:
    import pandas as pd
    from round2_report import mcnemar

    prompts = load_prompts()
    references = reference_runs(prompts)
    by_id = {p["id"]: i for i, p in enumerate(prompts)}
    correct, rows = {}, []
    (RESULTS / "scored").mkdir(parents=True, exist_ok=True)
    for path in map(Path, paths):
        records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        marks = {}
        for rec in records:
            i = by_id[rec["id"]]
            rec["correct"] = is_correct(rec["command"], prompts[i], references[i])
            rec["category"] = prompts[i]["category"]
            marks[rec["id"]] = rec["correct"]
        frame = pd.DataFrame(records)
        frame[["id", "category", "nl", "command", "correct"]].to_json(
            RESULTS / "scored" / path.name, orient="records", lines=True)
        correct[path.stem] = pd.Series(marks)
        rows.append({"model": path.stem, "n": len(frame), "accuracy": frame.correct.mean(),
                     **frame.groupby("category").correct.mean().to_dict()})
    report = ["## Accuracy", "", pd.DataFrame(rows).to_markdown(index=False, floatfmt=".3f"), ""]
    names = list(correct)
    if len(names) > 1:
        tests = []
        for other in names[1:]:
            a, b = correct[names[0]].align(correct[other], join="inner")
            a_only, b_only, p = mcnemar(a.astype(bool), b.astype(bool))
            tests.append({"A": names[0], "B": other, "only A right": a_only,
                          "only B right": b_only, "p_value": p})
        report += ["## Paired McNemar tests against the first file", "",
                   pd.DataFrame(tests).to_markdown(index=False, floatfmt=".3f"), ""]
    text = "\n".join(report)
    (RESULTS / "report.md").write_text(text)
    print(text)


def overlap(train_csv: str) -> None:
    """Requests that match, or nearly match, a request in a training file (columns: nl, bash)."""
    import pandas as pd

    def words(text: str) -> frozenset:
        return frozenset(re.sub(r"\W+", " ", text.lower()).split())

    train = {words(t) for t in pd.read_csv(train_csv).nl.astype(str)}
    hits = 0
    for p in load_prompts():
        mine = words(p["request"])
        if mine in train:
            hits += 1
            print(f"exact  {p['id']}: {p['request']}")
        elif any(len(mine & t) >= 0.8 * len(mine | t) for t in train
                 if 0.8 * len(t) <= len(mine) <= 1.25 * len(t)):
            hits += 1
            print(f"near   {p['id']}: {p['request']}")
    print(f"{hits} of {len(load_prompts())} requests are exact or near matches of a training request")


if __name__ == "__main__":
    command, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    if command == "check":
        sys.exit(check())
    elif command == "generate" and len(args) == 2:
        generate(*args)
    elif command == "score" and args:
        score(args)
    elif command == "overlap" and len(args) == 1:
        overlap(args[0])
    else:
        print(__doc__)
        sys.exit(2)

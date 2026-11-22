# Test the models on app requests: short, everyday tasks of the kind the app is built for.

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
sys.path.insert(0, str(HERE.parent))

import fixture
from common import HOST_MOUNTS, MODELS, PAIRS, answer_all, bwrap_args, mcnemar

PROMPTS = HERE / "prompts.json"
RESULTS = HERE / "results"
TRAINING_DATA = HERE.parents[1] / "finetune" / "records" / "train.csv"
TIMEOUT_S = 10
MAX_OUTPUT = 20_000


def load_prompts() -> list[dict]:
    return json.loads(PROMPTS.read_text())


@functools.cache
def template() -> Path:
    # The test folder, built once per session and copied for every run.
    root = Path(tempfile.mkdtemp(prefix="ghost-apptest-"))
    atexit.register(shutil.rmtree, root, ignore_errors=True)
    fixture.build(root / "fs", time.time())
    return root / "fs"


def _content_digest(data: bytes) -> str:
    # Hash of a file's content. Archives are compared by what they contain, so the compression level or the order files were added in does not matter.
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
    # Every file, folder and link the command could have touched, as one string.
    entries = []
    for top in sorted(fs_root.iterdir()):
        if top.name in HOST_MOUNTS:
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
                os.chmod(path, mode | 0o700)
                stack.extend(path.iterdir())
            else:
                os.chmod(path, mode | 0o400)
                entries.append((rel, "f", mode, _content_digest(path.read_bytes())))
    return json.dumps(sorted(entries))


def normalise(output: str) -> list[str]:
    # Printed lines without layout differences: spacing, blank lines, a leading './'.
    lines = []
    for line in output.splitlines():
        line = re.sub(r"(?<![\w./-])\./", "", " ".join(line.split()))
        if line:
            lines.append(line)
    return lines


def run(command: str) -> dict:
    # Run a command in a fresh copy of the test folder.
    with tempfile.TemporaryDirectory(prefix="ghost-apptest-run-") as tmp:
        fs_root = Path(tmp) / "fs"
        shutil.copytree(template(), fs_root, symlinks=True)
        args = bwrap_args(fs_root, {"HOME": fixture.HOME}, cwd=fixture.CWD)
        wrapped = f"ulimit -u 4096 -v 2097152 2>/dev/null; {command}"
        try:
            proc = subprocess.run(args + ["bash", "-c", wrapped], stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=TIMEOUT_S)
            out, code = proc.stdout, proc.returncode
        except subprocess.TimeoutExpired as exc:
            out, code = exc.stdout or b"", -1
        lines = normalise(out.decode("utf-8", errors="replace")[:MAX_OUTPUT])
        return {"lines": lines, "fs": manifest(fs_root), "exit": code}


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


def check() -> int:
    # Every reference must work, give the same result twice, and not be matched by doing nothing.
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


def main() -> None:
    import pandas as pd

    prompts = load_prompts()
    items = [{"index": i, "id": p["id"], "nl": p["request"]} for i, p in enumerate(prompts)]
    for name in MODELS:
        answer_all(name, items, RESULTS / "answers" / f"{name}.jsonl")

    references = reference_runs(prompts)
    correct, rows = {}, []
    (RESULTS / "scored").mkdir(parents=True, exist_ok=True)
    for name in MODELS:
        frame = pd.read_json(RESULTS / "answers" / f"{name}.jsonl", lines=True).set_index("index").sort_index()
        frame["correct"] = [is_correct(command, prompts[i], references[i]) for i, command in frame.command.items()]
        frame["category"] = [prompts[i]["category"] for i in frame.index]
        frame[["id", "category", "nl", "command", "correct"]].to_json(
            RESULTS / "scored" / f"{name}.jsonl", orient="records", lines=True)
        correct[name] = frame.correct.astype(bool)
        rows.append({"model": name, "n": len(frame), "accuracy": frame.correct.mean(),
                     **frame.groupby("category").correct.mean().to_dict()})
    tests = []
    for a_name, b_name in PAIRS:
        a_only, b_only, p = mcnemar(correct[a_name], correct[b_name])
        tests.append({"A": a_name, "B": b_name, "accuracy A": correct[a_name].mean(),
                      "accuracy B": correct[b_name].mean(), "only A right": a_only, "only B right": b_only,
                      "p_value": p})
    text = "\n".join(["## Accuracy", "", pd.DataFrame(rows).to_markdown(index=False, floatfmt=".3f"), "",
                      "## Paired McNemar tests", "", pd.DataFrame(tests).to_markdown(index=False, floatfmt=".3f"), ""])
    (RESULTS / "report.md").write_text(text)
    print(text)


def overlap(train_csv: Path = TRAINING_DATA) -> None:
    # Requests that match, or nearly match, a request the model was fine-tuned on.
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
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command == "run":
        main()
    elif command == "check":
        sys.exit(check())
    elif command == "overlap":
        overlap()
    else:
        print("usage: run.py [run|check|overlap]")
        sys.exit(2)

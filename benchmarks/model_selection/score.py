"""Score model predictions against NL2SH-ALFA references by executing them.

A prediction counts as correct when, run on a fresh copy of the test filesystem,
it leaves the same files behind as one of the two reference commands AND prints
the same output (strict), or the same lines in any order (lenient).

Gold runs are cached in results/gold_runs.json because every model shares them.
Usage: uv run python score.py results/preds/*.jsonl
"""

import json
import re
import shlex
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

import sandbox

HERE = Path(__file__).parent
DATA = HERE.parents[1] / "data" / "raw" / "test.csv"
RESULTS = HERE / "results"
GOLD_CACHE = RESULTS / "gold_runs.json"


def _key(r: sandbox.RunResult) -> dict:
    out = sandbox.normalize_output(r.output)
    return {
        "out": out,
        "lines": sorted(out.splitlines()),
        "fs": json.dumps(sorted(r.manifest.items())),
        "exit": r.exit_code,
    }


def gold_runs(test: pd.DataFrame) -> list[dict]:
    if GOLD_CACHE.exists():
        return json.loads(GOLD_CACHE.read_text())
    sandbox.build_templates()
    runs = []
    for i, row in test.iterrows():
        fs = sandbox.fs_for_index(i)
        refs = [_key(sandbox.run(c, fs)) for c in (row.bash, row.bash2)]
        runs.append({"fs_num": fs, "refs": refs})
    # Second pass, a minute later: a reference whose result changes between runs
    # (date, uptime, free, ps) can't be scored by execution, so it is marked unstable.
    for i, row in test.iterrows():
        again = _key(sandbox.run(row.bash, runs[i]["fs_num"]))
        first = runs[i]["refs"][0]
        runs[i]["stable"] = again["lines"] == first["lines"] and again["fs"] == first["fs"]
    # Items a do-nothing command passes (no output, no file change) are "trivial":
    # execution can't tell a right answer from a wrong one there.
    for i in range(len(test)):
        noop = _key(sandbox.run("true", runs[i]["fs_num"]))
        runs[i]["trivial"] = any(
            noop["fs"] == g["fs"] and noop["lines"] == g["lines"] for g in runs[i]["refs"]
        )
    RESULTS.mkdir(exist_ok=True)
    GOLD_CACHE.write_text(json.dumps(runs))
    return runs


def first_utility(cmd: str) -> str:
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        tokens = cmd.split()
    for tok in tokens:
        if tok in ("sudo", "env", "time", "nohup") or re.match(r"^\w+=", tok):
            continue
        return tok.split("/")[-1]
    return ""


def norm_cmd(cmd: str) -> str:
    return re.sub(r"\s+", " ", cmd.strip())


def syntax_ok(cmd: str) -> bool:
    return subprocess.run(["bash", "-n", "-c", cmd], capture_output=True).returncode == 0


def score_one(pred: str, row, gold: dict) -> dict:
    refs = [row.bash, row.bash2]
    p = _key(sandbox.run(pred, gold["fs_num"])) if pred.strip() else None
    strict = lenient = fs_ok = False
    if p is not None:
        for g in gold["refs"]:
            same_fs = p["fs"] == g["fs"]
            fs_ok |= same_fs
            strict |= same_fs and p["out"] == g["out"]
            lenient |= same_fs and p["lines"] == g["lines"]
    return {
        "exact": any(norm_cmd(pred) == norm_cmd(r) for r in refs),
        "utility": first_utility(pred) in {first_utility(r) for r in refs},
        "syntax": bool(pred.strip()) and syntax_ok(pred),
        "exec_strict": strict,
        "exec_lenient": lenient or strict,
        "fs_match": fs_ok,
        "pred_out": p["out"][:300] if p else "",
    }


def score_file(path: Path, test: pd.DataFrame, golds: list[dict]) -> pd.DataFrame:
    preds = [json.loads(line) for line in path.read_text().splitlines()]
    rows = []
    for rec in preds:
        i = rec["index"]
        row = test.iloc[i]
        s = score_one(rec["command"], row, golds[i])
        rows.append({**rec, **s, "difficulty": int(row.difficulty),
                     "stable": golds[i]["stable"], "trivial": golds[i]["trivial"]})
    return pd.DataFrame(rows)


def summarize(df: pd.DataFrame) -> dict:
    stable = df[df.stable]
    hard_to_fake = stable[~stable.trivial]
    return {
        "n": len(df),
        "exec_lenient": stable.exec_lenient.mean(),
        "exec_nontrivial": hard_to_fake.exec_lenient.mean(),
        "exec_strict": stable.exec_strict.mean(),
        "exec_easy": stable[stable.difficulty == 0].exec_lenient.mean(),
        "exec_medium": stable[stable.difficulty == 1].exec_lenient.mean(),
        "exec_hard": stable[stable.difficulty == 2].exec_lenient.mean(),
        "exact": df.exact.mean(),
        "utility": df.utility.mean(),
        "syntax": df.syntax.mean(),
        "format_errors": df.format_error.mean() if "format_error" in df else float("nan"),
        "sec_per_query": df.latency_s.mean() if "latency_s" in df else float("nan"),
        "tok_per_s": df.tok_per_s.mean() if "tok_per_s" in df else float("nan"),
    }


def main(paths: list[str]) -> None:
    test = pd.read_csv(DATA)
    golds = gold_runs(test)
    print(f"stable references: {sum(g['stable'] for g in golds)}/{len(golds)}, "
          f"trivial: {sum(g['trivial'] for g in golds)}")
    summary = []
    for p in map(Path, paths):
        df = score_file(p, test, golds)
        df.to_json(RESULTS / "scored" / f"{p.stem}.jsonl", orient="records", lines=True)
        summary.append({"model": p.stem, **summarize(df)})
        print(f"scored {p.stem}")
    table = pd.DataFrame(summary).sort_values("exec_lenient", ascending=False)
    table.to_csv(RESULTS / "summary.csv", index=False)
    print(table.to_markdown(index=False, floatfmt=".3f"))


if __name__ == "__main__":
    (RESULTS / "scored").mkdir(parents=True, exist_ok=True)
    main(sys.argv[1:])

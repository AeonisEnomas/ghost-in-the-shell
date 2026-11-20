"""Round 4: score the round 4 fine-tune against its base on NL2SH-ALFA.

Differences from round 3, following an audit of the harness:

- The test filesystems and the reference results are rebuilt in this session
  and every model is scored against them straight away. The cached reference
  results from round 1 had gone stale: some prompts depend on file ages or on
  the state of the machine.
- Both reference commands are checked for stability, not only the first.
- Accuracy is reported twice: on the round 1-3 definition of a scoreable
  prompt, and on a stricter "clean" set that also drops prompts where the
  second reference is unstable or where both references fail in the sandbox
  (missing tools, no network), since those compare error messages.

Expects in models/ the two files exported by training/round4/finetune.ipynb.
Earlier predictions (original base file, round 3 fine-tune) are re-scored
against the same fresh references for comparison.

Usage: uv run python round4_eval.py
"""

import json
from pathlib import Path

import pandas as pd

import sandbox
import score
from generate import DATA, SYSTEM_PROMPT
from round2 import run_task, with_server
from round2_report import mcnemar

HERE = Path(__file__).parent
MODEL_DIR = HERE.parents[1] / "models"
OUT = HERE / "results" / "round4"
PRED_DIR = OUT / "preds"

NEW = {
    "base-r4": MODEL_DIR / "qwen2.5-coder-1.5b-base-r4.Q4_K_M.gguf",
    "ft-r4": MODEL_DIR / "qwen2.5-coder-1.5b-ft-r4.Q4_K_M.gguf",
}
EARLIER = {
    "base (original Qwen file)": score.RESULTS / "preds" / "qwen2.5-coder-1.5b.jsonl",
    "ft-r3": score.RESULTS / "round3" / "preds" / "qwen2.5-coder-1.5b-ft__zeroshot.jsonl",
}
PAIRS = [("base-r4", "ft-r4"), ("base (original Qwen file)", "ft-r4"), ("ft-r3", "ft-r4"),
         ("base-r4", "base (original Qwen file)")]


def generate(test: pd.DataFrame) -> None:
    items = [{"index": int(i), "nl": r.nl} for i, r in test.iterrows()]
    for name, gguf in NEW.items():
        if not gguf.exists():
            raise FileNotFoundError(f"{gguf} not found; copy it from the notebook's output folder")
        print(f"{name}: generating", flush=True)
        with_server(None, str(gguf), lambda name=name: run_task(
            PRED_DIR / f"{name}.jsonl", items, lambda it: (SYSTEM_PROMPT, it["nl"], 128, True)))


def run_references(test: pd.DataFrame) -> list[dict]:
    runs = []
    for i, row in test.iterrows():
        fs = sandbox.fs_for_index(i)
        refs = [sandbox.run(c, fs) for c in (row.bash, row.bash2)]
        runs.append({"fs_num": fs, "refs": [score._key(r) for r in refs]})
    return runs


def same(a: dict, b: dict) -> bool:
    return a["lines"] == b["lines"] and a["fs"] == b["fs"]


def mark(golds: list[dict], again: list[dict]) -> None:
    """Label each prompt, given a second run of the references made after scoring."""
    for gold, later in zip(golds, again):
        first_stable = same(gold["refs"][0], later["refs"][0])
        both_stable = first_stable and same(gold["refs"][1], later["refs"][1])
        noop = score._key(sandbox.run("true", gold["fs_num"]))
        gold["stable"] = first_stable                           # the round 1-3 definition
        gold["trivial"] = any(same(noop, ref) for ref in gold["refs"])
        both_fail = all(ref["exit"] != 0 for ref in gold["refs"])
        gold["clean"] = both_stable and not gold["trivial"] and not both_fail


def report(test: pd.DataFrame, golds: list[dict], frames: dict[str, pd.DataFrame]) -> str:
    scoreable = pd.Series([g["stable"] and not g["trivial"] for g in golds])
    clean = pd.Series([g["clean"] for g in golds])
    rows, right = [], {}
    for name, df in frames.items():
        ok = df.set_index("index").exec_lenient.astype(bool)
        right[name] = ok
        s, c = ok[scoreable[ok.index]], ok[clean[ok.index]]
        diff = test.difficulty[c.index]
        rows.append({"model": name, "accuracy": s.mean(), "clean accuracy": c.mean(),
                     "easy": c[diff == 0].mean(), "medium": c[diff == 1].mean(), "hard": c[diff == 2].mean()})
    out = [f"## Accuracy ({int(scoreable.sum())} scoreable prompts; {int(clean.sum())} in the clean set)", "",
           "Easy, medium and hard are over the clean set.", "",
           pd.DataFrame(rows).to_markdown(index=False, floatfmt=".3f"), ""]
    tests = []
    for a_name, b_name in PAIRS:
        for label, keep in (("scoreable", scoreable), ("clean", clean)):
            a, b = right[a_name][keep[right[a_name].index]].align(
                right[b_name][keep[right[b_name].index]], join="inner")
            a_only, b_only, p = mcnemar(a, b)
            tests.append({"A": a_name, "B": b_name, "set": label, "accuracy A": a.mean(),
                          "accuracy B": b.mean(), "only A right": a_only, "only B right": b_only,
                          "p_value": p})
    out += ["## Paired McNemar tests", "",
            pd.DataFrame(tests).to_markdown(index=False, floatfmt=".3f"), ""]
    return "\n".join(out)


def main() -> None:
    PRED_DIR.mkdir(parents=True, exist_ok=True)
    test = pd.read_csv(DATA)
    sandbox.build_templates(force=True)
    generate(test)

    golds = run_references(test)
    frames = {name: score.score_file(PRED_DIR / f"{name}.jsonl", test,
                                     [{**g, "stable": True, "trivial": False} for g in golds])
              for name in NEW}
    frames |= {name: score.score_file(path, test, [{**g, "stable": True, "trivial": False} for g in golds])
               for name, path in EARLIER.items()}
    mark(golds, run_references(test))

    labels = [{k: g[k] for k in ("fs_num", "stable", "trivial", "clean")} for g in golds]
    (OUT / "prompt_labels.json").write_text(json.dumps(labels))
    for name, df in frames.items():
        slug = name.split(" ")[0]
        df[["index", "nl", "command", "exec_lenient", "exec_strict"]].to_json(
            OUT / f"{slug}__scored.jsonl", orient="records", lines=True)
    text = report(test, golds, frames)
    (OUT / "report.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()

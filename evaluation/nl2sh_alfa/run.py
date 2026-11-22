# Test the models on NL2SH-ALFA, the public benchmark (300 prompts).

import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))

import sandbox
import score
from common import MODELS, PAIRS, answer_all, mcnemar

TEST_SET = HERE.parents[1] / "data" / "nl2sh_alfa" / "test.csv"
RESULTS = HERE / "results"


def run_references(test: pd.DataFrame) -> list[dict]:
    runs = []
    for i, row in test.iterrows():
        fs_num = sandbox.fs_for_index(i)
        runs.append({"fs_num": fs_num, "refs": [score.effect(c, fs_num) for c in (row.bash, row.bash2)]})
    return runs


def label_prompts(references: list[dict], again: list[dict]) -> pd.DataFrame:
    # Which prompts can be scored, given a second run of the references made after scoring.
    rows = []
    for first, later in zip(references, again):
        nothing = score.effect("true", first["fs_num"])
        first_stable = score.same(first["refs"][0], later["refs"][0])
        both_stable = first_stable and score.same(first["refs"][1], later["refs"][1])
        trivial = any(score.same(nothing, ref) for ref in first["refs"])
        both_fail = all(ref["exit"] != 0 for ref in first["refs"])
        rows.append({"scoreable": first_stable and not trivial,
                     "clean": both_stable and not trivial and not both_fail})
    return pd.DataFrame(rows)


def report(test: pd.DataFrame, labels: pd.DataFrame, correct: dict[str, pd.Series]) -> str:
    scoreable, clean = labels.scoreable, labels.clean
    rows = []
    for name, right in correct.items():
        in_clean = right[clean]
        level = test.difficulty[clean]
        rows.append({"model": name, "accuracy": right[scoreable].mean(), "clean accuracy": in_clean.mean(),
                     "easy": in_clean[level == 0].mean(), "medium": in_clean[level == 1].mean(),
                     "hard": in_clean[level == 2].mean()})
    out = [f"## Accuracy ({int(scoreable.sum())} scoreable prompts; {int(clean.sum())} in the clean set)", "",
           "Easy, medium and hard are over the clean set.", "",
           pd.DataFrame(rows).to_markdown(index=False, floatfmt=".3f"), ""]
    tests = []
    for a_name, b_name in PAIRS:
        for label, keep in (("scoreable", scoreable), ("clean", clean)):
            a, b = correct[a_name][keep], correct[b_name][keep]
            a_only, b_only, p = mcnemar(a, b)
            tests.append({"A": a_name, "B": b_name, "set": label, "accuracy A": a.mean(), "accuracy B": b.mean(),
                          "only A right": a_only, "only B right": b_only, "p_value": p})
    out += ["## Paired McNemar tests", "", pd.DataFrame(tests).to_markdown(index=False, floatfmt=".3f"), ""]
    return "\n".join(out)


def main() -> None:
    test = pd.read_csv(TEST_SET)
    items = [{"index": int(i), "nl": row.nl} for i, row in test.iterrows()]
    for name in MODELS:
        answer_all(name, items, RESULTS / "answers" / f"{name}.jsonl")

    sandbox.build_filesystems()
    references = run_references(test)
    correct = {}
    (RESULTS / "scored").mkdir(parents=True, exist_ok=True)
    for name in MODELS:
        answers = pd.read_json(RESULTS / "answers" / f"{name}.jsonl", lines=True).set_index("index").sort_index()
        answers["correct"] = [score.is_correct(command, references[i]["fs_num"], references[i]["refs"])
                              for i, command in answers.command.items()]
        correct[name] = answers.correct.astype(bool)
        answers.reset_index()[["index", "nl", "command", "correct"]].to_json(
            RESULTS / "scored" / f"{name}.jsonl", orient="records", lines=True)
    labels = label_prompts(references, run_references(test))

    labels.to_json(RESULTS / "prompt_labels.json", orient="records")
    text = report(test, labels, correct)
    (RESULTS / "report.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()

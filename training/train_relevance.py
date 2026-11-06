"""Train the relevance classifier (is a request a shell task?).

Data
- Shell tasks: 12,000 requests sampled from the NL2SH-ALFA training split, plus
  data/relevance/train_positive.txt (casual phrasings written for this project).
- Not shell tasks: Dolly-15k instructions (CC BY-SA 3.0) with any instruction
  mentioning Linux, shells, files or folders removed, plus
  data/relevance/train_negative.txt (chit-chat, general coding questions,
  attempts to address the model).

The data are split 80/10/10, stratified. The threshold is chosen on the
validation split as the highest one that still accepts 99% of shell tasks:
wrongly refusing a real task costs the user more than letting an off-topic
request through, which the safety check and the "continue anyway" button
cover. Final numbers are reported on the test split and on handwritten sets
never used in training.

Usage: uv run python training/train_relevance.py
"""

import json
import re
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import classification_report, confusion_matrix, precision_recall_curve
from sklearn.model_selection import train_test_split

from ghost_in_the_shell.relevance import build_pipeline

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT_MODEL = ROOT / "models" / "relevance.joblib"
OUT_REPORT = ROOT / "training" / "relevance_report.json"
SEED = 42
POSITIVES = 12_000
MIN_RECALL = 0.99

SHELL_WORDS = re.compile(
    r"linux|unix|bash|shell|terminal|command[ -]line|ubuntu|director(y|ies)|folder|grep|sudo|"
    r"chmod|file ?system|\bfiles?\b|script|server|process", re.IGNORECASE)


def lines(name: str) -> list[str]:
    return [l.strip() for l in (DATA / "relevance" / name).read_text().splitlines() if l.strip()]


def load() -> pd.DataFrame:
    train = pd.read_csv(DATA / "raw" / "train.csv")
    test = pd.read_csv(DATA / "raw" / "test.csv")
    held_out = set(test.nl.str.lower().str.strip())
    nl = train.nl.dropna().astype(str).str.strip()
    nl = nl[~nl.str.lower().isin(held_out)].drop_duplicates()
    positives = nl.sample(POSITIVES, random_state=SEED).tolist() + lines("train_positive.txt")

    dolly_path = DATA / "raw" / "dolly" / "databricks-dolly-15k.jsonl"
    if not dolly_path.exists():
        from huggingface_hub import hf_hub_download
        hf_hub_download("databricks/databricks-dolly-15k", dolly_path.name, repo_type="dataset",
                        local_dir=dolly_path.parent)
    dolly = [json.loads(l)["instruction"].strip() for l in open(dolly_path)]
    negatives = [d for d in dict.fromkeys(dolly) if d and not SHELL_WORDS.search(d)]
    negatives += lines("train_negative.txt")
    return pd.DataFrame({"text": positives + negatives,
                         "label": [1] * len(positives) + [0] * len(negatives)})


def main() -> None:
    data = load()
    train, rest = train_test_split(data, test_size=0.2, stratify=data.label, random_state=SEED)
    val, test = train_test_split(rest, test_size=0.5, stratify=rest.label, random_state=SEED)
    print(f"train {len(train):,}  val {len(val):,}  test {len(test):,}  "
          f"(shell tasks {data.label.sum():,}, others {(data.label == 0).sum():,})")

    pipeline = build_pipeline().fit(train.text, train.label)

    val_scores = pipeline.predict_proba(val.text)[:, 1]
    _, recall, thresholds = precision_recall_curve(val.label, val_scores)
    ok = np.where(recall[:-1] >= MIN_RECALL)[0]
    threshold = float(thresholds[ok[-1]]) if len(ok) else 0.5
    print(f"threshold {threshold:.3f} (validation recall >= {MIN_RECALL})")

    def evaluate(texts, labels):
        scores = pipeline.predict_proba(list(texts))[:, 1]
        predicted = (scores >= threshold).astype(int)
        return predicted, scores

    report = {"threshold": threshold, "sizes": {"train": len(train), "val": len(val), "test": len(test)}}
    predicted, _ = evaluate(test.text, test.label)
    report["test"] = classification_report(test.label, predicted, output_dict=True, digits=4)
    report["test_confusion"] = confusion_matrix(test.label, predicted).tolist()
    print(classification_report(test.label, predicted, target_names=["other", "shell task"], digits=3))

    nl2sh_test = pd.read_csv(DATA / "raw" / "test.csv").nl.tolist()
    risky = json.loads((ROOT / "benchmarks" / "model_selection" / "risky_prompts.json").read_text())
    held = {
        "nl2sh_test (should accept)": (nl2sh_test, 1),
        "risky prompts (should accept)": (risky, 1),
        "handwritten shell tasks (should accept)": (lines("eval_positive.txt"), 1),
        "handwritten other (should reject)": (lines("eval_negative.txt"), 0),
    }
    report["held_out"] = {}
    for name, (texts, label) in held.items():
        predicted, scores = evaluate(texts, [label] * len(texts))
        rate = float((predicted == label).mean())
        report["held_out"][name] = {"n": len(texts), "correct": rate,
                                    "errors": [t for t, p in zip(texts, predicted) if p != label]}
        print(f"{name:42} {rate:6.1%} of {len(texts)}")
    borderline = lines("eval_borderline.txt")
    _, scores = evaluate(borderline, [0] * len(borderline))
    report["borderline"] = {t: round(float(s), 3) for t, s in zip(borderline, scores)}

    OUT_MODEL.parent.mkdir(exist_ok=True)
    joblib.dump({"pipeline": pipeline, "threshold": threshold}, OUT_MODEL)
    OUT_REPORT.write_text(json.dumps(report, indent=2))
    print(f"saved {OUT_MODEL} and {OUT_REPORT}")


if __name__ == "__main__":
    main()

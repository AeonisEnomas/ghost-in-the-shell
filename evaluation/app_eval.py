"""End-to-end evaluation of the finished app (not just the model).

1. Accuracy of the full pipeline on the NL2SH-ALFA test set (one-line grammar,
   validation, up to two extra samples when a command is invalid), scored with
   the same execution scorer as model selection.
2. The relevance gate (classifier + injection phrases) on held-out sets.
3. The safety check: risk levels of the 300 reference commands, and of every
   destructive command the models produced on the risky prompts.
4. An attack suite (data/eval/injection_attacks.json) through the real
   pipeline: is the request stopped at the gate, and if the user continues
   anyway, what command comes out and what risk level is shown?
5. Latency of each stage.

Usage, from the project root:  uv run python evaluation/app_eval.py
Saved work is reused, so the script can be stopped and resumed.
"""

import json
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "benchmarks" / "model_selection"
sys.path.insert(0, str(BENCH))

import score  # noqa: E402  (benchmark scorer)
from round2_report import destructive_reason, mcnemar, scored  # noqa: E402

from ghost_in_the_shell.config import Settings  # noqa: E402
from ghost_in_the_shell.model import Models  # noqa: E402
from ghost_in_the_shell.pipeline import Assistant  # noqa: E402
from ghost_in_the_shell.relevance import RelevanceChecker  # noqa: E402
from ghost_in_the_shell.safety import Level, assess  # noqa: E402
from ghost_in_the_shell.sanitize import clean_request, manipulation_signs  # noqa: E402

OUT = ROOT / "evaluation" / "results"
PIPELINE_PREDS = OUT / "pipeline_zeroshot.jsonl"
ATTACKS_OUT = OUT / "attacks.json"
FT_PREDS = BENCH / "results" / "round3" / "preds" / "qwen2.5-coder-1.5b-ft__zeroshot.jsonl"


def run_pipeline(assistant: Assistant, test: pd.DataFrame, folder: Path) -> None:
    done = set()
    if PIPELINE_PREDS.exists():
        done = {json.loads(l)["index"] for l in PIPELINE_PREDS.read_text().splitlines()}
    with PIPELINE_PREDS.open("a") as out:
        for index, row in test.iterrows():
            if index in done:
                continue
            start = time.perf_counter()
            outcome = assistant.ask(row.nl, folder, force=True)
            total = time.perf_counter() - start
            review = outcome.review
            out.write(json.dumps({
                "index": int(index), "nl": row.nl,
                "command": review.command if review else "",
                "status": outcome.status, "attempts": outcome.attempts,
                "generation_s": round(outcome.generation_seconds, 3),
                "preview_s": round(review.preview.seconds, 3) if review else None,
                "latency_s": round(total, 3),
                "level": review.assessment.level.name if review else None,
                "issues": list(review.issues) if review else [],
            }) + "\n")
            out.flush()
            if index % 50 == 0:
                print(f"  pipeline {index}/300", flush=True)


def run_attacks(assistant: Assistant, folder: Path) -> list[dict]:
    if ATTACKS_OUT.exists():
        return json.loads(ATTACKS_OUT.read_text())
    attacks = json.loads((ROOT / "data" / "eval" / "injection_attacks.json").read_text())
    results = []
    for attack in attacks:
        gate = assistant.ask(attack["prompt"], folder)
        forced = assistant.ask(attack["prompt"], folder, force=True)
        review = forced.review
        results.append({
            **attack,
            "gate": gate.status,
            "gate_reason": gate.message,
            "forced_status": forced.status,
            "command": review.command if review else "",
            "level": review.assessment.level.name if review else None,
            "findings": [f.title for f in review.assessment.findings] if review else [],
            "destructive_pattern": destructive_reason(review.command) if review else None,
        })
    ATTACKS_OUT.write_text(json.dumps(results, indent=1, ensure_ascii=False))
    return results


def table(df: pd.DataFrame) -> str:
    return df.to_markdown(index=False, floatfmt=".3f")


def report(test: pd.DataFrame, relevance: RelevanceChecker, attacks: list[dict]) -> str:
    golds = score.gold_runs(test)
    out = ["# App evaluation", ""]

    # 1. accuracy
    pipe = scored(PIPELINE_PREDS, test, golds)
    ft = scored(FT_PREDS, test, golds)
    a, b = ft.exec_lenient.align(pipe.exec_lenient, join="inner")
    only_ft, only_pipe, p = mcnemar(a.astype(bool), b.astype(bool))
    rows = [{"system": "fine-tuned 1.5B alone (round 3)", "accuracy": a.mean(),
             "sec_per_answer": ft.latency_s.mean()},
            {"system": "full app pipeline", "accuracy": b.mean(),
             "sec_per_answer": pipe.latency_s.mean()}]
    raw = [json.loads(l) for l in PIPELINE_PREDS.read_text().splitlines()]
    retried = [r for r in raw if r["attempts"] > 1]
    out += ["## 1. Accuracy on NL2SH-ALFA (275 scoreable prompts)", "", table(pd.DataFrame(rows)), "",
            f"Paired McNemar: only the model alone right {only_ft}, only the pipeline right {only_pipe}, "
            f"p = {p:.3f}. The pipeline sampled extra candidates for {len(retried)} of {len(raw)} prompts "
            f"(syntax error or a missing program in the first answer); "
            f"{sum(1 for r in raw if r['issues'])} final answers still had a validation issue, "
            f"which the app shows to the user.", ""]

    # 2. relevance gate
    data = ROOT / "data" / "relevance"
    sets = {
        "NL2SH-ALFA test prompts (300)": (test.nl.tolist(), True),
        "risky prompts (50)": (json.loads((BENCH / "risky_prompts.json").read_text()), True),
        "handwritten shell tasks (30)": ((data / "eval_positive.txt").read_text().splitlines(), True),
        "handwritten other requests (30)": ((data / "eval_negative.txt").read_text().splitlines(), False),
        "attack suite (24)": ([x["prompt"] for x in attacks], None),
    }
    rows = []
    for name, (texts, should_pass) in sets.items():
        texts = [t for t in texts if t.strip()]
        checks = [relevance.check(clean_request(t)) for t in texts]
        classifier_pass = sum(c.on_topic for c in checks)
        gate_pass = sum(c.on_topic and not c.injection_phrases and not manipulation_signs(t)
                        for c, t in zip(checks, texts))
        rows.append({"set": name, "n": len(texts),
                     "classifier accepts": classifier_pass / len(texts),
                     "gate accepts (classifier, no injection phrase, no hidden content)": gate_pass / len(texts),
                     "expected": {True: "accept", False: "stop", None: "-"}[should_pass]})
    out += ["## 2. Relevance gate", "", table(pd.DataFrame(rows)), ""]

    # 3. safety check
    levels = Counter(assess(c).level.name for c in test.bash)
    dangerous_refs = [c for c in test.bash if assess(c).level is Level.DANGER]
    risky_files = sorted((BENCH / "results").glob("round*/*__risky.jsonl"))
    flagged, caught, danger = 0, 0, 0
    for path in risky_files:
        for line in path.read_text().splitlines():
            command = json.loads(line)["command"]
            if destructive_reason(command):
                flagged += 1
                level = assess(command).level
                caught += level >= Level.CAUTION
                danger += level is Level.DANGER
    out += ["## 3. Safety check", "",
            "Risk levels given to the 300 reference commands (written by people, mostly harmless):", "",
            table(pd.DataFrame([{"level": k, "count": levels.get(k, 0)} for k in Level.__members__])), "",
            f"Reference commands rated Dangerous: {len(dangerous_refs)}: "
            + "; ".join(f"`{c}`" for c in dangerous_refs), "",
            f"Destructive commands produced by the models on the risky prompts "
            f"({len(risky_files)} model runs, found with the round 2 patterns): {flagged}. "
            f"Rated Caution or Dangerous: {caught} ({caught / flagged:.0%}); "
            f"rated Dangerous: {danger}.", ""]

    # 4. attacks
    rows = [{"category": x["category"], "prompt": x["prompt"].replace("\n", "\\n")[:70],
             "gate": "stopped" if x["gate"] == "off_topic" else x["gate"],
             "command if forced": x["command"][:60], "risk shown": x["level"]} for x in attacks]
    stopped = sum(x["gate"] == "off_topic" for x in attacks)
    harmful = [x for x in attacks if x["level"] in ("CAUTION", "DANGER")]
    unflagged = [x for x in attacks if x["destructive_pattern"] and x["level"] not in ("CAUTION", "DANGER")]
    out += ["## 4. Attack suite", "",
            f"{stopped} of {len(attacks)} attacks stopped at the gate. Forced past the gate, "
            f"{len(harmful)} produced a command rated Caution or Dangerous; "
            f"commands matching the round 2 destructive patterns but rated below Caution: {len(unflagged)}"
            + (": " + "; ".join(f"`{x['command']}`" for x in unflagged) if unflagged else "") + ".", "",
            table(pd.DataFrame(rows)), ""]

    # 5. latency
    lat = pd.DataFrame(raw)
    out += ["## 5. Latency (laptop CPU, per request)", "",
            table(pd.DataFrame([{
                "stage": "write command (incl. retries)", "mean_s": lat.generation_s.mean(),
                "p90_s": lat.generation_s.quantile(0.9)},
                {"stage": "sandbox dry run", "mean_s": lat.preview_s.mean(), "p90_s": lat.preview_s.quantile(0.9)},
                {"stage": "whole request", "mean_s": lat.latency_s.mean(), "p90_s": lat.latency_s.quantile(0.9)},
            ])), ""]
    return "\n".join(out)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    test = pd.read_csv(score.DATA)
    settings = Settings()
    relevance = RelevanceChecker.load(settings.models_dir / "relevance.joblib")
    with tempfile.TemporaryDirectory() as tmp, Models(settings) as models:
        folder = Path(tmp)
        (folder / "notes.txt").write_text("example\n")
        assistant = Assistant(models, relevance)
        print("pipeline on the test set", flush=True)
        run_pipeline(assistant, test, folder)
        print("attack suite", flush=True)
        attacks = run_attacks(assistant, folder)
    text = report(test, relevance, attacks)
    (OUT / "report.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()

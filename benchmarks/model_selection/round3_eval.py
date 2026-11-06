"""Round 3: evaluate the fine-tuned models and apply the pre-registered decision rule.

Expects the GGUF files exported by training/round3_finetune.ipynb in models/.
Each fine-tuned model is run through the same tests as round 2 (300 test
prompts zero-shot, 50 risky prompts, 60 explain-mode commands with the base
Qwen2.5-Coder-3B translating explanations back into commands), on the same
llama.cpp runtime and Q4_K_M quantisation as its base model.

Decision rule (fixed 2026-11-06, before any fine-tuning):
  keep the 3B model only if, after fine-tuning, it beats the 1.5B model by
  at least 5 points of execution accuracy AND the paired McNemar test gives
  p < 0.05. Otherwise ship the 1.5B model alone.

Usage: uv run python round3_eval.py
"""

import json
from pathlib import Path

import pandas as pd

import score
from generate import DATA, MODELS, SYSTEM_PROMPT
from round2 import EXPLAIN_SYSTEM, explain_items, run_task, with_server
from round2_report import destructive_reason, mcnemar, scored

HERE = Path(__file__).parent
MODEL_DIR = HERE.parents[1] / "models"
OUT = HERE / "results" / "round3"
PRED_DIR = OUT / "preds"

FINE_TUNED = {
    "qwen2.5-coder-1.5b-ft": ("qwen2.5-coder-1.5b", MODEL_DIR / "qwen2.5-coder-1.5b-ft.Q4_K_M.gguf"),
    "qwen2.5-coder-3b-ft": ("qwen2.5-coder-3b", MODEL_DIR / "qwen2.5-coder-3b-ft.Q4_K_M.gguf"),
}
BACK_TRANSLATOR = "qwen2.5-coder-3b"   # base model, as in round 2
MIN_GAIN = 0.05
ALPHA = 0.05


def generate_all(test: pd.DataFrame) -> None:
    test_items = [{"index": int(i), "nl": r.nl} for i, r in test.iterrows()]
    risky = [{"index": i, "nl": p}
             for i, p in enumerate(json.loads((HERE / "risky_prompts.json").read_text()))]
    to_explain = explain_items(test)

    for name, (_, gguf) in FINE_TUNED.items():
        if not gguf.exists():
            raise FileNotFoundError(f"{gguf} not found; copy it from the notebook's output folder")
        print(f"{name}: starting", flush=True)

        def work(name=name):
            run_task(PRED_DIR / f"{name}__zeroshot.jsonl", test_items,
                     lambda it: (SYSTEM_PROMPT, it["nl"], 128, True))
            run_task(OUT / f"{name}__risky.jsonl", risky,
                     lambda it: (SYSTEM_PROMPT, it["nl"], 128, True))
            run_task(OUT / f"{name}__explain.jsonl", to_explain,
                     lambda it: (EXPLAIN_SYSTEM, it["bash"], 160, False))

        with_server(None, str(gguf), work)

    repo, file = MODELS[BACK_TRANSLATOR]
    print(f"{BACK_TRANSLATOR}: back-translating explanations", flush=True)

    def back_translate():
        for name in FINE_TUNED:
            lines = (OUT / f"{name}__explain.jsonl").read_text().splitlines()
            items = [{"index": json.loads(l)["index"], "explanation": json.loads(l)["raw"]} for l in lines]
            run_task(PRED_DIR / f"{name}__roundtrip.jsonl", items,
                     lambda it: (SYSTEM_PROMPT, it["explanation"], 128, True))

    with_server(repo, file, back_translate)


def report(test: pd.DataFrame) -> str:
    golds = score.gold_runs(test)
    base_dir = score.RESULTS / "preds"
    out = []

    acc, rows = {}, []
    for name, (base, _) in FINE_TUNED.items():
        for label, path in [(base, base_dir / f"{base}.jsonl"),
                            (name, PRED_DIR / f"{name}__zeroshot.jsonl")]:
            df = scored(path, test, golds)
            acc[label] = df.exec_lenient
            rows.append({
                "model": label, "accuracy": df.exec_lenient.mean(),
                "easy": df[df.difficulty == 0].exec_lenient.mean(),
                "medium": df[df.difficulty == 1].exec_lenient.mean(),
                "hard": df[df.difficulty == 2].exec_lenient.mean(),
                "sec_per_answer": df.latency_s.mean(),
            })
    out += ["## Accuracy, base vs fine-tuned (execution-checked, 275 scoreable prompts)", "",
            pd.DataFrame(rows).to_markdown(index=False, floatfmt=".3f"), ""]

    tests = []
    pairs = [(base, name) for name, (base, _) in FINE_TUNED.items()]
    pairs.append(tuple(FINE_TUNED))
    for a_name, b_name in pairs:
        a, b = acc[a_name].align(acc[b_name], join="inner")
        a_only, b_only, p = mcnemar(a.astype(bool), b.astype(bool))
        tests.append({"A": a_name, "B": b_name, "accuracy A": a.mean(),
                      "accuracy B": b.mean(), "only A right": a_only, "only B right": b_only,
                      "p_value": p})
    out += ["## Paired McNemar tests", "",
            pd.DataFrame(tests).to_markdown(index=False, floatfmt=".3f"), ""]

    risk_rows = []
    for name in FINE_TUNED:
        recs = [json.loads(l) for l in (OUT / f"{name}__risky.jsonl").read_text().splitlines()]
        hits = [(r["nl"], r["command"], destructive_reason(r["command"])) for r in recs]
        hits = [h for h in hits if h[2]]
        (OUT / f"{name}__risky_flagged.json").write_text(json.dumps(hits, indent=1))
        risk_rows.append({"model": name, "destructive": len(hits), "of": len(recs)})
    out += ["## Risky prompts (flagged for manual over-reach review)", "",
            pd.DataFrame(risk_rows).to_markdown(index=False), ""]

    ex_rows = []
    for name in FINE_TUNED:
        df = score.score_file(PRED_DIR / f"{name}__roundtrip.jsonl", test, golds)
        ex_rows.append({"model": name, "round_trip_accuracy": df.exec_lenient.mean()})
    out += ["## Explain mode (round-trip execution check)", "",
            pd.DataFrame(ex_rows).to_markdown(index=False, floatfmt=".3f"), ""]

    small, large = FINE_TUNED
    a, b = acc[small].align(acc[large], join="inner")
    gain = b.mean() - a.mean()
    p = mcnemar(a.astype(bool), b.astype(bool))[2]
    keep_large = gain >= MIN_GAIN and p < ALPHA
    verdict = ("Keep both: the fine-tuned 3B model is the 'accurate' option."
               if keep_large else "Ship the fine-tuned 1.5B model only.")
    out += ["## Decision", "",
            f"Fine-tuned 3B minus fine-tuned 1.5B: {gain * 100:+.1f} points, McNemar p = {p:.3f}.",
            f"Rule: keep 3B only if gain >= {MIN_GAIN * 100:.0f} points and p < {ALPHA}.",
            f"**{verdict}**", ""]
    return "\n".join(out)


def main() -> None:
    PRED_DIR.mkdir(parents=True, exist_ok=True)
    test = pd.read_csv(DATA)
    generate_all(test)
    text = report(test)
    (OUT / "report.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()

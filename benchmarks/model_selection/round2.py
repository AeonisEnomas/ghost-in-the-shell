"""Round 2: compare the three finalists under the conditions the app will use.

For each finalist this runs, with one llama-server start per model:
  fewshot      300 test prompts, system prompt + 5 worked examples
  fewshot_rag  same, plus the 2 most relevant tldr pages (BM25) in the request
  risky        50 ambiguous or risky requests, checked for destructive commands
  explain      60 reference commands explained in plain English
Then Qwen2.5-Coder-3B translates every explanation back into a command
(round trip) so explanation quality can be scored by execution, and the 1.5B
model is rerun zero-shot at Q8_0 to measure the cost of 4-bit quantisation.

Outputs go to results/round2/. Finished items are skipped on rerun.
Usage: uv run python round2.py
"""

import json
import re
import time
from pathlib import Path

import bm25s
import pandas as pd
import requests

from generate import DATA, MODELS, SYSTEM_PROMPT, URL, extract_command, start_server

HERE = Path(__file__).parent
OUT = HERE / "results" / "round2"
PRED_DIR = OUT / "preds"
TLDR_DIR = HERE.parents[1] / "data" / "raw" / "tldr" / "pages"

FINALISTS = ["qwen2.5-coder-1.5b", "gemma4-e2b", "qwen2.5-coder-3b"]
BACK_TRANSLATOR = "qwen2.5-coder-3b"
Q8_VARIANT = ("qwen2.5-coder-1.5b-q8", "Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF",
              "qwen2.5-coder-1.5b-instruct-q8_0.gguf")

# Exact pairs from the NL2SH-ALFA train split, checked not to overlap the test set.
FEW_SHOT = [
    ("Find all files in $dir directory (non-recursive) and count them",
     'find "$dir" -maxdepth 1 -type f | wc -l'),
    ('List the 10 largest files or directories and their sizes under (and including) "/var"',
     "du -a /var | sort -n -r | head -n 10"),
    ("Print the last column of each line in a file, using a comma (instead of space) as a field separator",
     "awk -F ',' '{print $NF}' path/to/file"),
    ('Find all files with the extension ".ext" and replace all occurrences of "foo" with "bar" in them.',
     'find . -name "*.ext" | xargs sed -i "s/foo/bar/g"'),
    ("Recursively finds all '*.png' files older than 50 days in a current folder and removes them.",
     'find . -name "*.png" -mtime +50 -exec rm {} \\;'),
]

FEW_SHOT_SYSTEM = SYSTEM_PROMPT + "\n\nExamples:\n" + "\n".join(
    f"Request: {nl}\nCommand: {cmd}" for nl, cmd in FEW_SHOT
)

EXPLAIN_SYSTEM = (
    "You explain Linux bash commands to a beginner. Describe in one or two plain-English "
    "sentences exactly what the command does, including what each flag and file path "
    "affects. Do not include the command itself or any code."
)


# ---------------------------------------------------------------- retrieval

def load_tldr() -> list[dict]:
    # Only pages for standard Linux tools (coreutils, findutils, grep, sed, gawk,
    # tar, procps, util-linux, ...), listed in core_commands.txt. With all ~6.8k
    # pages, niche CLIs (aws, kubectl, git-count-objects) crowd out du, find, tar.
    core = set((HERE / "core_commands.txt").read_text().split())
    pages, seen = [], set()
    for platform in ("linux", "common"):
        for md in sorted((TLDR_DIR / platform).glob("*.md")):
            if md.stem not in core or md.stem in seen:
                continue
            seen.add(md.stem)
            text = md.read_text()
            name = md.stem
            desc = " ".join(l[2:] for l in text.splitlines() if l.startswith("> ") and "More information" not in l)
            examples = re.findall(r"^- (.+?)\n\n`(.+?)`", text, re.M)
            pages.append({"name": name, "desc": desc, "examples": examples})
    return pages


class TldrRetriever:
    def __init__(self) -> None:
        self.pages = load_tldr()
        # Repeat the command name so a query mentioning "tar" finds the tar page.
        corpus = [
            f"{p['name']} {p['name']} {p['name']} {p['desc']} " + " ".join(d for d, _ in p["examples"])
            for p in self.pages
        ]
        self.index = bm25s.BM25()
        self.index.index(bm25s.tokenize(corpus, stopwords="en", show_progress=False), show_progress=False)

    def context(self, query: str, k: int = 2, max_examples: int = 6) -> str:
        docs, _ = self.index.retrieve(bm25s.tokenize([query], stopwords="en", show_progress=False),
                                      k=k, show_progress=False)
        blocks = []
        for i in docs[0]:
            p = self.pages[int(i)]
            lines = [f"# {p['name']}: {p['desc']}"]
            lines += [f"- {d.rstrip(':')}: {c}" for d, c in p["examples"][:max_examples]]
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)


# ---------------------------------------------------------------- generation

def chat(system: str, user: str, max_tokens: int = 128) -> dict:
    t0 = time.time()
    resp = requests.post(f"{URL}/v1/chat/completions", json={
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0, "max_tokens": max_tokens, "seed": 0,
    }, timeout=600).json()
    return {
        "raw": resp["choices"][0]["message"].get("content") or "",
        "latency_s": round(time.time() - t0, 3),
        "tok_per_s": round(resp.get("timings", {}).get("predicted_per_second", 0.0), 2),
        "prompt_tokens": resp.get("usage", {}).get("prompt_tokens"),
        "completion_tokens": resp.get("usage", {}).get("completion_tokens"),
    }


def run_task(path: Path, items: list[dict], build) -> None:
    """items: dicts with an "index" key; build(item) -> (system, user, max_tokens, is_command)."""
    done = set()
    if path.exists():
        done = {json.loads(l)["index"] for l in path.read_text().splitlines() if l.strip()}
    todo = [it for it in items if it["index"] not in done]
    if not todo:
        return
    print(f"  {path.stem}: {len(todo)} items", flush=True)
    with path.open("a") as fh:
        for n, item in enumerate(todo):
            system, user, max_tokens, is_command = build(item)
            rec = {**item, **chat(system, user, max_tokens)}
            if is_command:
                rec["command"], rec["format_error"] = extract_command(rec["raw"])
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            if n % 50 == 0:
                print(f"    {path.stem} {n}/{len(todo)} {rec['latency_s']}s", flush=True)


def with_server(repo: str, file: str, work) -> None:
    proc = start_server(repo, file)
    try:
        chat(SYSTEM_PROMPT, "list files")  # warm-up
        work()
    finally:
        proc.terminate()
        proc.wait(timeout=30)


def explain_items(test: pd.DataFrame) -> list[dict]:
    gold = json.loads((HERE / "results" / "gold_runs.json").read_text())
    usable = [i for i in range(len(test)) if gold[i]["stable"] and not gold[i]["trivial"]]
    picked = (test.loc[usable].groupby("difficulty", group_keys=False)
              .apply(lambda g: g.sample(20, random_state=0)))
    return [{"index": int(i), "nl": r.nl, "bash": r.bash} for i, r in picked.iterrows()]


def rag_sample(test: pd.DataFrame) -> set[int]:
    """50 prompts per difficulty level. RAG runs at 10-15 s per answer for the
    2-3B models on this CPU, so they are compared on this sample only."""
    picked = test.groupby("difficulty", group_keys=False).apply(lambda g: g.sample(50, random_state=1))
    return {int(i) for i in picked.index}


def main() -> None:
    PRED_DIR.mkdir(parents=True, exist_ok=True)
    test = pd.read_csv(DATA)
    retriever = TldrRetriever()
    test_items = [{"index": int(i), "nl": r.nl} for i, r in test.iterrows()]
    contexts = {it["index"]: retriever.context(it["nl"]) for it in test_items}
    risky = [{"index": i, "nl": p} for i, p in enumerate(json.loads((HERE / "risky_prompts.json").read_text()))]
    to_explain = explain_items(test)
    rag_subset = rag_sample(test)
    (OUT / "rag_contexts.json").write_text(json.dumps(contexts, indent=1))

    def finalist_work(name: str):
        def work():
            run_task(PRED_DIR / f"{name}__fewshot.jsonl", test_items,
                     lambda it: (FEW_SHOT_SYSTEM, it["nl"], 128, True))
            rag_items = test_items if name == "qwen2.5-coder-1.5b" else [
                it for it in test_items if it["index"] in rag_subset]
            run_task(PRED_DIR / f"{name}__fewshot_rag.jsonl", rag_items,
                     lambda it: (FEW_SHOT_SYSTEM,
                                 f"Relevant documentation:\n{contexts[it['index']]}\n\nRequest: {it['nl']}",
                                 128, True))
            run_task(OUT / f"{name}__risky.jsonl", risky,
                     lambda it: (SYSTEM_PROMPT, it["nl"], 128, True))
            run_task(OUT / f"{name}__explain.jsonl", to_explain,
                     lambda it: (EXPLAIN_SYSTEM, it["bash"], 160, False))
            if name == BACK_TRANSLATOR:
                for source in FINALISTS:
                    expl = {json.loads(l)["index"]: json.loads(l)["raw"]
                            for l in (OUT / f"{source}__explain.jsonl").read_text().splitlines()}
                    items = [{"index": i, "explanation": e} for i, e in expl.items()]
                    run_task(PRED_DIR / f"{source}__roundtrip.jsonl", items,
                             lambda it: (SYSTEM_PROMPT, it["explanation"], 128, True))
        return work

    # The back-translator goes last so every finalist's explanations exist.
    for name in sorted(FINALISTS, key=lambda n: n == BACK_TRANSLATOR):
        print(f"{name}: starting", flush=True)
        repo, file = MODELS[name]
        with_server(repo, file, finalist_work(name))

    name, repo, file = Q8_VARIANT
    print(f"{name}: starting", flush=True)
    with_server(repo, file, lambda: run_task(
        PRED_DIR / f"{name}__zeroshot.jsonl", test_items,
        lambda it: (SYSTEM_PROMPT, it["nl"], 128, True)))
    print("round 2 generation complete", flush=True)


if __name__ == "__main__":
    main()

"""Generate a bash command for every NL2SH-ALFA test prompt with each candidate model.

Each model runs locally on CPU through llama-server (llama.cpp), one at a time,
with the same system prompt, greedy decoding, and thinking turned off.
Predictions go to results/preds/<model>.jsonl; finished items are skipped on
rerun, so the script can be stopped and resumed.

Usage: uv run python generate.py [model-name ...]   (default: all models)
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).parent
DATA = HERE.parents[1] / "data" / "raw" / "test.csv"
PRED_DIR = HERE / "results" / "preds"
PORT = 8089
URL = f"http://127.0.0.1:{PORT}"

# name -> (Hugging Face repo, GGUF file). Models of 1B or less use Q8_0 because
# small models lose more accuracy at 4-bit; larger ones use Q4_K_M.
MODELS = {
    "qwen2.5-coder-0.5b": ("Qwen/Qwen2.5-Coder-0.5B-Instruct-GGUF", "qwen2.5-coder-0.5b-instruct-q8_0.gguf"),
    "qwen3.5-0.8b": ("unsloth/Qwen3.5-0.8B-GGUF", "Qwen3.5-0.8B-Q8_0.gguf"),
    "llama3.2-1b": ("bartowski/Llama-3.2-1B-Instruct-GGUF", "Llama-3.2-1B-Instruct-Q8_0.gguf"),
    "qwen2.5-coder-1.5b": ("Qwen/Qwen2.5-Coder-1.5B-Instruct-GGUF", "qwen2.5-coder-1.5b-instruct-q4_k_m.gguf"),
    "qwen3.5-2b": ("unsloth/Qwen3.5-2B-GGUF", "Qwen3.5-2B-Q4_K_M.gguf"),
    "gemma4-e2b": ("unsloth/gemma-4-E2B-it-GGUF", "gemma-4-E2B-it-Q4_K_M.gguf"),
    "qwen2.5-coder-3b": ("Qwen/Qwen2.5-Coder-3B-Instruct-GGUF", "qwen2.5-coder-3b-instruct-q4_k_m.gguf"),
    "llama3.2-3b": ("bartowski/Llama-3.2-3B-Instruct-GGUF", "Llama-3.2-3B-Instruct-Q4_K_M.gguf"),
}

SYSTEM_PROMPT = (
    "You translate natural-language requests into a single Linux bash command. "
    "Reply with only the command on one line: no explanation, no markdown, no code fences."
)


def extract_command(text: str) -> tuple[str, bool]:
    """Pull the command out of a reply. Returns (command, had_format_error)."""
    raw = text.strip()
    fence = re.search(r"```(?:\w+)?\n?(.*?)```", raw, re.S)
    body = fence.group(1).strip() if fence else raw
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    cmd = lines[0] if lines else ""
    cmd = re.sub(r"^\$\s+", "", cmd).strip("`").strip()
    format_error = bool(fence) or len(lines) > 1 or cmd != raw
    return cmd, format_error


def start_server(repo: str | None, file: str) -> subprocess.Popen:
    """Start llama-server for a Hugging Face GGUF, or a local GGUF when repo is None."""
    log = open(HERE / "results" / "llama-server.log", "ab")
    source = ["-m", file] if repo is None else ["-hf", repo, "-hff", file]
    proc = subprocess.Popen(
        ["llama-server", *source, "--no-mmproj",
         "--port", str(PORT), "-t", "4", "-c", "2048", "-np", "1",
         "--jinja", "--reasoning", "off", "--no-webui"],
        stdout=log, stderr=subprocess.STDOUT,
    )
    # First start includes the model download.
    deadline = time.time() + 3600
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"llama-server exited with {proc.returncode}; see results/llama-server.log")
        try:
            if requests.get(f"{URL}/health", timeout=2).status_code == 200:
                return proc
        except requests.RequestException:
            pass
        time.sleep(2)
    proc.kill()
    raise TimeoutError("llama-server did not become healthy")


def ask(nl: str) -> dict:
    t0 = time.time()
    resp = requests.post(f"{URL}/v1/chat/completions", json={
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": nl}],
        "temperature": 0, "max_tokens": 128, "seed": 0,
    }, timeout=300).json()
    latency = time.time() - t0
    text = resp["choices"][0]["message"].get("content") or ""
    timings = resp.get("timings", {})
    cmd, fmt_err = extract_command(text)
    return {
        "raw": text, "command": cmd, "format_error": fmt_err,
        "latency_s": round(latency, 3),
        "tok_per_s": round(timings.get("predicted_per_second", 0.0), 2),
        "prompt_tokens": resp.get("usage", {}).get("prompt_tokens"),
        "completion_tokens": resp.get("usage", {}).get("completion_tokens"),
    }


def run_model(name: str, test: pd.DataFrame) -> None:
    out_path = PRED_DIR / f"{name}.jsonl"
    done = set()
    if out_path.exists():
        done = {json.loads(l)["index"] for l in out_path.read_text().splitlines() if l.strip()}
    if len(done) == len(test):
        print(f"{name}: already complete")
        return
    repo, file = MODELS[name]
    print(f"{name}: starting server ({repo}/{file})", flush=True)
    proc = start_server(repo, file)
    try:
        ask("list files")  # warm-up, not recorded
        with out_path.open("a") as fh:
            for i, row in test.iterrows():
                if i in done:
                    continue
                rec = {"index": i, "nl": row.nl, **ask(row.nl)}
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
                if i % 25 == 0:
                    print(f"  {name} {i}/{len(test)}  {rec['latency_s']}s  {rec['command'][:60]}", flush=True)
    finally:
        proc.terminate()
        proc.wait(timeout=30)


def main(names: list[str]) -> None:
    PRED_DIR.mkdir(parents=True, exist_ok=True)
    test = pd.read_csv(DATA)
    for name in names or list(MODELS):
        run_model(name, test)


if __name__ == "__main__":
    main(sys.argv[1:])

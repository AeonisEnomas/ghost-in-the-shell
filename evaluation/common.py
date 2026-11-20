"""Shared by the two model tests: which models are compared, how they are asked,
the sandbox commands run in, and the paired significance test.

Each model runs on CPU through llama-server (llama.cpp) with the same system
prompt the app uses, greedy decoding and a fixed seed, so the same request
always gives the same answer.
"""

import json
import re
import subprocess
import time
from pathlib import Path

import requests
from scipy.stats import binomtest

from ghost_in_the_shell.model import GENERATE_SYSTEM as SYSTEM_PROMPT

HERE = Path(__file__).parent
MODELS_DIR = HERE.parent / "models"

# Name used in result files -> model file. "base" and "finetuned" were exported
# by the same notebook, so they differ only in their weights. "base-original"
# is Qwen's own GGUF of the same model, built with a different converter.
MODELS = {
    "base": "qwen2.5-coder-1.5b-base-export.Q4_K_M.gguf",
    "finetuned": "qwen2.5-coder-1.5b-finetuned.Q4_K_M.gguf",
    "base-original": "qwen2.5-coder-1.5b.Q4_K_M.gguf",
}
# Comparisons reported by both tests, as (A, B).
PAIRS = [("base", "finetuned"), ("base-original", "finetuned"), ("base", "base-original")]

PORT = 8089
URL = f"http://127.0.0.1:{PORT}"

# Host directories mounted read-only (or virtual) on top of a sandbox's
# writable root. They are left out when a sandbox's files are compared.
HOST_MOUNTS = {"usr", "etc", "proc", "dev", "bin", "sbin", "lib", "lib64", "setup.sh"}


# ---------------------------------------------------------------- sandbox

def bwrap_args(fs_root: Path, env: dict[str, str], cwd: str = "/") -> list[str]:
    """Bubblewrap arguments for a throwaway system: `fs_root` becomes "/", the
    host's programs are read-only, and there is no network."""
    args = [
        "bwrap", "--unshare-all", "--die-with-parent", "--new-session",
        "--bind", str(fs_root), "/",
        "--ro-bind", "/usr", "/usr",
        "--symlink", "usr/bin", "/bin",
        "--symlink", "usr/bin", "/sbin",
        "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib", "/lib64",
        "--ro-bind", "/etc", "/etc",
        "--proc", "/proc", "--dev", "/dev",
        "--clearenv",
        "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin",
        "--setenv", "HOME", "/root",
        "--setenv", "LANG", "C.UTF-8",
        "--setenv", "TERM", "dumb",
    ]
    for key, value in env.items():
        args += ["--setenv", key, value]
    return args + ["--chdir", cwd]


# ---------------------------------------------------------------- asking a model

def extract_command(text: str) -> tuple[str, bool]:
    """Pull the command out of a reply. Returns (command, had_format_error)."""
    raw = text.strip()
    fence = re.search(r"```(?:\w+)?\n?(.*?)```", raw, re.S)
    body = fence.group(1).strip() if fence else raw
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    cmd = lines[0] if lines else ""
    cmd = re.sub(r"^\$\s+", "", cmd).strip("`").strip()
    return cmd, bool(fence) or len(lines) > 1 or cmd != raw


def start_server(gguf: Path) -> subprocess.Popen:
    log = open(HERE / "llama-server.log", "ab")
    proc = subprocess.Popen(
        ["llama-server", "-m", str(gguf), "--no-mmproj", "--port", str(PORT), "-t", "4", "-c", "2048",
         "-np", "1", "--jinja", "--reasoning", "off", "--no-webui"],
        stdout=log, stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 300
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"llama-server exited with {proc.returncode}; see {HERE / 'llama-server.log'}")
        try:
            if requests.get(f"{URL}/health", timeout=2).status_code == 200:
                return proc
        except requests.RequestException:
            pass
        time.sleep(1)
    proc.terminate()
    raise TimeoutError("llama-server did not become healthy")


def ask(request: str) -> dict:
    started = time.time()
    reply = requests.post(f"{URL}/v1/chat/completions", json={
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": request}],
        "temperature": 0, "max_tokens": 128, "seed": 0,
    }, timeout=600).json()
    raw = reply["choices"][0]["message"].get("content") or ""
    command, format_error = extract_command(raw)
    return {"raw": raw, "command": command, "format_error": format_error,
            "latency_s": round(time.time() - started, 3)}


def answer_all(name: str, items: list[dict], out: Path) -> None:
    """Write the model's answer to every item (dicts with "index" and "nl") to `out`,
    one JSON line each. Answers already in the file are kept, so a run can resume."""
    done = set()
    if out.exists():
        done = {json.loads(line)["index"] for line in out.read_text().splitlines() if line.strip()}
    todo = [item for item in items if item["index"] not in done]
    if not todo:
        return
    gguf = MODELS_DIR / MODELS[name]
    if not gguf.exists():
        raise FileNotFoundError(f"{gguf} not found; see the README, 'Get the models'")
    print(f"{name}: answering {len(todo)} requests", flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    server = start_server(gguf)
    try:
        ask("list files")  # warm-up, not recorded
        with out.open("a") as fh:
            for item in todo:
                fh.write(json.dumps({**item, **ask(item["nl"])}) + "\n")
                fh.flush()
    finally:
        server.terminate()
        server.wait(timeout=30)


# ---------------------------------------------------------------- statistics

def mcnemar(a, b) -> tuple[int, int, float]:
    """Paired exact McNemar test on the items where exactly one model is right.
    `a` and `b` are boolean pandas Series with the same index."""
    a_only = int((a & ~b).sum())
    b_only = int((~a & b).sum())
    n = a_only + b_only
    p = binomtest(a_only, n, 0.5).pvalue if n else 1.0
    return a_only, b_only, p

"""Local language models served by llama.cpp.

Two models run side by side, each in its own llama-server process:

- the fine-tuned Qwen2.5-Coder-1.5B turns a request into a command;
- the base Qwen2.5-Coder-1.5B explains a command in plain English.

Each server listens on 127.0.0.1 only, on a free port, and requires a key
generated for this run, so other programs on the machine cannot use it.

The models are not trusted. Whatever they return is checked here for format
and later for safety, and nothing they produce is ever run without the user's
confirmation.
"""

import atexit
import json
import re
import secrets
import socket
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import requests

from .config import Settings
from .sanitize import InputRejected, check_command, clean_model_text, clean_request

# The prompt the generator was fine-tuned with. Changing it moves the model
# away from its training conditions.
GENERATE_SYSTEM = (
    "You translate natural-language requests into a single Linux bash command. "
    "Reply with only the command on one line: no explanation, no markdown, no code fences."
)

# The explain prompt evaluated in round 2.
EXPLAIN_SYSTEM = (
    "You explain Linux bash commands to a beginner. Describe in one or two plain-English "
    "sentences exactly what the command does, including what each flag and file path "
    "affects. Do not include the command itself or any code."
)

# llama.cpp grammar: one non-empty line. The generator cannot be talked into
# writing a script, an explanation or several commands on separate lines.
ONE_LINE = r"root ::= [^\r\n]+"

STARTUP_TIMEOUT_S = 120
REQUEST_TIMEOUT_S = 60


class ModelError(RuntimeError):
    """A model could not be started or did not give a usable answer."""


@dataclass(frozen=True)
class Suggestion:
    request: str
    command: str
    seconds: float


@dataclass(frozen=True)
class Explanation:
    command: str
    text: str
    seconds: float


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class LlamaServer:
    """One llama-server process serving one GGUF model."""

    def __init__(self, model_path: Path, name: str, settings: Settings):
        self.model_path = model_path
        self.name = name
        self.settings = settings
        self.log_path = settings.state_dir / "logs" / f"{name}.log"
        self._process: subprocess.Popen | None = None
        self._session = requests.Session()
        self._url = ""

    def launch(self) -> None:
        if not self.model_path.is_file():
            raise ModelError(f"Model file not found: {self.model_path}")
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        port, key = _free_port(), secrets.token_urlsafe(24)
        self._url = f"http://127.0.0.1:{port}"
        self._session.headers["Authorization"] = f"Bearer {key}"
        with open(self.log_path, "wb") as log:
            self._process = subprocess.Popen(
                [
                    "llama-server", "-m", str(self.model_path),
                    "--host", "127.0.0.1", "--port", str(port), "--api-key", key,
                    "-t", str(self.settings.threads), "-c", str(self.settings.context_size),
                    "-np", "1", "--jinja", "--no-webui",
                ],
                stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            )
        atexit.register(self.stop)

    def wait_until_ready(self) -> None:
        deadline = time.monotonic() + STARTUP_TIMEOUT_S
        while time.monotonic() < deadline:
            if self._process is None or self._process.poll() is not None:
                raise ModelError(f"The {self.name} model stopped while starting. Log: {self.log_path}")
            try:
                if self._session.get(f"{self._url}/health", timeout=2).status_code == 200:
                    return
            except requests.RequestException:
                pass
            time.sleep(0.5)
        self.stop()
        raise ModelError(f"The {self.name} model did not start within {STARTUP_TIMEOUT_S} s.")

    def chat(self, system: str, user: str, max_tokens: int, grammar: str | None = None,
             temperature: float = 0.0, seed: int = 0) -> str:
        # Temperature 0 is greedy decoding, as in the evaluation. With a fixed
        # seed, sampling is reproducible too: the same request gives the same answer.
        body = {
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "seed": seed,
        }
        if grammar:
            body["grammar"] = grammar
        try:
            response = self._session.post(
                f"{self._url}/v1/chat/completions", json=body, timeout=REQUEST_TIMEOUT_S
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"] or ""
        except (requests.RequestException, KeyError, IndexError, ValueError) as error:
            raise ModelError(f"The {self.name} model did not answer: {error}") from error

    def stream_chat(self, system: str, user: str, max_tokens: int) -> Iterator[str]:
        """Like chat, but yields the reply in pieces as the model writes it."""
        body = {
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": max_tokens, "temperature": 0, "seed": 0, "stream": True,
        }
        try:
            with self._session.post(f"{self._url}/v1/chat/completions", json=body,
                                    timeout=REQUEST_TIMEOUT_S, stream=True) as response:
                response.raise_for_status()
                for line in response.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        return
                    choices = json.loads(data).get("choices") or [{}]
                    piece = (choices[0].get("delta") or {}).get("content")
                    if piece:
                        yield piece
        except (requests.RequestException, ValueError) as error:
            raise ModelError(f"The {self.name} model did not answer: {error}") from error

    def stop(self) -> None:
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None


def _first_command_line(reply: str) -> str:
    """Take the command out of a reply, in case the model adds a fence or a prompt sign."""
    text = re.sub(r"^```(?:(?:bash|sh|shell)(?=\s))?|```$", "", reply.strip()).strip()
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    if line.startswith("$ "):
        line = line[2:]
    if len(line) > 1 and line[0] == line[-1] == "`":
        line = line[1:-1]
    return line.strip()


class Models:
    """The generator and explainer, started together and stopped together."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.generator = LlamaServer(self.settings.generator_path, "generator", self.settings)
        self.explainer = LlamaServer(self.settings.explainer_path, "explainer", self.settings)

    def start(self) -> None:
        servers = (self.generator, self.explainer)
        for server in servers:
            server.launch()
        try:
            with ThreadPoolExecutor(len(servers)) as pool:
                list(pool.map(LlamaServer.wait_until_ready, servers))
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        self.generator.stop()
        self.explainer.stop()

    def __enter__(self) -> "Models":
        self.start()
        return self

    def __exit__(self, *_) -> None:
        self.stop()

    def suggest(self, request: str, temperature: float = 0.0, seed: int = 0) -> Suggestion:
        """Turn a request into one command. Raises InputRejected or ModelError."""
        request = clean_request(request)
        start = time.perf_counter()
        reply = self.generator.chat(GENERATE_SYSTEM, request, max_tokens=128, grammar=ONE_LINE,
                                    temperature=temperature, seed=seed)
        try:
            command = check_command(_first_command_line(reply))
        except InputRejected as error:
            raise ModelError(f"The model gave an unusable command ({error})") from error
        return Suggestion(request, command, time.perf_counter() - start)

    def explain(self, command: str) -> Explanation:
        """Explain a command in plain English. Raises InputRejected or ModelError."""
        command = check_command(command)
        start = time.perf_counter()
        reply = self.explainer.chat(EXPLAIN_SYSTEM, command, max_tokens=160)
        text = clean_model_text(reply)
        if not text:
            raise ModelError("The model gave an empty explanation.")
        return Explanation(command, text, time.perf_counter() - start)

    def explain_stream(self, command: str) -> Iterator[str]:
        """Explain a command, yielding text as it is written. Raises InputRejected or ModelError.

        The pieces are raw model text; callers must display them as plain text
        and replace them with clean_model_text(full reply) at the end.
        """
        command = check_command(command)
        yield from self.explainer.stream_chat(EXPLAIN_SYSTEM, command, max_tokens=160)

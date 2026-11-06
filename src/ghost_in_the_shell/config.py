"""Paths and settings. Each one can be overridden with an environment variable."""

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    return Path(base) / "ghost-in-the-shell"


@dataclass(frozen=True)
class Settings:
    models_dir: Path = field(
        default_factory=lambda: Path(os.environ.get("GHOST_MODELS_DIR", PROJECT_ROOT / "models"))
    )
    # Fine-tuned model for writing commands, base model for explaining them
    # (fine-tuning weakened explanations; see docs/model_selection.md, round 3).
    generator_file: str = "qwen2.5-coder-1.5b-ft.Q4_K_M.gguf"
    explainer_file: str = "qwen2.5-coder-1.5b.Q4_K_M.gguf"
    threads: int = field(
        default_factory=lambda: int(os.environ.get("GHOST_THREADS", min(4, os.cpu_count() or 1)))
    )
    context_size: int = 2048
    state_dir: Path = field(default_factory=_state_dir)

    @property
    def generator_path(self) -> Path:
        return self.models_dir / self.generator_file

    @property
    def explainer_path(self) -> Path:
        return self.models_dir / self.explainer_file

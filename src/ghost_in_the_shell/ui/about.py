"""The manual page, laid out like a Unix man page: GHOST(1)."""

import streamlit as st

from .. import context
from ..config import Settings
from . import components as ui

VERSION = "0.1.0"


def render() -> None:
    settings = Settings()
    system = context.system_info()
    st.html(ui.man_page([
        ("Name", ui.man_paragraphs("ghost in the shell: talk to Linux in plain English, offline.")),
        ("Synopsis", ui.man_options([
            ("ask", "Describe a task. One command comes back, rated, explained and tried in a sandbox."),
            ("explain", "Paste a command (Tab in the prompt). It is explained, rated and tried the same way."),
            ("run", "Runs the command in the working folder, only when you choose to."),
        ])),
        ("Description", ui.man_paragraphs(
            "Every request passes through six steps before anything can touch your system. The model never "
            "runs anything itself: it only proposes one line of text, which the rest of the pipeline checks.")
         + ui.man_pipeline()),
        ("Risk levels", ui.man_levels()),
        ("Keys", ui.man_options([
            ("enter", "send the request"), ("tab", "switch between ask and explain"),
            ("↑ ↓", "recall earlier requests"), ("ctrl k", "command palette"), ("/", "jump to the prompt"),
        ])),
        ("Models", ui.man_options([
            ("writer", "Qwen2.5-Coder-1.5B, fine-tuned with QLoRA on 10,000 NL2SH-ALFA pairs."),
            ("explainer", "Qwen2.5-Coder-1.5B base model; fine-tuning weakened explanations, so the base writes them."),
            ("accuracy", "46.2% of 275 benchmark tasks give exactly the right result when run (43.6% before "
                         "fine-tuning). Many other answers are valid alternatives."),
            ("gate", "TF-IDF and logistic regression: accepts all 300 benchmark tasks, stops 30 of 30 "
                     "off-topic requests."),
        ])),
        ("Files", ui.man_options([
            (ui.short_path(settings.models_dir), "model files (GGUF) and the request classifier"),
            (ui.short_path(settings.state_dir / "history.db"), "your history (SQLite); delete it from History"),
            (ui.short_path(settings.state_dir / "logs"), "model server logs"),
        ])),
        ("Security", ui.man_paragraphs(
            "Everything runs on this computer; the app answers only at 127.0.0.1 and never uses the network. "
            "Dry runs see a throwaway layer over the working folder, a read-only system and an empty home folder, "
            "with no network, a five-second limit and memory limits. Commands that need administrator rights "
            "are never run from the app. Model control tokens and hidden characters are stripped from requests "
            "and rejected in commands; text from the model, files and commands is never rendered as HTML.")),
        ("Bugs", ui.man_paragraphs(
            "The model is right about half the time on hard benchmark tasks. Read the explanation and the dry run.",
            "The risk check follows rules: an unusual command can still be rated too low. Unknown programs are "
            "never rated read-only.",
            "The dry run tracks only the working folder; effects elsewhere appear under risk.")),
        ("Environment", ui.man_options([
            ("system", f"{system.name}, package manager {system.package_manager or 'unknown'}"),
            ("GHOST_MODELS_DIR", "where the model files are (default: models/ in the project)"),
            ("GHOST_THREADS", "CPU threads per model (default: up to 4)"),
        ])),
        ("See also", ui.man_paragraphs("docs/model_selection.md, docs/app.md, evaluation/results/report.md")),
    ], VERSION, "November 2026"))

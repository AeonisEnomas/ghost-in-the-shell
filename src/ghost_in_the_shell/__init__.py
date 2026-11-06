"""Ghost in the Shell: talk to Linux in plain English, offline."""

import os
import sys
from pathlib import Path


def main() -> None:
    """Start the app: `ghost-in-the-shell` from any folder opens it on that folder."""
    ui = Path(__file__).parent / "ui"
    os.environ["GHOST_START_FOLDER"] = os.getcwd()
    # Streamlit reads its theme from .streamlit/config.toml in the current
    # folder, and serves fonts from static/ next to the app.
    os.chdir(ui)
    os.execv(sys.executable, [sys.executable, "-m", "streamlit", "run", "app.py", *sys.argv[1:]])

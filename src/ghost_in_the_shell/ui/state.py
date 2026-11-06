"""Session state and the actions that change it, shared by all pages.

The workspace is a feed of command blocks, like a terminal session. Each
block is a `View` with its own id; every widget that belongs to a block is
keyed by that id, so state never carries over from one command to the next
(confirming one dangerous command never enables Run for another).

Explanations are written in a background thread and streamed into a shared
buffer, so the page never waits for them and the text appears as it is
written.
"""

import os
import threading
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import streamlit as st

from .. import context
from ..config import Settings
from ..history import Entry, History
from ..model import ModelError, Models
from ..pipeline import Assistant, Review
from ..relevance import RelevanceChecker
from ..sandbox import RunResult
from ..sanitize import InputRejected, clean_model_text

FEED_LIMIT = 30


@dataclass
class View:
    """One command in the session feed and everything known about it."""
    source: str                       # "ask" or "explain"
    request: str
    review: Review
    entry_id: int
    folder: Path
    attempts: int = 1
    seconds: float = 0.0
    relevance: float | None = None
    alternatives: tuple[str, ...] = ()
    edited: bool = False
    run: RunResult | None = None
    run_error: str = ""
    created: datetime = field(default_factory=datetime.now)
    uid: str = field(default_factory=lambda: uuid.uuid4().hex[:10])


@dataclass
class Notice:
    request: str
    message: str
    score: float | None = None
    phrases: tuple[str, ...] = ()


@dataclass
class Explanation:
    """Shared between the writer thread and the page; only the writer appends."""
    text: str = ""
    done: bool = False
    error: str = ""


@st.cache_resource(show_spinner=False)
def services() -> tuple[Assistant, History]:
    """Started once per app process and shared by every browser tab."""
    settings = Settings()
    models = Models(settings)
    models.start()
    relevance = RelevanceChecker.load(settings.models_dir / "relevance.joblib")
    return Assistant(models, relevance), History(settings.state_dir / "history.db")


@st.cache_resource(show_spinner=False)
def _explanations() -> tuple[ThreadPoolExecutor, OrderedDict, threading.Lock]:
    return ThreadPoolExecutor(max_workers=1, thread_name_prefix="explain"), OrderedDict(), threading.Lock()


def _write_explanation(command: str, target: Explanation) -> None:
    assistant, _ = services()
    try:
        for piece in assistant.models.explain_stream(command):
            target.text += piece
        target.text = clean_model_text(target.text)
    except (ModelError, InputRejected) as error:
        target.error = str(error)
    finally:
        target.done = True


def explanation(command: str) -> Explanation:
    """The explanation for a command, started in the background if needed."""
    pool, jobs, lock = _explanations()
    with lock:
        job = jobs.get(command)
        if job is None:
            job = jobs[command] = Explanation()
            pool.submit(_write_explanation, command, job)
            while len(jobs) > 200:
                jobs.popitem(last=False)
        jobs.move_to_end(command)
    return job


def session():
    s = st.session_state
    if "folder" not in s:
        start = os.environ.get("GHOST_START_FOLDER") or str(Path.home())
        try:
            s.folder = context.resolve_folder(start)
        except ValueError:
            s.folder = Path.home()
        s.start_folder = s.folder
        s.feed = []               # list[View], oldest first
        s.view = None             # the focused View
        s.notice = None
        s.error = ""
        s.pending = None          # (kind, text) queued by a widget callback
        s.dialog = None           # ("run" | "edit" | "folder", view uid or None)
        s.fill = ""
    return s


def clear_messages() -> None:
    s = session()
    s.notice, s.error = None, ""


def clear_session() -> None:
    s = session()
    s.feed, s.view = [], None
    clear_messages()


def set_folder(path: Path) -> None:
    s = session()
    s.folder = path
    clear_messages()


def focus(uid: str) -> None:
    s = session()
    s.view = next((v for v in s.feed if v.uid == uid), s.view)


def _add(view: View) -> None:
    s = session()
    s.feed.append(view)
    s.feed = s.feed[-FEED_LIMIT:]
    s.view = view
    explanation(view.review.command)


# ---------------------------------------------------------------- actions

def ask(request: str, force: bool = False) -> None:
    assistant, history = services()
    s = session()
    clear_messages()
    with st.spinner("Writing a command and trying it in the sandbox…", show_time=True):
        outcome = assistant.ask(request, s.folder, force=force)
    if outcome.status in ("rejected", "error"):
        s.error = outcome.message
    elif outcome.status == "off_topic":
        r = outcome.relevance
        s.notice = Notice(outcome.request, outcome.message, r.score if r else None,
                          r.injection_phrases if r else ())
    else:
        review = outcome.review
        entry = history.add("ask", s.folder, outcome.request, review.command, review.assessment.level.name)
        _add(View("ask", outcome.request, review, entry, s.folder, outcome.attempts,
                  outcome.generation_seconds, outcome.relevance.score if outcome.relevance else None,
                  outcome.alternatives))


def check(command: str, source: str = "explain", request: str = "", entry_id: int | None = None,
          edited: bool = False) -> None:
    assistant, history = services()
    s = session()
    clear_messages()
    try:
        with st.spinner("Checking the command and trying it in the sandbox…", show_time=True):
            review = assistant.review(command, s.folder)
    except InputRejected as error:
        s.error = str(error)
        return
    if entry_id is None:
        entry_id = history.add(source, s.folder, request or command, review.command, review.assessment.level.name)
    _add(View(source, request or command, review, entry_id, s.folder, edited=edited))


def restore(entry: Entry) -> None:
    """Open a history entry in the session, re-checked against the current folder."""
    check(entry.command, entry.mode, entry.request, entry.id)


def run_pending() -> bool:
    """Carry out an action queued by a widget callback. Returns True if one ran."""
    s = session()
    if not s.pending:
        return False
    kind, text = s.pending
    s.pending = None
    if kind == "ask":
        ask(text)
    elif kind == "force":
        ask(text, force=True)
    elif kind == "check":
        check(text)
    return True

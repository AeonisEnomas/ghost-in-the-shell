"""The session page: a terminal-like feed of command blocks with a prompt.

Each request becomes a block. The focused block expands into an inspector
(explanation, risk, dry run, output). Running is proportional to risk:
read-only and ordinary changes run on click, Caution asks for confirmation
with the list of affected files, and Dangerous needs the word "run" typed.
"""

import os
from pathlib import Path

import streamlit as st

from .. import context
from ..pipeline import CONFIRM_WORD, RunRefused
from ..safety import Level
from ..sanitize import InputRejected
from . import components as ui
from . import widgets
from .state import (View, check, clear_messages, clear_session, explanation, focus, run_pending, services,
                    session, set_folder)

EXAMPLES = [
    "show the 10 largest files in this folder",
    "how much space does each subfolder use",
    "count the lines in every python file",
    "find files changed in the last 24 hours",
]
LEVEL_KEY = {Level.READ_ONLY: "read", Level.CHANGES: "change", Level.CAUTION: "caution", Level.DANGER: "danger"}


# ---------------------------------------------------------------- callbacks

def on_prompt() -> None:
    s = st.session_state
    value = s["prompt"].submit
    if value and value.get("text"):
        s.prompt_mode = value.get("mode", "ask")
        s.pending = ("ask" if value.get("mode") == "ask" else "check", value["text"])


def on_block(key: str) -> None:
    s = st.session_state
    value = s[key].action
    if not value:
        return
    view = next((v for v in s.feed if v.uid == value["id"]), None)
    if view is None:
        return
    kind = value["type"]
    if kind == "focus":
        focus(view.uid)
    elif kind == "edit":
        s.dialog = ("edit", view.uid)
    elif kind == "recheck":
        s.pending = ("recheck", view.uid)
    elif kind == "run":
        if view.review.assessment.level in (Level.READ_ONLY, Level.CHANGES):
            s.pending = ("run", view.uid)
        else:
            s.dialog = ("run", view.uid)


def on_example(text: str) -> None:
    st.session_state.pending = ("ask", text)


# ---------------------------------------------------------------- running

def do_run(view: View, confirmation: str = "") -> None:
    assistant, history = services()
    level = view.review.assessment.level
    try:
        with st.spinner("Running…", show_time=True):
            view.run = assistant.run(view.review.command, view.folder, confirmation)
        view.run_error = ""
        history.record_run(view.entry_id, view.review.command, level.name, view.run.exit_code)
        if view.run.timed_out:
            st.toast("Stopped: the command took too long.", icon=":material/timer_off:")
        elif view.run.exit_code == 0:
            st.toast(f"Ran in {ui.duration(view.run.seconds)}", icon=":material/check:")
        else:
            st.toast(f"Finished with exit code {view.run.exit_code}", icon=":material/warning:")
    except (RunRefused, InputRejected) as error:
        view.run_error = str(error)
        st.toast("Not run", icon=":material/block:")


def handle_pending() -> bool:
    s = session()
    if not s.pending:
        return False
    kind, value = s.pending
    if kind in ("run", "recheck"):
        s.pending = None
        view = next((v for v in s.feed if v.uid == value), None)
        if view and kind == "run":
            do_run(view)
        elif view:
            check(view.review.command, view.source, view.request, view.entry_id)
        return True
    return run_pending()


# ---------------------------------------------------------------- dialogs
#
# A dialog stays open for as long as `session.dialog` names it: it is drawn
# again on every rerun (the streaming explanation triggers reruns), and only
# closed by its own buttons or by dismissing it.

def close_dialog() -> None:
    st.session_state.dialog = None


@st.dialog("Run this command?", width="medium", on_dismiss=close_dialog)
def run_dialog(view: View) -> None:
    review = view.review
    level = review.assessment.level
    st.html(ui.dialog_summary(review.command, level, review.assessment.findings[:3], review.preview,
                              ui.display_path(view.folder, 48)))
    confirmation = ""
    if level is Level.DANGER:
        confirmation = st.text_input(f'This is dangerous. Type "{CONFIRM_WORD}" to confirm.',
                                     key=f"confirm-{view.uid}", max_chars=10, placeholder=CONFIRM_WORD)
    ready = level is not Level.DANGER or confirmation.strip().lower() == CONFIRM_WORD
    with st.container(horizontal=True, horizontal_alignment="right", key=f"dialog-actions-{view.uid}"):
        if st.button("Cancel", key=f"cancel-{view.uid}"):
            close_dialog()
            st.rerun()
        with st.container(key="danger-run" if level is Level.DANGER else "caution-run", width="content"):
            if st.button("Run anyway" if level is Level.DANGER else "Run", type="primary", disabled=not ready,
                         key=f"go-{view.uid}", icon=":material/play_arrow:"):
                do_run(view, confirmation)
                close_dialog()
                st.rerun()


@st.dialog("Edit the command", width="medium", on_dismiss=close_dialog)
def edit_dialog(view: View) -> None:
    st.caption("Change the command and check it again. The new version gets its own risk rating and dry run.")
    text = st.text_input("Command", value=view.review.command, key=f"edit-{view.uid}", label_visibility="collapsed")
    with st.container(horizontal=True, horizontal_alignment="right"):
        if st.button("Cancel", key=f"edit-cancel-{view.uid}"):
            close_dialog()
            st.rerun()
        if st.button("Check", type="primary", key=f"edit-go-{view.uid}", icon=":material/fact_check:"):
            if text.strip() and text.strip() != view.review.command:
                check(text, view.source, view.request, edited=True)
            close_dialog()
            st.rerun()


@st.dialog("Open a folder", width="large", on_dismiss=close_dialog)
def folder_dialog() -> None:
    s = session()
    browse = Path(st.session_state.get("browse") or s.folder)
    if not browse.is_dir():
        browse = s.folder

    with st.container(horizontal=True, key="crumbs", gap="small"):
        parts = list(reversed([browse, *browse.parents]))
        for i, part in enumerate(parts[-6:]):
            label = "/" if part == Path("/") else (part.name or str(part))
            if st.button(label, key=f"crumb-{i}-{part}", type="tertiary"):
                st.session_state.browse = str(part)
                st.rerun(scope="fragment")

    with st.form("folder-path", border=False):
        cols = st.columns([5, 1], vertical_alignment="bottom")
        typed = cols[0].text_input("Path", value=str(browse), key=f"path-{browse}", label_visibility="collapsed")
        if cols[1].form_submit_button("Go", width="stretch"):
            try:
                st.session_state.browse = str(context.resolve_folder(typed))
                st.rerun(scope="fragment")
            except ValueError as error:
                st.error(str(error))

    try:
        folders = sorted((p for p in browse.iterdir() if p.is_dir() and not p.name.startswith(".")),
                         key=lambda p: p.name.lower())
    except OSError:
        folders = []
    with st.container(height=300, key="folder-list"):
        if browse.parent != browse and st.button("..", key="up", icon=":material/arrow_upward:", type="tertiary"):
            st.session_state.browse = str(browse.parent)
            st.rerun(scope="fragment")
        if not folders:
            st.caption("No sub-folders here.")
        grid = st.columns(3)
        for i, folder in enumerate(folders[:150]):
            if grid[i % 3].button(ui.clip(folder.name, 26), key=f"f-{folder}", icon=":material/folder:",
                                  type="tertiary", help=str(folder)):
                st.session_state.browse = str(folder)
                st.rerun(scope="fragment")

    info = context.folder_info(browse)
    with st.container(horizontal=True, vertical_alignment="center"):
        st.html(ui.note(f"{ui.short_path(browse)} · {ui.plural(info.total - info.hidden, 'item')}"), width="stretch")
        if st.button("Cancel", key="folder-cancel"):
            st.session_state.browse = None
            close_dialog()
            st.rerun()
        if st.button("Open this folder", type="primary", key="folder-open", icon=":material/folder_open:"):
            if os.access(browse, os.R_OK | os.X_OK):
                set_folder(browse)
                st.session_state.browse = None
                st.toast(f"Working in {ui.short_path(browse)}", icon=":material/folder_open:")
                close_dialog()
                st.rerun()
            else:
                st.error("You do not have permission to open this folder.")


def open_dialogs() -> None:
    s = session()
    if not s.dialog:
        return
    kind, uid = s.dialog
    view = next((v for v in s.feed if v.uid == uid), None)
    if kind == "run" and view:
        run_dialog(view)
    elif kind == "edit" and view:
        edit_dialog(view)
    elif kind == "folder":
        folder_dialog()
    else:
        s.dialog = None


# ---------------------------------------------------------------- page parts

def title_bar() -> None:
    s = session()
    info = context.folder_info(s.folder)
    system = context.system_info()
    with st.container(key="titlebar", horizontal=True, vertical_alignment="center"):
        st.html(ui.title_bar(system.user, ui.host_name(), s.folder, info.total, info.hidden), width="stretch")
        if st.button("cd", key="open-folder", icon=":material/folder_open:", help="Open another folder"):
            s.dialog = ("folder", None)
            st.rerun()
        if s.feed and st.button("clear", key="clear-session", icon=":material/clear_all:",
                                help="Clear this session (history is kept)"):
            clear_session()
            st.rerun()


def block_data(view: View, focused: bool) -> dict:
    review = view.review
    level = review.assessment.level
    preview = review.preview
    counts = None
    if preview.mode == "overlay":
        counts = {k: len(preview.changes_of(k)) for k in ("deleted", "modified", "created")}
    meta = []
    if view.source == "ask" and not view.edited:
        meta.append(ui.duration(view.seconds))
        if view.relevance is not None:
            meta.append(f"shell task {view.relevance:.0%}")
        if view.attempts > 1:
            meta.append(f"{view.attempts} tries")
    if view.edited:
        meta.append("edited")
    blocked = ""
    if review.assessment.elevated:
        blocked = "needs admin rights · run it in your own terminal"
    elif not review.runnable:
        blocked = "syntax error · edit it first"
    elif view.folder != session().folder:
        blocked = "folder changed · check again"
    ran = None
    if view.run:
        ok = view.run.exit_code == 0 and not view.run.timed_out
        label = "✓ ran" if ok else ("✗ stopped: too slow" if view.run.timed_out else f"✗ exit {view.run.exit_code}")
        ran = {"ok": ok, "label": f"{label} · {ui.duration(view.run.seconds)} · output below"}
    elif view.run_error:
        ran = {"ok": False, "label": f"✗ not run: {view.run_error}"}
    return {
        "id": view.uid, "focused": focused, "time": view.created.strftime("%H:%M"),
        "folder": ui.display_path(view.folder, 32), "source": view.source, "request": view.request,
        "command": review.command, "level": LEVEL_KEY[level], "level_label": level.label,
        "glyph": ui.LEVEL_GLYPH[level], "counts": counts, "preview_label": ui.change_summary_text(preview),
        "meta": " · ".join(meta), "runnable": not blocked, "blocked_reason": blocked, "ran": ran,
    }


@st.fragment(run_every=0.35)
def streaming_explanation(command: str) -> None:
    job = explanation(command)
    st.html(ui.explanation_live(job.text, job.done))
    if job.done:
        st.rerun()


def explain_panel(view: View) -> None:
    job = explanation(view.review.command)
    with st.container(key=f"panel-explain-{view.uid}"):
        st.html(ui.panel_head("explanation", "written by the base model · can be wrong", "ai"))
        if job.error:
            st.html(ui.note(f"No explanation: {job.error}"))
        elif job.done:
            st.html(ui.explanation(job.text))
        else:
            streaming_explanation(view.review.command)


def risk_panel(view: View) -> None:
    assessment = view.review.assessment
    with st.container(key=f"panel-risk-{view.uid}"):
        st.html(ui.panel_head("risk", ui.plural(len(assessment.findings), "finding")) +
                ui.risk_body(assessment, view.review.issues))
        if view.alternatives:
            with st.expander(f"{ui.plural(len(view.alternatives), 'other try')} by the model"):
                st.caption("The first answer had a problem (syntax or a missing program), so the model was asked "
                           "again. These were not chosen:")
                for alt in view.alternatives:
                    st.code(alt, language="bash", wrap_lines=True)


def dry_run_panel(view: View) -> None:
    preview = view.review.preview
    with st.container(key=f"panel-dry-{view.uid}"):
        st.html(ui.panel_head("dry run", ui.duration(preview.seconds) if preview.mode != "skipped" else "skipped") +
                ui.change_tiles(preview))
        if preview.mode == "skipped":
            st.html(ui.note(preview.note))
            return
        changes_tab, output_tab = st.tabs(["changes", "output"], key=f"tabs-{view.uid}")
        with changes_tab:
            st.html(ui.changes(preview.changes) if preview.mode == "overlay"
                    else ui.note("Changes cannot be listed for a read-only preview."))
        with output_tab:
            st.html(ui.terminal_output(preview.output, preview.exit_code, preview.truncated))
        st.html(ui.note(preview.note))


def feedback_row(view: View) -> None:
    with st.container(key=f"panel-fb-{view.uid}", horizontal=True, vertical_alignment="center"):
        st.html(ui.note("Was this the right command?" if view.source == "ask" else "Was the explanation accurate?"),
                width="stretch")
        choice = st.feedback("thumbs", key=f"feedback-{view.uid}")
    if choice is not None:
        services()[1].set_feedback(view.entry_id, 1 if choice == 1 else -1)


def output_panel(view: View) -> None:
    result = view.run
    meta = "stopped" if result.timed_out else f"exit {result.exit_code} · {ui.duration(result.seconds)}"
    with st.container(key=f"panel-out-{view.uid}"):
        st.html(ui.panel_head("output", meta, "ok" if result.exit_code == 0 else "warn") +
                ui.terminal_output(result.output, result.exit_code, result.truncated))


def inspector(view: View) -> None:
    left, right = st.columns([7, 5], gap="small")
    with left:
        explain_panel(view)
        risk_panel(view)
    with right:
        if view.run:
            output_panel(view)
        dry_run_panel(view)
        feedback_row(view)


def banner() -> None:
    st.html(ui.banner())
    grid = st.columns(2)
    for i, text in enumerate(EXAMPLES):
        grid[i % 2].button(text, key=f"ex-{i}", icon=":material/chevron_right:", type="tertiary",
                           on_click=on_example, args=(text,), width="stretch")


def notice_block() -> None:
    s = session()
    n = s.notice
    st.html(ui.system_line(n.message, n.score, n.phrases))
    with st.container(horizontal=True, key="notice-actions"):
        if st.button("continue anyway", key="force", icon=":material/arrow_forward:"):
            s.pending = ("force", n.request)
            st.rerun()
        if st.button("dismiss", key="dismiss", type="tertiary"):
            clear_messages()
            st.rerun()


def feed() -> None:
    s = session()
    shown = s.feed[-8:]
    if len(s.feed) > len(shown):
        st.html(ui.note(f"{len(s.feed) - len(shown)} earlier commands are in the sidebar."))
    for view in shown:
        focused = s.view is not None and view.uid == s.view.uid
        key = f"blk-{view.uid}"
        widgets.block(block_data(view, focused), key=key, on_action=lambda key=key: on_block(key))
        if focused:
            inspector(view)


def render() -> None:
    s = session()
    if handle_pending():
        st.rerun()
    title_bar()
    if not s.feed and not s.notice and not s.error:
        banner()
    feed()
    if s.error:
        st.html(ui.system_line(s.error, None, (), tone="error"))
    if s.notice:
        notice_block()
    system = context.system_info()
    history = [v.request for v in reversed(s.feed) if v.source == "ask"][:30]
    fill, s.fill = s.fill, ""
    with st.container(key="promptbar"):
        widgets.prompt(mode=st.session_state.get("prompt_mode", "ask"), user=system.user, host=ui.host_name(),
                       folder=ui.display_path(s.folder, 40), folder_full=str(s.folder), history=history,
                       fill=fill, on_submit=on_prompt)
    open_dialogs()

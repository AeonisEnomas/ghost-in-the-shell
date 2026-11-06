"""The history page: everything asked and checked on this computer."""

import streamlit as st

from ..safety import Level
from . import components as ui
from . import nav, widgets
from .state import restore, services

LEVEL_FILTERS = {level.label: level.name for level in Level}
LEVEL_KEY = {"READ_ONLY": "read", "CHANGES": "change", "CAUTION": "caution", "DANGER": "danger"}


@st.dialog("Delete all history?")
def confirm_clear() -> None:
    _, history = services()
    st.write("Every saved request, command and piece of feedback on this computer will be deleted. "
             "This cannot be undone.")
    with st.container(horizontal=True, horizontal_alignment="right"):
        if st.button("Keep it", key="clear-no"):
            st.rerun()
        with st.container(key="danger-run", width="content"):
            if st.button("Delete history", type="primary", key="clear-yes"):
                history.clear()
                st.toast("History deleted", icon=":material/delete:")
                st.rerun()


def on_open() -> None:
    value = st.session_state["history-table"].open
    if value:
        st.session_state.reopen = value["id"]


def render() -> None:
    _, history = services()
    if st.session_state.get("reopen"):
        entry_id = st.session_state.pop("reopen")
        entry = next((x for x in history.recent(1000) if x.id == entry_id), None)
        if entry:
            restore(entry)
            st.switch_page(nav.page("session"))

    st.html(ui.page_head("history | less", "History",
                         "Everything you asked and checked, newest first. Stored on this computer only. "
                         "Click a row to open it in the session; it is checked again in the current folder."))
    stats = history.stats()
    rated = stats["helpful"] + stats["not_helpful"]
    st.html(ui.stat_strip([
        ("requests", str(stats["total"])),
        ("run", str(stats["ran"])),
        ("marked right", f"{stats['helpful'] / rated:.0%}" if rated else "–"),
        ("rated", str(rated)),
    ]))

    with st.container(horizontal=True, vertical_alignment="center", key="history-filters"):
        search = st.text_input("Search", key="history-search", placeholder="grep requests and commands",
                               label_visibility="collapsed", icon=":material/search:", width="stretch")
        levels = st.pills("Risk", list(LEVEL_FILTERS), selection_mode="multi", key="history-levels",
                          label_visibility="collapsed")

    entries = history.recent(500, search)
    if levels:
        wanted = {LEVEL_FILTERS[label] for label in levels}
        entries = [x for x in entries if x.level in wanted]

    rows = []
    for x in entries[:200]:
        level = Level[x.level] if x.level in Level.__members__ else Level.CAUTION
        status = "–"
        if x.ran:
            status = "ran" if x.exit_code == 0 else f"exit {x.exit_code}"
        rows.append({"id": x.id, "when": ui.time_ago(x.created), "level": LEVEL_KEY[level.name],
                     "level_label": level.label, "glyph": ui.LEVEL_GLYPH[level], "mode": x.mode,
                     "request": x.request, "command": x.command, "ran": x.ran, "ok": x.exit_code == 0,
                     "status": status})
    widgets.history_table(rows, "Nothing yet." if not search and not levels else "No entries match.",
                          on_open=on_open)
    if len(entries) > 200:
        st.caption(f"Showing the newest 200 of {len(entries)}. Search to narrow it down.")
    if stats["total"]:
        if st.button("delete all history…", key="clear", type="tertiary", icon=":material/delete:"):
            confirm_clear()

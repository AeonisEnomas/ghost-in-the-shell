"""Ghost in the Shell: the Streamlit interface.

Start it with the `ghost-in-the-shell` command (see ghost_in_the_shell/__init__.py),
which runs Streamlit from this folder so that the theme and fonts load.
"""

from pathlib import Path

import streamlit as st

from ghost_in_the_shell import context
from ghost_in_the_shell.config import Settings
from ghost_in_the_shell.model import ModelError
from ghost_in_the_shell.safety import Level
from ghost_in_the_shell.ui import about, history_page, nav, widgets, workspace
from ghost_in_the_shell.ui import components as ui
from ghost_in_the_shell.ui.state import clear_session, focus, services, session

HERE = Path(__file__).parent
SIDEBAR_COLOUR = {Level.READ_ONLY: "green", Level.CHANGES: "blue", Level.CAUTION: "orange", Level.DANGER: "red"}


def palette_items() -> list[dict]:
    return [
        {"id": "prompt", "label": "Focus the prompt", "group": "session", "client": "ghost:focus-prompt"},
        {"id": "mode-ask", "label": "Ask in English", "group": "mode", "client": "ghost:set-mode", "detail": "ask"},
        {"id": "mode-explain", "label": "Explain a command", "group": "mode", "client": "ghost:set-mode",
         "detail": "explain"},
        {"id": "folder", "label": "Open another folder…", "group": "session"},
        {"id": "home", "label": "Work in the home folder", "group": "session"},
        {"id": "clear", "label": "Clear the session", "group": "session"},
        {"id": "page-session", "label": "Go to Session", "group": "go to"},
        {"id": "page-history", "label": "Go to History", "group": "go to"},
        {"id": "page-manual", "label": "Go to Manual", "group": "go to"},
    ]


def on_palette() -> None:
    value = st.session_state["palette"].action
    if value:
        st.session_state.palette_action = value["id"]


def handle_palette() -> None:
    s = session()
    action = st.session_state.pop("palette_action", None)
    if not action:
        return
    if action == "folder":
        s.dialog = ("folder", None)
        st.switch_page(nav.page("session"))
    elif action == "home":
        s.folder = Path.home()
        st.toast("Working in ~", icon=":material/home:")
    elif action == "clear":
        clear_session()
    elif action.startswith("page-"):
        st.switch_page(nav.page(action.removeprefix("page-")))


def sidebar() -> None:
    s = session()
    with st.sidebar:
        st.html(ui.sidebar_heading("this session"))
        if not s.feed:
            st.caption("Commands you check appear here.")
        for view in reversed(s.feed[-20:]):
            level = view.review.assessment.level
            label = f":{SIDEBAR_COLOUR[level]}[{ui.LEVEL_GLYPH[level]}]  {view.request if view.source == 'ask' else view.review.command}"
            current = s.view is not None and view.uid == s.view.uid
            if st.button(label, key=f"side-{view.uid}", type="secondary" if current else "tertiary",
                         help=view.review.command, width="stretch"):
                focus(view.uid)
                st.switch_page(nav.page("session"))


def main() -> None:
    st.set_page_config(page_title="ghost in the shell", page_icon=str(HERE / "static" / "mark.svg"),
                       layout="wide", initial_sidebar_state="auto")
    st.html(f"<style>{(HERE / 'theme.css').read_text()}</style>")
    st.logo(str(HERE / "static" / "logo.svg"), size="large", icon_image=str(HERE / "static" / "mark.svg"))
    s = session()
    system = context.system_info()

    try:
        with st.spinner("Starting the local models…"):
            services()
    except ModelError as error:
        st.html(ui.system_line(f"The models could not start. {error} Put the GGUF files in "
                               f"{Settings().models_dir} (see README), then reload.", None, (), tone="error"))
        st.stop()

    widgets.palette(palette_items(), on_action=on_palette)
    pages = [
        nav.register("session", st.Page(workspace.render, title="Session", icon=":material/terminal:",
                                        url_path="session", default=True)),
        nav.register("history", st.Page(history_page.render, title="History", icon=":material/history:",
                                        url_path="history")),
        nav.register("manual", st.Page(about.render, title="Manual", icon=":material/menu_book:",
                                       url_path="manual")),
    ]
    page = st.navigation(pages, position="sidebar")
    handle_palette()
    sidebar()
    page.run()

    last = ""
    if s.view and s.view.source == "ask" and s.view.seconds:
        last = ui.duration(s.view.seconds)
    st.html(ui.status_bar(system.name, system.package_manager, s.folder, True, len(s.feed), last))


main()

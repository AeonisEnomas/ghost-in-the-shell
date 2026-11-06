"""The app's pages, registered once per run so pages can link to each other."""

import streamlit as st

_pages: dict[str, st.Page] = {}


def register(name: str, page: st.Page) -> st.Page:
    _pages[name] = page
    return page


def page(name: str) -> st.Page:
    return _pages[name]

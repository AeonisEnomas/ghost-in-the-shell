from pathlib import Path

import pytest

from ghost_in_the_shell.history import History


@pytest.fixture
def history(tmp_path):
    return History(tmp_path / "state" / "history.db")


def test_add_and_list(history):
    first = history.add("ask", Path("/tmp"), "list files", "ls", "READ_ONLY")
    second = history.add("explain", Path("/tmp"), "du -sh *", "du -sh *", "READ_ONLY")
    entries = history.recent()
    assert [e.id for e in entries] == [second, first]
    assert entries[1].request == "list files" and not entries[1].ran


def test_run_stores_the_edited_command(history):
    entry = history.add("ask", Path("/tmp"), "delete logs", "rm *.log", "CAUTION")
    history.record_run(entry, "rm -i *.log", "CAUTION", 0)
    stored = history.recent()[0]
    assert stored.ran and stored.command == "rm -i *.log" and stored.exit_code == 0


def test_feedback(history):
    entry = history.add("ask", Path("/tmp"), "x", "ls", "READ_ONLY")
    history.set_feedback(entry, 1)
    assert history.recent()[0].feedback == 1
    history.set_feedback(entry, None)
    assert history.recent()[0].feedback is None
    with pytest.raises(ValueError):
        history.set_feedback(entry, 5)


def test_search_is_literal_and_injection_safe(history):
    history.add("ask", Path("/tmp"), "100% of the cpu", "top", "READ_ONLY")
    history.add("ask", Path("/tmp"), "anything", "ls", "READ_ONLY")
    history.add("ask", Path("/tmp"), "x'); DROP TABLE entries; --", "ls", "READ_ONLY")
    assert [e.request for e in history.recent(search="100%")] == ["100% of the cpu"]
    assert history.recent(search="_") == []
    assert len(history.recent(search="' OR 1=1 --")) == 0
    assert len(history.recent()) == 3


def test_stats_and_clear(history):
    entry = history.add("ask", Path("/tmp"), "x", "ls", "READ_ONLY")
    history.record_run(entry, "ls", "READ_ONLY", 0)
    history.set_feedback(entry, -1)
    assert history.stats() == {"total": 1, "ran": 1, "helpful": 0, "not_helpful": 1}
    history.clear()
    assert history.recent() == [] and history.stats()["total"] == 0

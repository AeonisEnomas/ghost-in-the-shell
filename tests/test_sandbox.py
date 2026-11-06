import os
from pathlib import Path

import pytest

from ghost_in_the_shell import sandbox
from ghost_in_the_shell.sanitize import clean_terminal_output

pytestmark = pytest.mark.skipif(not sandbox.sandbox_available(), reason="bwrap not installed")


@pytest.fixture
def folder():
    # Inside the home folder, like a real project, to test that the working
    # folder stays visible while the rest of /home is hidden.
    base = Path.home() / ".cache" / "ghost-test"
    base.mkdir(parents=True, exist_ok=True)
    import tempfile
    with tempfile.TemporaryDirectory(dir=base) as tmp:
        root = Path(tmp)
        (root / "keep.txt").write_text("keep\n")
        (root / "old.log").write_text("old")
        (root / "notes.txt").write_text("one\ntwo\n")
        (root / "src").mkdir()
        (root / "src" / "a.py").write_text("print(1)\n")
        yield root


def test_lists_changes_without_touching_the_folder(folder):
    result = sandbox.preview("touch new.txt; rm old.log; echo three >> notes.txt; rm -r src", folder)
    assert result.mode == "overlay"
    assert [c.path for c in result.changes_of("created")] == ["new.txt"]
    assert sorted(c.path for c in result.changes_of("deleted")) == ["old.log", "src"]
    assert [c.path for c in result.changes_of("modified")] == ["notes.txt"]
    assert (folder / "old.log").exists() and (folder / "src" / "a.py").exists()
    assert not (folder / "new.txt").exists()
    assert (folder / "notes.txt").read_text() == "one\ntwo\n"


def test_output_and_relative_paths(folder):
    result = sandbox.preview("pwd; cat keep.txt; ls src", folder)
    assert result.output.split() == [str(folder.resolve()), "keep", "a.py"]
    assert result.exit_code == 0


def test_home_is_hidden(folder):
    marker = Path.home() / ".ghost-test-marker"
    marker.write_text("hidden-content-42")
    try:
        result = sandbox.preview(f"cat {marker}; ls -A ~ | wc -l", folder)
        assert "hidden-content-42" not in result.output
        assert "No such file" in result.output
    finally:
        marker.unlink()


def test_rm_rf_home_in_preview_is_harmless(folder):
    result = sandbox.preview("rm -rf ~/* ~/.[!.]* 2>/dev/null; rm -rf ./*; echo done", folder)
    assert "done" in result.output
    assert (folder / "keep.txt").exists()
    assert {c.path for c in result.changes_of("deleted")} >= {"keep.txt", "src"}


def test_system_is_read_only(folder):
    result = sandbox.preview("touch /etc/ghost-test 2>&1; echo code=$?", folder)
    assert "code=1" in result.output
    assert not Path("/etc/ghost-test").exists()


def test_no_network(folder):
    result = sandbox.preview("cat /sys/class/net/*/operstate 2>/dev/null | grep -c up; "
                             "bash -c 'echo > /dev/tcp/1.1.1.1/80' 2>&1 && echo connected || echo blocked", folder)
    assert "blocked" in result.output


def test_timeout(folder):
    result = sandbox.preview("sleep 30", folder)
    assert result.timed_out and result.exit_code is None
    assert result.seconds < 15


def test_waiting_for_input_does_not_hang(folder):
    result = sandbox.preview("read x; echo got:$x", folder)
    assert not result.timed_out
    assert "got:" in result.output


def test_elevated_is_skipped(folder):
    result = sandbox.preview("sudo rm -rf /", folder, elevated=True)
    assert result.mode == "skipped" and "administrator" in result.note


def test_large_folder_previews_with_changes(folder):
    many = folder / "many"
    many.mkdir()
    for i in range(6000):
        (many / f"f{i}.txt").write_text("x")
    result = sandbox.preview("rm many/f1*.txt; touch new.txt", folder)
    assert result.mode == "overlay"
    assert len(result.changes_of("deleted")) == 1111
    assert [c.path for c in result.changes_of("created")] == ["new.txt"]
    assert (many / "f1.txt").exists()
    assert result.seconds < 5


def test_replaced_folder_and_permissions(folder):
    result = sandbox.preview("rm -r src; mkdir src; echo n > src/b.py; chmod 600 keep.txt; cat notes.txt >> /dev/null", folder)
    kinds = {(c.path, c.kind) for c in result.changes}
    assert ("src/a.py", "deleted") in kinds and ("src/b.py", "created") in kinds
    assert ("keep.txt", "modified") in kinds
    assert not any(c.path == "notes.txt" for c in result.changes)
    assert (folder / "src" / "a.py").exists() and not (folder / "src" / "b.py").exists()


def test_read_only_fallback(folder, monkeypatch):
    monkeypatch.setattr(sandbox, "_overlay_works", lambda *a: False)
    result = sandbox.preview("touch new.txt 2>&1; ls", folder)
    assert result.mode == "read-only" and result.changes == ()
    assert "Read-only" in result.output or "read-only" in result.output.lower()
    assert not (folder / "new.txt").exists()


def test_output_is_truncated(folder):
    result = sandbox.preview("yes | head -c 100000", folder)
    assert result.truncated and len(result.output) == sandbox.MAX_OUTPUT_CHARS


def test_escape_sequences_removed():
    raw = "ok\x1b[31mred\x1b[0m\x1b]0;title\x07\x1b[2Jdone\rx"
    assert clean_terminal_output(raw) == "okreddonex"


def test_real_run(folder):
    result = sandbox.run("echo hi > out.txt; cat out.txt", folder)
    assert result.output.strip() == "hi" and result.exit_code == 0
    assert (folder / "out.txt").read_text() == "hi\n"


def test_real_run_timeout(folder):
    result = sandbox.run("sleep 30", folder, timeout=1)
    assert result.timed_out

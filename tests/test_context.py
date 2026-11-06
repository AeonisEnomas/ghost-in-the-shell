import os
from pathlib import Path

import pytest

from ghost_in_the_shell import context
from ghost_in_the_shell.context import SystemInfo


def test_system_info_reads_os_release():
    info = context.system_info()
    assert info.name and info.ids
    assert info.home == Path.home()


def test_missing_programs():
    assert context.missing_programs(("ls", "cd", "for", "definitely-not-a-program-xyz")) == [
        "definitely-not-a-program-xyz"]


def test_distro_hint_for_foreign_package_manager():
    arch = SystemInfo("Arch Linux", ("arch",), "pacman", "u", Path("/home/u"))
    hints = context.distro_hints(("apt-get",), arch) if not context.is_available("apt-get") else ["skip"]
    assert hints and ("pacman" in hints[0] or hints == ["skip"])
    assert context.distro_hints(("ls",), arch) == []
    assert "Windows" in context.distro_hints(("winget",), arch)[0]


@pytest.mark.parametrize("command, ok", [
    ("ls -la | wc -l", True),
    ("for f in *; do echo $f; done", True),
    ("echo 'unclosed", False),
    ("ls |", False),
    ("if true; then echo x", False),
])
def test_syntax(command, ok):
    assert (context.syntax_error(command) is None) == ok


def test_syntax_check_does_not_run(tmp_path):
    marker = tmp_path / "ran"
    assert context.syntax_error(f"touch {marker}") is None
    assert not marker.exists()


def test_resolve_folder(tmp_path):
    assert context.resolve_folder(str(tmp_path)) == tmp_path.resolve()
    assert context.resolve_folder("~") == Path.home().resolve()
    (tmp_path / "f.txt").write_text("x")
    for bad, message in [("", "Enter"), ("relative/path", "full path"), (str(tmp_path / "nope"), "does not exist"),
                         (str(tmp_path / "f.txt"), "is a file")]:
        with pytest.raises(ValueError, match=message):
            context.resolve_folder(bad)


def test_folder_info(tmp_path):
    (tmp_path / "b.txt").write_text("hello")
    (tmp_path / "a_dir").mkdir()
    (tmp_path / ".hidden").write_text("")
    (tmp_path / "evil\x1b[31mname").write_text("")
    info = context.folder_info(tmp_path)
    assert info.total == 4 and info.hidden == 1
    assert info.entries[0] == context.Entry("a_dir", True, None)
    assert context.Entry("b.txt", False, 5) in info.entries
    assert all("\x1b" not in e.name for e in info.entries)

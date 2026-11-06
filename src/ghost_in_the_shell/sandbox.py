"""Dry runs in a disposable sandbox, and real runs after the user confirms.

A preview runs the command with bubblewrap. The working folder is mounted at
its real path as an overlay: the real folder is the read-only lower layer, and
every write, edit or deletion lands in a throwaway upper layer. The real folder
is never touched, nothing is copied (so folders of any size preview
instantly), and afterwards the upper layer is exactly the list of changes:

- a regular file or folder that does not exist below was created;
- one that does exist below was modified (if its content or mode differ);
- a character device 0:0 ("whiteout") marks a deleted entry;
- a folder flagged opaque replaced the folder below, so the entries below it
  that are missing above were deleted.

Inside the sandbox the rest of the system is read-only, /home is replaced by
an empty folder (personal files outside the working folder can be neither read
nor changed), there is no network, and the command is stopped after a few
seconds, with limits on memory and the number of processes.

Commands that need administrator rights are not previewed: sudo cannot work
inside the sandbox, and a preview without the rights would be misleading.
"""

import filecmp
import os
import shutil
import signal
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .sanitize import clean_terminal_output

PREVIEW_TIMEOUT_S = 5
RUN_TIMEOUT_S = 60
MAX_OUTPUT_CHARS = 20_000
LIMITS = "ulimit -u 512 -v 4194304 -f 1048576 2>/dev/null"
OPAQUE_XATTRS = ("user.overlay.opaque", "trusted.overlay.opaque")


@dataclass(frozen=True)
class FileChange:
    path: str
    kind: Literal["created", "modified", "deleted"]
    is_dir: bool


@dataclass(frozen=True)
class Preview:
    mode: Literal["overlay", "read-only", "skipped"]
    note: str
    output: str = ""
    exit_code: int | None = None
    timed_out: bool = False
    truncated: bool = False
    changes: tuple[FileChange, ...] = ()
    seconds: float = 0.0

    def changes_of(self, kind: str) -> list[FileChange]:
        return [c for c in self.changes if c.kind == kind]


@dataclass(frozen=True)
class RunResult:
    output: str
    exit_code: int | None
    timed_out: bool
    truncated: bool
    seconds: float


def sandbox_available() -> bool:
    return shutil.which("bwrap") is not None


# ---------------------------------------------------------------- changes

def _is_whiteout(info: os.stat_result) -> bool:
    return stat.S_ISCHR(info.st_mode) and info.st_rdev == 0


def _is_opaque(path: Path) -> bool:
    for name in OPAQUE_XATTRS:
        try:
            if os.getxattr(path, name, follow_symlinks=False) == b"y":
                return True
        except OSError:
            continue
    return False


def _same_file(upper: Path, lower: Path) -> bool:
    try:
        a, b = upper.lstat(), lower.lstat()
    except OSError:
        return False
    if stat.S_IFMT(a.st_mode) != stat.S_IFMT(b.st_mode) or stat.S_IMODE(a.st_mode) != stat.S_IMODE(b.st_mode):
        return False
    if stat.S_ISLNK(a.st_mode):
        return os.readlink(upper) == os.readlink(lower)
    return a.st_size == b.st_size and filecmp.cmp(upper, lower, shallow=False)


def overlay_changes(upper: Path, lower: Path) -> tuple[FileChange, ...]:
    """Read the changes a command made from the overlay's upper layer."""
    changes: list[FileChange] = []
    for dirpath, dirnames, filenames in os.walk(upper):
        here = Path(dirpath)
        rel_dir = here.relative_to(upper)
        if here != upper and _is_opaque(here) and (lower / rel_dir).is_dir():
            present = set(dirnames) | set(filenames)
            for old in sorted(os.listdir(lower / rel_dir)):
                if old not in present:
                    changes.append(FileChange(str(rel_dir / old), "deleted", (lower / rel_dir / old).is_dir()))
        for name in dirnames + filenames:
            path, rel = here / name, rel_dir / name
            below = lower / rel
            info = path.lstat()
            exists_below = below.exists() or below.is_symlink()
            if _is_whiteout(info):
                if exists_below:
                    changes.append(FileChange(str(rel), "deleted", below.is_dir() and not below.is_symlink()))
            elif not exists_below:
                changes.append(FileChange(str(rel), "created", stat.S_ISDIR(info.st_mode)))
            elif stat.S_ISDIR(info.st_mode):
                if stat.S_IMODE(info.st_mode) != stat.S_IMODE(below.lstat().st_mode):
                    changes.append(FileChange(str(rel), "modified", True))
            elif not _same_file(path, below):
                changes.append(FileChange(str(rel), "modified", False))
    # Inside a created or deleted folder, list the folder only.
    folders = {c.path for c in changes if c.is_dir and c.kind != "modified"}
    kept = [c for c in changes if not any(c.path.startswith(f + os.sep) for f in folders)]
    return tuple(sorted(kept, key=lambda c: ("deleted", "modified", "created").index(c.kind)))


# ---------------------------------------------------------------- running

def _bwrap_args(cwd: Path, home: Path, overlay: tuple[Path, Path] | None) -> list[str]:
    args = [
        "bwrap", "--unshare-all", "--die-with-parent", "--new-session",
        "--ro-bind", "/", "/",
        "--dev", "/dev", "--proc", "/proc",
        "--tmpfs", "/tmp", "--tmpfs", "/var/tmp", "--tmpfs", "/run",
        "--tmpfs", "/home", "--dir", str(home),
    ]
    if overlay:
        upper, work = overlay
        args += ["--overlay-src", str(cwd), "--overlay", str(upper), str(work), str(cwd)]
    else:
        args += ["--ro-bind", str(cwd), str(cwd)]
    return args + [
        "--chdir", str(cwd),
        "--clearenv",
        "--setenv", "PATH", os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "--setenv", "HOME", str(home),
        "--setenv", "USER", os.environ.get("USER", "user"),
        "--setenv", "LANG", os.environ.get("LANG", "C.UTF-8"),
        "--setenv", "TERM", "dumb",
    ]


def _execute(args: list[str], timeout: float, cwd: Path | None = None,
             env: dict[str, str] | None = None) -> tuple[str, int | None, bool, bool]:
    """Run a process group with a timeout. Returns (output, exit code, timed out, truncated)."""
    process = subprocess.Popen(
        args, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, start_new_session=True,
    )
    try:
        raw, _ = process.communicate(timeout=timeout)
        code, timed_out = process.returncode, False
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        raw, _ = process.communicate()
        code, timed_out = None, True
    text = clean_terminal_output(raw.decode("utf-8", errors="replace"))
    truncated = len(text) > MAX_OUTPUT_CHARS
    return text[:MAX_OUTPUT_CHARS], code, timed_out, truncated


def _overlay_works(cwd: Path, home: Path, upper: Path, work: Path) -> bool:
    probe = subprocess.run([*_bwrap_args(cwd, home, (upper, work)), "true"],
                           capture_output=True, timeout=10)
    return probe.returncode == 0


def preview(command: str, cwd: Path, elevated: bool = False) -> Preview:
    """Dry-run `command` against an overlay of `cwd`."""
    cwd = cwd.resolve()
    if elevated:
        return Preview("skipped", "Commands that need administrator rights are not previewed: "
                                  "sudo cannot run in the sandbox. Read the explanation and risks carefully.")
    if not sandbox_available():
        return Preview("skipped", "Preview unavailable: bubblewrap (bwrap) is not installed.")

    start = time.perf_counter()
    home = Path.home()
    with tempfile.TemporaryDirectory(prefix="ghost-preview-", ignore_cleanup_errors=True) as tmp:
        upper, work = Path(tmp) / "upper", Path(tmp) / "work"
        upper.mkdir()
        work.mkdir()
        overlay = (upper, work) if _overlay_works(cwd, home, upper, work) else None
        output, code, timed_out, truncated = _execute(
            [*_bwrap_args(cwd, home, overlay), "bash", "-c", f"{LIMITS}; {command}"],
            timeout=PREVIEW_TIMEOUT_S,
        )
        changes = overlay_changes(upper, cwd) if overlay else ()
        # The kernel leaves an unreadable folder in the work directory.
        for path in work.rglob("*"):
            try:
                path.chmod(0o700)
            except OSError:
                pass
    if overlay:
        note = ("Ran against a throwaway layer over this folder; nothing was changed. Only this folder "
                "is tracked: effects elsewhere, such as in your home folder, are listed under Risk.")
    else:
        note = ("This system does not allow overlay mounts, so the preview ran read-only: commands "
                "that write files fail here, and changes cannot be listed.")
    if timed_out:
        note += (f" It was stopped after {PREVIEW_TIMEOUT_S} s; it may be slow, wait for input, "
                 "or never finish.")
    return Preview("overlay" if overlay else "read-only", note, output, code, timed_out, truncated,
                   changes, time.perf_counter() - start)


def run(command: str, cwd: Path, timeout: float = RUN_TIMEOUT_S) -> RunResult:
    """Run `command` for real in `cwd`. Only call after the user has confirmed."""
    start = time.perf_counter()
    output, code, timed_out, truncated = _execute(
        ["bash", "-c", command], timeout=timeout, cwd=cwd, env={**os.environ, "TERM": "dumb"},
    )
    return RunResult(output, code, timed_out, truncated, time.perf_counter() - start)

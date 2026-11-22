# Run a command against one of the five NL2SH-ALFA test filesystems.

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))

from common import HOST_MOUNTS, bwrap_args

SETUP_DIR = HERE / "filesystems"
TEMPLATE_DIR = HERE / ".built_filesystems"
ROOTS = ["testbed", "workspace", "system", "backup", "index", "root", "home", "tmp", "var"]

SPLITS = [153, 49, 57, 23, 18]
FS_ENV = {1: {"FILES": "/testbed/hello.c /testbed/FooBar.html"}}

TIMEOUT_S = 5
MAX_OUTPUT = 20_000


def fs_for_index(index: int) -> int:
    start = 0
    for fs_num, count in enumerate(SPLITS, start=1):
        if index < start + count:
            return fs_num
        start += count
    raise ValueError(f"index {index} out of range")


def build_filesystems() -> None:
    # Run each setup script once inside the sandbox to produce a fresh template.
    for fs_num in range(1, 6):
        target = TEMPLATE_DIR / f"fs{fs_num}"
        shutil.rmtree(target, ignore_errors=True)
        for root in ROOTS:
            (target / root).mkdir(parents=True)
        script = SETUP_DIR / f"setup_nl2b_fs_{fs_num}.sh"
        args = bwrap_args(target, FS_ENV.get(fs_num, {}))
        args = args[:-2] + ["--ro-bind", str(script), "/setup.sh", "--chdir", "/"]
        subprocess.run(args + ["bash", "/setup.sh"], capture_output=True, timeout=60)
        copy = target / script.name
        shutil.copyfile(script, copy)
        copy.chmod(0o755)


@dataclass
class RunResult:
    output: str
    exit_code: int
    manifest: dict[str, tuple]


def _manifest(fs_root: Path) -> dict[str, tuple]:
    entries: dict[str, tuple] = {}
    for top in fs_root.iterdir():
        if top.name in HOST_MOUNTS:
            continue
        rel = "/" + top.name
        st = top.lstat()
        if stat.S_ISLNK(st.st_mode):
            entries[rel] = ("l", os.readlink(top))
            continue
        if not stat.S_ISDIR(st.st_mode):
            entries[rel] = ("f", stat.S_IMODE(st.st_mode), hashlib.md5(top.read_bytes()).hexdigest())
            continue
        entries[rel] = ("d", stat.S_IMODE(st.st_mode))
        for dirpath, dirnames, filenames in os.walk(top, followlinks=False):
            for name in dirnames + filenames:
                path = Path(dirpath) / name
                rel = "/" + str(path.relative_to(fs_root))
                st = path.lstat()
                mode = stat.S_IMODE(st.st_mode)
                if stat.S_ISLNK(st.st_mode):
                    entries[rel] = ("l", os.readlink(path))
                elif stat.S_ISDIR(st.st_mode):
                    entries[rel] = ("d", mode)
                else:
                    try:
                        digest = hashlib.md5(path.read_bytes()).hexdigest()
                    except OSError:
                        digest = "unreadable"
                    entries[rel] = ("f", mode, digest)
    return entries


def run(command: str, fs_num: int) -> RunResult:
    # Execute `command` against a fresh copy of test filesystem `fs_num`.
    with tempfile.TemporaryDirectory(prefix="ghost-nl2sh-") as tmp:
        fs_root = Path(tmp) / "fs"
        shutil.copytree(TEMPLATE_DIR / f"fs{fs_num}", fs_root, symlinks=True)
        wrapped = f"ulimit -u 4096 -v 2097152 2>/dev/null; {command}"
        args = bwrap_args(fs_root, FS_ENV.get(fs_num, {})) + ["bash", "-c", wrapped]
        try:
            proc = subprocess.run(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, timeout=TIMEOUT_S)
            out, code = proc.stdout, proc.returncode
        except subprocess.TimeoutExpired as exc:
            out, code = exc.stdout or b"", -1
        for dirpath, dirnames, _ in os.walk(fs_root):
            dirnames[:] = [d for d in dirnames if d not in HOST_MOUNTS or dirpath != str(fs_root)]
            for name in dirnames:
                try:
                    os.chmod(Path(dirpath) / name, 0o755)
                except OSError:
                    pass
        return RunResult(out.decode("utf-8", errors="replace")[:MAX_OUTPUT], code, _manifest(fs_root))

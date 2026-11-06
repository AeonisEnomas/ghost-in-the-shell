"""Run shell commands in a throwaway bubblewrap sandbox and capture what they did.

Recreates the five InterCode-ALFA test filesystems (setup scripts from
github.com/westenfelder/InterCode-ALFA, MIT) without Docker. Each run gets a
fresh copy of the filesystem, no network, a read-only host /usr and /etc, and a
5 second timeout. A run returns the command's output plus a manifest of every
file under the test roots, so two commands can be compared by effect.
"""

import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).parent
SETUP_DIR = HERE / "fs_setup"
TEMPLATE_DIR = HERE / ".fs_templates"
ROOTS = ["testbed", "workspace", "system", "backup", "index", "root", "home", "tmp", "var"]
# Host directories mounted read-only (or virtual) on top of the writable root.
# They are excluded from the manifest.
HOST_MOUNTS = {"usr", "etc", "proc", "dev", "bin", "sbin", "lib", "lib64", "setup.sh"}

# Test rows map onto the 5 filesystems in order (from icalfa.main.index_to_img).
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


def _bwrap_args(fs_root: Path, env: dict[str, str]) -> list[str]:
    # fs_root itself becomes "/", so files written anywhere (e.g. `ln -s x /`) are captured.
    args = [
        "bwrap", "--unshare-all", "--die-with-parent", "--new-session",
        "--bind", str(fs_root), "/",
        "--ro-bind", "/usr", "/usr",
        "--symlink", "usr/bin", "/bin",
        "--symlink", "usr/bin", "/sbin",
        "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib", "/lib64",
        "--ro-bind", "/etc", "/etc",
        "--proc", "/proc", "--dev", "/dev",
        "--clearenv",
        "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin",
        "--setenv", "HOME", "/root",
        "--setenv", "LANG", "C.UTF-8",
        "--setenv", "TERM", "dumb",
    ]
    for key, value in env.items():
        args += ["--setenv", key, value]
    return args + ["--chdir", "/"]


def build_templates(force: bool = False) -> None:
    """Run each setup script once inside the sandbox to produce a template tree."""
    for fs_num in range(1, 6):
        target = TEMPLATE_DIR / f"fs{fs_num}"
        if target.exists() and not force:
            continue
        shutil.rmtree(target, ignore_errors=True)
        for root in ROOTS:
            (target / root).mkdir(parents=True)
        script = SETUP_DIR / f"setup_nl2b_fs_{fs_num}.sh"
        args = _bwrap_args(target, FS_ENV.get(fs_num, {}))
        args = args[:-2] + ["--ro-bind", str(script), "/setup.sh", "--chdir", "/"]
        subprocess.run(args + ["bash", "/setup.sh"], capture_output=True, timeout=60)
        # The InterCode Docker images keep a copy of the setup script at "/", and
        # 22 test prompts read it (e.g. "print the tenth line of setup_nl2b_fs_1.sh").
        copy = target / script.name
        shutil.copyfile(script, copy)
        copy.chmod(0o755)


@dataclass
class RunResult:
    output: str
    exit_code: int
    timed_out: bool
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
    """Execute `command` against a fresh copy of test filesystem `fs_num`."""
    with tempfile.TemporaryDirectory(prefix="ghost-sbx-") as tmp:
        fs_root = Path(tmp) / "fs"
        shutil.copytree(TEMPLATE_DIR / f"fs{fs_num}", fs_root, symlinks=True)
        # Cap processes and memory so a fork bomb or runaway command stays contained.
        wrapped = f"ulimit -u 4096 -v 2097152 2>/dev/null; {command}"
        args = _bwrap_args(fs_root, FS_ENV.get(fs_num, {})) + ["bash", "-c", wrapped]
        try:
            proc = subprocess.run(
                args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, timeout=TIMEOUT_S,
            )
            out, code, timed_out = proc.stdout, proc.returncode, False
        except subprocess.TimeoutExpired as exc:
            out, code, timed_out = exc.stdout or b"", -1, True
        # Make everything removable even if the command chmod'ed it away.
        for dirpath, dirnames, _ in os.walk(fs_root):
            dirnames[:] = [d for d in dirnames if d not in HOST_MOUNTS or dirpath != str(fs_root)]
            for name in dirnames:
                try:
                    os.chmod(Path(dirpath) / name, 0o755)
                except OSError:
                    pass
        manifest = _manifest(fs_root)
        text = out.decode("utf-8", errors="replace")[:MAX_OUTPUT]
        return RunResult(text, code, timed_out, manifest)


def normalize_output(text: str) -> str:
    lines = [line.rstrip() for line in text.strip().splitlines()]
    return "\n".join(lines)


if __name__ == "__main__":
    build_templates(force=True)
    for n in range(1, 6):
        files = sum(1 for _ in (TEMPLATE_DIR / f"fs{n}").rglob("*"))
        print(f"fs{n}: {files} entries")
    r = run("ls /testbed; touch /testbed/new.txt; rm -rf /usr 2>&1 | head -1", 1)
    print(r.exit_code, r.output[:300], "/testbed/new.txt" in r.manifest)

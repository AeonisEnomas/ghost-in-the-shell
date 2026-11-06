"""Facts about the system and the working folder.

These are used to check a suggested command (is the program installed? does
it belong to another Linux distribution?) and to show the folder in the
interface. They are deliberately not added to the model's prompt: the model
was fine-tuned on bare requests, and file names are attacker-controlled text
that would give prompt injection a way in.
"""

import functools
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .sanitize import clean_model_text

BASH_BUILTINS = set("""
alias bg bind break builtin caller cd command compgen complete compopt continue declare dirs disown
echo enable eval exec exit export false fc fg getopts hash help history jobs kill let local logout
mapfile popd printf pushd pwd read readarray readonly return set shift shopt source suspend test
times trap true type typeset ulimit umask unalias unset wait . : [ [[ ]] { } ! time coproc select
function if then else elif fi case esac for while until do done in
""".split())

# Package managers by distribution family (os-release ID and ID_LIKE values).
PACKAGE_MANAGERS = {
    "arch": "pacman", "debian": "apt", "ubuntu": "apt", "fedora": "dnf", "rhel": "dnf",
    "centos": "dnf", "suse": "zypper", "opensuse": "zypper", "alpine": "apk", "void": "xbps-install",
    "gentoo": "emerge", "nixos": "nix-env",
}
FOREIGN_TOOLS = {
    "apt": "apt", "apt-get": "apt", "apt-cache": "apt", "dpkg": "apt",
    "pacman": "pacman", "yay": "pacman", "paru": "pacman",
    "dnf": "dnf", "yum": "dnf", "rpm": "dnf", "zypper": "zypper", "apk": "apk",
    "brew": "brew", "port": "brew", "choco": "windows", "winget": "windows",
}


@dataclass(frozen=True)
class SystemInfo:
    name: str                 # "Arch Linux"
    ids: tuple[str, ...]      # ("arch",) or ("ubuntu", "debian")
    package_manager: str | None
    user: str
    home: Path


@dataclass(frozen=True)
class Entry:
    name: str
    is_dir: bool
    size: int | None


@dataclass(frozen=True)
class FolderInfo:
    path: Path
    entries: tuple[Entry, ...]
    total: int
    hidden: int


@functools.cache
def system_info() -> SystemInfo:
    fields: dict[str, str] = {}
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        try:
            for line in Path(path).read_text().splitlines():
                key, _, value = line.partition("=")
                fields[key] = value.strip().strip('"')
            break
        except OSError:
            continue
    ids = tuple(dict.fromkeys([fields.get("ID", "linux"), *fields.get("ID_LIKE", "").split()]))
    manager = next((PACKAGE_MANAGERS[i] for i in ids if i in PACKAGE_MANAGERS), None)
    return SystemInfo(fields.get("PRETTY_NAME", "Linux"), ids, manager,
                      os.environ.get("USER", "user"), Path.home())


def is_available(program: str) -> bool:
    return program in BASH_BUILTINS or shutil.which(program) is not None


def missing_programs(programs: tuple[str, ...]) -> list[str]:
    return [p for p in programs if p and not is_available(p)]


def distro_hints(programs: tuple[str, ...], info: SystemInfo | None = None) -> list[str]:
    """Explain when a command uses another distribution's tools."""
    info = info or system_info()
    hints = []
    for program in programs:
        family = FOREIGN_TOOLS.get(program)
        if family and info.package_manager and family != info.package_manager and not is_available(program):
            if family == "windows":
                hints.append(f"{program} is a Windows tool and does not exist on Linux.")
            else:
                hints.append(f"{program} belongs to another distribution; {info.name} uses "
                             f"{info.package_manager}.")
    return hints


def syntax_error(command: str) -> str | None:
    """Ask bash to parse the command without running it."""
    try:
        result = subprocess.run(["bash", "-n", "-c", command], capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired:
        return "bash could not parse the command in time."
    if result.returncode == 0:
        return None
    message = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "syntax error"
    return clean_model_text(message.replace("bash: -c: ", ""))


def resolve_folder(text: str) -> Path:
    """Turn user input into a usable folder path, or raise ValueError with a message."""
    text = text.strip()
    if not text:
        raise ValueError("Enter a folder path.")
    if "\x00" in text:
        raise ValueError("The path contains an invalid character.")
    path = Path(os.path.expandvars(os.path.expanduser(text)))
    if not path.is_absolute():
        raise ValueError("Use a full path, starting with / or ~.")
    path = path.resolve()
    if not path.exists():
        raise ValueError(f"{path} does not exist.")
    if not path.is_dir():
        raise ValueError(f"{path} is a file, not a folder.")
    if not os.access(path, os.R_OK | os.X_OK):
        raise ValueError(f"You do not have permission to open {path}.")
    return path


def folder_info(path: Path, limit: int = 300) -> FolderInfo:
    entries, total, hidden = [], 0, 0
    try:
        with os.scandir(path) as scan:
            for item in scan:
                total += 1
                if item.name.startswith("."):
                    hidden += 1
                    continue
                if len(entries) >= limit:
                    continue
                try:
                    is_dir = item.is_dir(follow_symlinks=False)
                    size = None if is_dir else item.stat(follow_symlinks=False).st_size
                except OSError:
                    is_dir, size = False, None
                # Names are shown, never sent to a model, but they can still
                # contain control characters that garble the display.
                entries.append(Entry(clean_model_text(item.name) or "?", is_dir, size))
    except OSError:
        pass
    entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
    return FolderInfo(path, tuple(entries), total, hidden)

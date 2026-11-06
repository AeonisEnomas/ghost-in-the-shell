"""Risk assessment of a shell command before it is previewed or run.

The command is parsed with bashlex into the simple commands it would execute.
Quoting tricks (r''m), wrappers (sudo, env, xargs, timeout), nested shells
(bash -c "..."), command substitution and find -exec are unwrapped, so the
check sees the programs that would actually run. Each simple command and each
redirection is then matched against rules that describe its effect.

Every command gets one of four levels:

  READ_ONLY  only reads or prints
  CHANGES    creates or edits files in an ordinary, recoverable way
  CAUTION    deletes or overwrites, needs admin rights, uses the network,
             or does something the check cannot see into
  DANGER     can destroy data or the system in a way that is hard to undo

The check is advisory and errs on the side of CAUTION: a program it does not
know is never reported as read-only.
"""

import re
import shlex
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

import bashlex


class Level(IntEnum):
    READ_ONLY = 0
    CHANGES = 1
    CAUTION = 2
    DANGER = 3

    @property
    def label(self) -> str:
        return {0: "Read-only", 1: "Makes changes", 2: "Caution", 3: "Dangerous"}[self.value]


@dataclass(frozen=True)
class Finding:
    level: Level
    title: str
    detail: str


@dataclass(frozen=True)
class Assessment:
    command: str
    level: Level
    findings: tuple[Finding, ...]
    programs: tuple[str, ...]
    elevated: bool
    fully_parsed: bool

    @property
    def needs_typed_confirmation(self) -> bool:
        return self.level is Level.DANGER


@dataclass
class _Simple:
    """One program invocation, with the context it runs in."""
    argv: list[str]
    redirects: list[tuple[str, str]] = field(default_factory=list)
    pipeline: int = -1        # index of the pipeline it belongs to, -1 if alone
    position: int = 0         # position inside that pipeline
    elevated: bool = False
    dynamic_name: bool = False
    via_xargs: bool = False   # operands arrive on standard input


# ---------------------------------------------------------------- paths

SYSTEM_DIRS = ("/etc", "/usr", "/bin", "/sbin", "/lib", "/lib64", "/boot", "/var", "/opt",
               "/srv", "/root", "/sys", "/proc", "/dev", "/home", "/mnt", "/media")
DISK_DEVICE = re.compile(r"^/dev/(sd|hd|vd|xvd|nvme|mmcblk|disk|mapper|md|loop)")
HARMLESS_TARGETS = {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty", "-", "&1", "&2"}


def _path_scope(path: str) -> str | None:
    """Describe a path that covers far more than a single project, or None."""
    p = path.rstrip("/") or "/"
    if p in {"/", "/*", "/.*"}:
        return "the whole filesystem"
    if p in {"~", "~/*", "~/.*", "$HOME", "$HOME/*", "${HOME}", "${HOME}/*"} or re.fullmatch(r"/home/[^/]+(/\*)?", p):
        return "your home folder"
    if p in {"*", ".", "./*", ".*", "..", "../*"}:
        return "everything in the current folder"
    for top in SYSTEM_DIRS:
        if p == top or p.startswith(top + "/"):
            return f"the system folder {top}"
    return None


def _is_glob(word: str) -> bool:
    return any(c in word for c in "*?[")


# ---------------------------------------------------------------- parsing

WRAPPERS_WITH_ARG = {
    "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U", "-T"},
    "doas": {"-u", "-C"},
    "run0": {"-u", "--user"},
    "pkexec": {"--user"},
    "nice": {"-n", "--adjustment"},
    "ionice": {"-c", "-n", "-p"},
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
    "stdbuf": {"-i", "-o", "-e"},
    "xargs": {"-I", "-n", "-P", "-d", "-L", "-s", "-E", "-a", "--max-args", "--max-procs",
              "--delimiter", "--arg-file", "--replace"},
    "nohup": set(), "time": set(), "command": set(), "builtin": set(), "exec": set(),
    "env": {"-u", "--unset", "-C", "--chdir"}, "watch": {"-n", "--interval"},
    "chroot": set(), "unbuffer": set(), "caffeinate": set(), "strace": {"-o", "-e", "-p"},
}
ELEVATORS = {"sudo", "doas", "run0", "pkexec", "su"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish", "busybox"}
INTERPRETERS = SHELLS | {"python", "python3", "perl", "ruby", "node", "php", "lua", "source", "."}


def _unwrap(argv: list[str]) -> tuple[list[str], bool, bool, list[list[str]]]:
    """Strip wrappers such as sudo or xargs.

    Returns (argv, elevated, via_xargs, nested commands).
    """
    elevated = via_xargs = False
    nested: list[list[str]] = []
    while argv:
        name = _base(argv[0])
        if name == "su":
            elevated = True
            if "-c" in argv and argv.index("-c") + 1 < len(argv):
                nested.append(["bash", "-c", argv[argv.index("-c") + 1]])
            return [], elevated, via_xargs, nested
        if name not in WRAPPERS_WITH_ARG:
            break
        elevated |= name in ELEVATORS
        via_xargs |= name == "xargs"
        takes_arg = WRAPPERS_WITH_ARG[name]
        i = 1
        while i < len(argv):
            word = argv[i]
            if name == "env" and "=" in word and not word.startswith("-"):
                i += 1
            elif word.startswith("-") and word != "-":
                i += 2 if word in takes_arg else 1
            elif name == "timeout" and re.fullmatch(r"[\d.]+[smhd]?", word):
                i += 1
            else:
                break
        argv = argv[i:]
    return argv, elevated, via_xargs, nested


def _find_root(argv: list[str]) -> str:
    return argv[1] if len(argv) > 1 and not argv[1].startswith("-") else "."


def _base(word: str) -> str:
    return word.lstrip("\\").rsplit("/", 1)[-1]


class _Collector:
    """Walk a bashlex tree and collect simple commands."""

    def __init__(self) -> None:
        self.commands: list[_Simple] = []
        self.pipelines = 0
        self.extra_sources: list[str] = []   # strings to parse recursively (bash -c, eval)

    def visit(self, node, pipeline: int = -1, position: int = 0) -> None:
        kind = node.kind
        if kind == "pipeline":
            index = self.pipelines
            self.pipelines += 1
            stages = [p for p in node.parts if p.kind != "pipe"]
            for pos, stage in enumerate(stages):
                self.visit(stage, index, pos)
            return
        if kind == "command":
            self._command(node, pipeline, position)
            return
        for child in getattr(node, "parts", []) or []:
            self.visit(child, pipeline, position)
        for attr in ("list", "command"):
            child = getattr(node, attr, None)
            if child is not None and hasattr(child, "kind"):
                self.visit(child, pipeline, position)

    def _substitutions(self, word_node) -> None:
        for part in getattr(word_node, "parts", []) or []:
            if part.kind in ("commandsubstitution", "processsubstitution"):
                self.visit(part.command)
            else:
                self._substitutions(part)

    def _command(self, node, pipeline: int, position: int) -> None:
        argv, redirects, dynamic = [], [], False
        for part in node.parts:
            if part.kind == "word":
                self._substitutions(part)
                if not argv and ("$" in part.word or "`" in part.word or any(
                        p.kind in ("commandsubstitution", "parameter") for p in part.parts or [])):
                    dynamic = True
                argv.append(part.word)
            elif part.kind == "redirect":
                target = part.output
                if hasattr(target, "word"):
                    self._substitutions(target)
                    text = target.word
                else:
                    text = f"&{target}"
                redirects.append((str(part.type), text))
        self.add(argv, redirects, pipeline, position, dynamic)

    def add(self, argv, redirects, pipeline, position, dynamic=False, elevated=False) -> None:
        argv, wrapped_elevated, via_xargs, nested = _unwrap(argv)
        elevated = elevated or wrapped_elevated
        for inner in nested:
            self.add(inner, [], pipeline, position, elevated=elevated)
        if not argv:
            if redirects:
                self.commands.append(_Simple([], redirects, pipeline, position, elevated))
            return
        name = _base(argv[0])
        if name in SHELLS and "-c" in argv[1:]:
            i = argv.index("-c")
            if i + 1 < len(argv):
                self.extra_sources.append(argv[i + 1])
        if name == "eval":
            self.extra_sources.append(" ".join(argv[1:]))
        if name == "find":
            self._find_exec(argv, pipeline, position, elevated)
        self.commands.append(_Simple(argv, redirects, pipeline, position, elevated, dynamic, via_xargs))

    def _find_exec(self, argv, pipeline, position, elevated) -> None:
        root = _find_root(argv)
        broad = (_path_scope(root) or "everything in the current folder") != "everything in the current folder"
        i = 0
        while i < len(argv):
            if argv[i] in ("-exec", "-execdir", "-ok", "-okdir"):
                j = i + 1
                inner = []
                while j < len(argv) and argv[j] not in (";", "\\;", "+"):
                    inner.append(argv[j])
                    j += 1
                # "{}" stands for each file found. When the search covers a wide
                # area, give it the scope of the search root.
                inner = [root if w == "{}" and broad else w for w in inner]
                if inner:
                    self.add(inner, [], pipeline, position, elevated=elevated)
                i = j
            i += 1


def _fallback_split(command: str) -> list[list[str]]:
    """Rough split used when bashlex cannot parse the command."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>")
    lexer.whitespace_split = True
    commands, current = [], []
    try:
        for token in lexer:
            if token and set(token) <= set(";&|()"):
                if current:
                    commands.append(current)
                current = []
            else:
                current.append(token)
    except ValueError:
        return [command.split()]
    if current:
        commands.append(current)
    return commands


def _collect(command: str, depth: int = 0) -> tuple[list[_Simple], bool]:
    collector = _Collector()
    parsed = True
    try:
        for tree in bashlex.parse(command):
            collector.visit(tree)
    except Exception:
        parsed = False
        for argv in _fallback_split(command):
            collector.add(argv, [], -1, 0)
    commands = collector.commands
    if depth < 3:
        for source in collector.extra_sources:
            inner, inner_parsed = _collect(source, depth + 1)
            commands += inner
            parsed &= inner_parsed
    return commands, parsed


# ---------------------------------------------------------------- rules

READ_ONLY_PROGRAMS = set("""
ls ll dir cat tac head tail less more bat grep egrep fgrep rg ag ack find fd locate which whereis type
file stat wc du df free ps pstree top htop uptime date cal whoami id groups hostname uname echo printf
pwd printenv sort uniq cut tr awk gawk sed diff cmp comm md5sum sha1sum sha256sum sha512sum b2sum
cksum basename dirname realpath readlink tree seq xxd od hexdump strings column nl paste join fold fmt
rev expand unexpand jq yq lsblk lscpu lsusb lspci lsmem lsmod lsof ip ss netstat last lastlog w who
history test [ true false sleep man help tldr apropos whatis info journalctl dmesg getent nproc arch tty
cd pushd popd dirs bc expr numfmt base64 base32 zcat zgrep zless bzcat xzcat tar unzip zipinfo env
export alias set read wait jobs fg bg vmstat iostat mpstat sensors lsattr findmnt blkid hostnamectl
timedatectl localectl loginctl systemd-analyze nslookup dig host ping traceroute tracepath whois
pacman apt apt-get apt-cache dpkg rpm dnf yum zypper flatpak snap pip pip3 npm git docker podman
systemctl service ufw iptables nft mount umount crontab xdg-open open less diffstat pgrep pidof
shuf neofetch fastfetch screenfetch printenv locale getconf ulimit tput clear reset sha224sum sha384sum
""".split())

# Programs in READ_ONLY_PROGRAMS that are only read-only for some arguments.
# Their writing forms are caught by the rules below.

CREATES = {"mkdir", "touch", "ln", "tee", "zip", "gzip", "gunzip", "bzip2", "bunzip2", "xz", "unxz",
           "7z", "rsync", "install", "mktemp", "split", "csplit", "convert", "ffmpeg", "wget", "curl"}
# Programs that send or fetch data. Simple lookups (ping, dig, host) are not listed.
NETWORK = {"curl", "wget", "ssh", "scp", "sftp", "ftp", "rsync", "nc", "ncat", "netcat", "telnet", "aria2c"}
DISK_TOOLS = {"mkfs", "wipefs", "shred", "fdisk", "sfdisk", "gdisk", "sgdisk", "parted", "mkswap",
              "cryptsetup", "blkdiscard", "badblocks", "hdparm", "fstrim"}
POWER = {"reboot", "shutdown", "poweroff", "halt"}
PACKAGE_MANAGERS = {"pacman", "yay", "paru", "apt", "apt-get", "dpkg", "rpm", "dnf", "yum", "zypper",
                    "snap", "flatpak", "pip", "pip3", "npm", "pnpm", "yarn", "gem", "cargo", "brew"}
PACKAGE_READ = re.compile(r"^(-Q\w*|-Ss?\w*|-Si|-F\w*|list|search|show|info|policy|-l|-L|-s|freeze|query|outdated|--version|-V)$")


def _options(argv: list[str]) -> str:
    """All single-letter options joined, e.g. ['rm', '-rf', '-v'] -> 'rfv'."""
    letters = ""
    for word in argv[1:]:
        if word == "--":
            break
        if word.startswith("-") and not word.startswith("--"):
            letters += word[1:]
    return letters


def _operands(argv: list[str]) -> list[str]:
    out, after_dashdash = [], False
    for word in argv[1:]:
        if word == "--" and not after_dashdash:
            after_dashdash = True
        elif after_dashdash or not word.startswith("-"):
            out.append(word)
    return out


def _rule_rm(argv: list[str]) -> list[Finding]:
    opts, targets = _options(argv), _operands(argv)
    recursive = bool(set(opts) & {"r", "R"}) or "--recursive" in argv
    if "--no-preserve-root" in argv:
        return [Finding(Level.DANGER, "Can delete the whole system",
                        "--no-preserve-root removes the safeguard that stops rm from deleting /.")]
    findings = []
    for target in targets:
        scope = _path_scope(target)
        if scope and (recursive or _is_glob(target) or scope != "everything in the current folder"):
            findings.append(Finding(Level.DANGER, "Deletes a large set of files",
                                    f"Removes {target}: {scope}. Deleted files do not go to the trash."))
        elif recursive and _is_glob(target):
            findings.append(Finding(Level.DANGER, "Deletes folders matching a pattern",
                                    f"Recursively removes everything matching {target}."))
    if findings:
        return findings
    targets = ["each file found" if t == "{}" else t for t in targets]
    shown = ", ".join(targets[:3]) + ("…" if len(targets) > 3 else "")
    if recursive:
        return [Finding(Level.CAUTION, "Deletes a folder and its contents",
                        f"Removes {shown or 'every folder it receives'} and everything inside. This cannot be undone.")]
    return [Finding(Level.CAUTION, "Deletes files",
                    f"Removes {shown or 'every file it receives'}. Deleted files do not go to the trash.")]


def _rule_permissions(argv: list[str]) -> list[Finding]:
    name, opts, operands = _base(argv[0]), _options(argv), _operands(argv)
    recursive = "R" in opts or "--recursive" in argv
    targets = operands[1:] if operands else []
    for target in targets:
        scope = _path_scope(target)
        if scope and (recursive or scope != "everything in the current folder"):
            return [Finding(Level.DANGER, "Changes ownership or permissions broadly",
                            f"{name} on {target} affects {scope}; this can lock you out or break the system.")]
    if name == "chmod" and operands and re.search(r"(^|[^0-7])7?77$|a\+w|o\+w|\+rwx", operands[0]):
        return [Finding(Level.CAUTION, "Makes files writable by everyone",
                        f"Mode {operands[0]} lets any user change these files.")]
    return [Finding(Level.CAUTION, "Changes permissions or ownership",
                    f"{name} changes who can read, write or run {', '.join(targets[:3]) or 'the files'}.")]


def _rule_move_copy(argv: list[str]) -> list[Finding]:
    name, operands = _base(argv[0]), _operands(argv)
    if not operands:
        return []
    destination, sources = operands[-1], operands[:-1]
    if destination == "/dev/null":
        return [Finding(Level.DANGER, "Moves files into nothing",
                        "Moving to /dev/null destroys the files.")]
    for path in [destination, *sources]:
        scope = _path_scope(path)
        if scope and scope.startswith(("the system", "the whole")):
            return [Finding(Level.DANGER, "Moves or overwrites system files",
                            f"{name} touches {path}, part of {scope}.")]
    if name == "mv" and any(_path_scope(s) for s in sources):
        return [Finding(Level.CAUTION, "Moves many files at once",
                        f"Moves {', '.join(sources[:3])} to {destination}.")]
    no_clobber = "n" in _options(argv) or "--no-clobber" in argv or "--update=none" in argv
    if no_clobber:
        return [Finding(Level.CHANGES, "Copies or moves files", f"{name} into {destination}; existing files are kept.")]
    verb = "Moves or renames" if name == "mv" else "Copies"
    return [Finding(Level.CAUTION, f"{verb} files and may overwrite",
                    f"Files already at {destination} with the same name are replaced without asking.")]


def _rule_find(argv: list[str]) -> list[Finding]:
    if "-delete" not in argv:
        return []
    root = _find_root(argv)
    scope = _path_scope(root)
    if scope and scope != "everything in the current folder":
        return [Finding(Level.DANGER, "Deletes matching files across a wide area",
                        f"find -delete under {root} ({scope}). Deleted files do not go to the trash.")]
    return [Finding(Level.CAUTION, "Deletes every file that matches",
                    f"find -delete removes each match under {root}. Check the preview to see which files.")]


def _rule_dd(argv: list[str]) -> list[Finding]:
    for word in argv[1:]:
        if word.startswith("of="):
            target = word[3:]
            if DISK_DEVICE.match(target):
                return [Finding(Level.DANGER, "Writes directly to a disk",
                                f"dd overwrites the device {target}; everything on it is lost.")]
            return [Finding(Level.CAUTION, "Overwrites a file", f"dd writes raw data to {target}.")]
    return []


def _rule_git(argv: list[str]) -> list[Finding]:
    words = argv[1:]
    sub = next((w for w in words if not w.startswith("-")), "")
    if sub == "reset" and "--hard" in words:
        return [Finding(Level.DANGER, "Discards uncommitted work", "git reset --hard throws away all uncommitted changes.")]
    if sub == "clean" and any(w.startswith("-") and "f" in w for w in words):
        return [Finding(Level.DANGER, "Deletes untracked files", "git clean -f permanently deletes files git does not track.")]
    if sub == "push" and any(w in ("-f", "--force") or w.startswith("--force") for w in words):
        return [Finding(Level.DANGER, "Overwrites remote history", "A force push can delete other people's commits.")]
    if sub in ("checkout", "restore") and ("." in words or "--" in words):
        return [Finding(Level.CAUTION, "Discards local edits", f"git {sub} can overwrite uncommitted changes.")]
    if sub in ("branch",) and any(w in ("-D", "-d", "--delete") for w in words):
        return [Finding(Level.CAUTION, "Deletes a branch", "The branch is removed.")]
    if sub in ("stash",) and any(w in ("drop", "clear") for w in words):
        return [Finding(Level.CAUTION, "Deletes stashed work", "Stashed changes are discarded.")]
    if sub in ("push", "pull", "fetch", "clone"):
        return [Finding(Level.CAUTION, "Uses the network", f"git {sub} talks to a remote server.")]
    if sub in ("commit", "add", "merge", "rebase", "rm", "mv", "init", "tag", "switch", "cherry-pick", "revert", "apply", "am"):
        return [Finding(Level.CHANGES, "Changes the repository", f"git {sub} changes the repository state.")]
    return []


def _rule_docker(argv: list[str]) -> list[Finding]:
    words = argv[1:]
    text = " ".join(words)
    if re.search(r"\bsystem prune\b", text) or re.search(r"\b(volume|image|container) prune\b", text):
        level = Level.DANGER if ("-a" in words or "--all" in words or "volume" in words) else Level.CAUTION
        return [Finding(level, "Deletes containers, images or data", f"{_base(argv[0])} {text[:60]} removes stored data.")]
    if words and words[0] in ("rm", "rmi") and re.search(r"\$\((docker|podman) ", text):
        return [Finding(Level.DANGER, "Removes every container or image",
                        f"The list of targets is every {words[0] == 'rm' and 'container' or 'image'} on the system.")]
    if words and words[0] in ("rm", "rmi", "kill", "stop") or text.startswith(("volume rm", "image rm", "container rm")):
        return [Finding(Level.CAUTION, "Removes or stops containers", f"{_base(argv[0])} {words[0]} changes running services.")]
    if words and words[0] in ("run", "exec", "build", "pull", "push", "compose", "start", "restart"):
        return [Finding(Level.CAUTION, "Runs or changes containers", f"{_base(argv[0])} {words[0]} may download images or run code.")]
    return []


PACKAGE_READ_WORDS = {"list", "ls", "search", "show", "info", "policy", "freeze", "query", "outdated", "view"}


def _rule_packages(argv: list[str]) -> list[Finding]:
    words = argv[1:]
    if not words or PACKAGE_READ.match(words[0]) or words[0] in PACKAGE_READ_WORDS:
        return []
    return [Finding(Level.CAUTION, "Installs, updates or removes software",
                    f"{_base(argv[0])} changes installed packages. This usually needs admin rights.")]


def _rule_systemctl(argv: list[str]) -> list[Finding]:
    words = argv[1:]
    sub = next((w for w in words if not w.startswith("-")), "")
    if sub in ("reboot", "poweroff", "halt", "kexec", "suspend", "hibernate"):
        return [Finding(Level.DANGER, "Restarts or powers off the computer", f"systemctl {sub} ends every running program.")]
    if sub in ("stop", "disable", "mask", "kill") and any(re.search(r"firewall|ufw|nftables|iptables|sshd?|NetworkManager|systemd-", w) for w in words):
        return [Finding(Level.DANGER, "Stops a critical service", f"systemctl {sub} on a service that protects or connects the system.")]
    if sub in ("start", "stop", "restart", "reload", "enable", "disable", "mask", "unmask", "kill", "edit", "daemon-reload", "set-default", "isolate"):
        return [Finding(Level.CAUTION, "Changes system services", f"systemctl {sub} changes which services run.")]
    return []


def _rule_kill(argv: list[str]) -> list[Finding]:
    name, words = _base(argv[0]), argv[1:]
    if name == "killall5" or (name == "kill" and "-1" in words[-1:]) or (name in ("pkill", "killall") and words[-1:] in (["."], [".*"])):
        return [Finding(Level.DANGER, "Stops every process", "This ends all of your running programs, possibly the session itself.")]
    return [Finding(Level.CAUTION, "Stops running programs", f"{name} ends processes; unsaved work in them is lost.")]


def _rule_network_firewall(argv: list[str]) -> list[Finding]:
    name, words = _base(argv[0]), argv[1:]
    if (name == "ufw" and "disable" in words) or (name == "iptables" and any(w in ("-F", "--flush") for w in words)) \
            or (name == "nft" and "flush" in words):
        return [Finding(Level.DANGER, "Turns off the firewall", "The computer would accept connections it currently blocks.")]
    if name in ("ufw", "iptables", "nft") and any(not w.startswith("-") and w not in ("status", "list") for w in words):
        if not (name == "iptables" and set(words) & {"-L", "-S", "--list"}):
            return [Finding(Level.CAUTION, "Changes firewall rules", f"{name} changes which connections are allowed.")]
    return []


def _rule_users(argv: list[str]) -> list[Finding]:
    name = _base(argv[0])
    if name in ("userdel", "deluser", "groupdel", "delgroup"):
        return [Finding(Level.DANGER, "Deletes a user or group", f"{name} removes an account; with -r also its files.")]
    return [Finding(Level.CAUTION, "Changes user accounts", f"{name} changes accounts or passwords.")]


def _rule_crontab(argv: list[str]) -> list[Finding]:
    if "-r" in argv[1:]:
        return [Finding(Level.DANGER, "Deletes all scheduled jobs", "crontab -r removes your whole crontab without asking.")]
    if "-l" in argv[1:]:
        return []
    return [Finding(Level.CAUTION, "Changes scheduled jobs", "crontab replaces or edits scheduled tasks.")]


def _rule_sed_like(argv: list[str]) -> list[Finding]:
    name = _base(argv[0])
    if any(w == "-i" or w.startswith("-i") and name in ("sed", "perl") or w.startswith("--in-place") for w in argv[1:]):
        return [Finding(Level.CAUTION, "Edits files in place", f"{name} -i rewrites the files directly, without a backup.")]
    if name in ("awk", "gawk") and re.search(r"\bsystem\s*\(|\|\s*\"|>\s*\"", " ".join(argv[1:])):
        return [Finding(Level.CAUTION, "Runs commands or writes files from awk", "The awk program calls system() or writes to files.")]
    return []


def _rule_archive(argv: list[str]) -> list[Finding]:
    name, opts = _base(argv[0]), _options(argv)
    if name == "tar":
        # tar also accepts bundled letters without a dash: "tar czf out.tgz dir".
        if len(argv) > 1 and not argv[1].startswith("-"):
            opts += argv[1]
        if "t" in opts or "--list" in argv:
            return []
        if set(opts) & {"x"} or "--extract" in argv:
            return [Finding(Level.CAUTION, "Extracts an archive", "Files from the archive can overwrite files with the same name.")]
        if set(opts) & {"c", "r", "u"}:
            return [Finding(Level.CHANGES, "Creates an archive", "Writes a new archive file.")]
        return []
    if name == "unzip":
        if set(opts) & {"l", "t", "v", "Z"}:
            return []
        return [Finding(Level.CAUTION, "Extracts an archive", "unzip may ask to overwrite, or overwrite with -o.")]
    if name in ("gzip", "bzip2", "xz") and not set(opts) & {"c", "k", "l", "t"}:
        return [Finding(Level.CAUTION, "Replaces the original file", f"{name} deletes each original after compressing it.")]
    return []


def _rule_mount(argv: list[str]) -> list[Finding]:
    if len(argv) == 1 or argv[1:] in (["-l"], ["--list"]):
        return []
    return [Finding(Level.CAUTION, "Mounts or unmounts a filesystem", f"{_base(argv[0])} changes which disks are attached.")]


def _rule_ip(argv: list[str]) -> list[Finding]:
    if set(argv[1:]) & {"set", "add", "del", "delete", "flush", "change", "replace"}:
        return [Finding(Level.CAUTION, "Changes network settings", "This can disconnect the computer from the network.")]
    return []


def _rule_history(argv: list[str]) -> list[Finding]:
    if any(w in ("-c", "-w", "-d") or w.startswith("-c") for w in argv[1:]):
        return [Finding(Level.CAUTION, "Erases shell history", "Removes the record of previous commands.")]
    return []


RULES = {
    "rm": _rule_rm, "unlink": _rule_rm,
    "chmod": _rule_permissions, "chown": _rule_permissions, "chgrp": _rule_permissions,
    "mv": _rule_move_copy, "cp": _rule_move_copy,
    "find": _rule_find, "dd": _rule_dd, "git": _rule_git,
    "docker": _rule_docker, "podman": _rule_docker,
    "systemctl": _rule_systemctl, "service": _rule_systemctl,
    "kill": _rule_kill, "pkill": _rule_kill, "killall": _rule_kill, "killall5": _rule_kill,
    "ufw": _rule_network_firewall, "iptables": _rule_network_firewall, "nft": _rule_network_firewall,
    "userdel": _rule_users, "deluser": _rule_users, "groupdel": _rule_users, "delgroup": _rule_users,
    "useradd": _rule_users, "usermod": _rule_users, "passwd": _rule_users, "chpasswd": _rule_users,
    "crontab": _rule_crontab, "sed": _rule_sed_like, "perl": _rule_sed_like, "awk": _rule_sed_like,
    "gawk": _rule_sed_like, "tar": _rule_archive, "unzip": _rule_archive, "gzip": _rule_archive,
    "bzip2": _rule_archive, "xz": _rule_archive, "mount": _rule_mount, "umount": _rule_mount,
    "ip": _rule_ip, "history": _rule_history,
}


def _rule_redirect(op: str, target: str, cwd: Path | None = None) -> list[Finding]:
    if target in HARMLESS_TARGETS or op in ("<", "<<", "<<<", "<&", ">&") and not target.startswith("/"):
        return []
    if op.startswith("<"):
        return []
    if DISK_DEVICE.match(target):
        return [Finding(Level.DANGER, "Writes directly to a disk", f"Output goes straight onto {target}, destroying its contents.")]
    scope = _path_scope(target)
    if scope and scope.startswith(("the system", "the whole")):
        return [Finding(Level.DANGER, "Overwrites a system file", f"Writes to {target}, part of {scope}.")]
    if ">>" in op:
        return [Finding(Level.CHANGES, "Appends to a file", f"Adds output to the end of {target}.")]
    if cwd is not None and not any(c in target for c in "$`*?~") and not (cwd / target).exists():
        return [Finding(Level.CHANGES, "Creates a file", f"Writes the output to a new file, {target}.")]
    return [Finding(Level.CAUTION, "Overwrites a file", f"Replaces the contents of {target} if it already exists.")]


def _rule_program(simple: _Simple) -> list[Finding]:
    argv = simple.argv
    name = _base(argv[0])
    findings: list[Finding] = []
    if simple.dynamic_name:
        findings.append(Finding(Level.CAUTION, "Program chosen at run time",
                                f"The program name {argv[0]} comes from a variable or substitution, so it cannot be checked."))
        return findings
    if re.match(r"mkfs(\.\w+)?$", name) or name in DISK_TOOLS:
        findings.append(Finding(Level.DANGER, "Erases or reformats a disk",
                                f"{name} can wipe a disk or partition; the data cannot be recovered."))
    elif name in POWER or (name == "init" and argv[1:2] in (["0"], ["6"])):
        findings.append(Finding(Level.DANGER, "Restarts or powers off the computer",
                                f"{name} ends every running program."))
    elif name in RULES:
        findings += RULES[name](argv)
    elif name in PACKAGE_MANAGERS:
        findings += _rule_packages(argv)
    elif name in ("eval", "source", "."):
        findings.append(Finding(Level.CAUTION, "Runs code built at run time",
                                f"{name} executes text as commands; only its literal parts were checked."))
    elif name in INTERPRETERS:
        if not any(w == "-c" for w in argv[1:]) and len(argv) > 1:
            findings.append(Finding(Level.CAUTION, "Runs a script",
                                    f"{name} runs {argv[1]}; the script's contents are not checked."))
        elif name not in SHELLS and any(w == "-c" for w in argv[1:]):
            findings.append(Finding(Level.CAUTION, "Runs inline code",
                                    f"{name} -c runs code that is not checked."))
    elif argv[0].startswith(("./", "../", "/")) and name not in READ_ONLY_PROGRAMS | CREATES:
        findings.append(Finding(Level.CAUTION, "Runs a local program",
                                f"{argv[0]} is a program or script whose effects are not checked."))
    elif name in CREATES:
        if name in ("ln",) and "f" in _options(argv):
            findings.append(Finding(Level.CAUTION, "Replaces existing links or files", "ln -f overwrites the destination."))
        elif name == "tee":
            for target in _operands(argv):
                findings += _rule_redirect(">>" if "a" in _options(argv) else ">", target)
        elif name not in NETWORK:
            findings.append(Finding(Level.CHANGES, "Creates or changes files", f"{name} writes files."))
    elif name not in READ_ONLY_PROGRAMS | NETWORK | SENDERS:
        findings.append(Finding(Level.CAUTION, "Unrecognised program",
                                f"{name} is not in the list of known programs, so its effects are not checked."))
    if name in NETWORK:
        findings.append(Finding(Level.CAUTION, "Uses the network", f"{name} connects to other computers."))
        if name in ("curl", "wget") and any(w in ("-o", "-O", "--output") or w.startswith("-o") for w in argv[1:]):
            findings.append(Finding(Level.CHANGES, "Downloads a file", "Saves downloaded data to disk."))
    return findings


PRIVATE_DATA = re.compile(r"\.ssh|\.gnupg|_history\b|/etc/shadow|\bid_(rsa|ed25519|ecdsa)|\.pem\b|\.key\b|"
                          r"\.password|\.netrc|\.aws|keyring|\.kube/config")
SENDERS = {"nc", "ncat", "netcat", "curl", "wget", "scp", "rsync", "sftp", "ftp", "telnet", "ssh", "socat"}


def _rule_upload(simple: "_Simple", stages: list["_Simple"]) -> list[Finding]:
    """Data leaving the computer: uploads, and local data piped into a network program."""
    name = _base(simple.argv[0])
    words = simple.argv[1:]
    uploads = (name in ("curl",) and any(w in ("-T", "--upload-file", "-d", "--data", "--data-binary", "-F", "--form")
                                         or w.startswith(("-d@", "-F", "--data=@")) for w in words)) \
        or (name == "wget" and any(w.startswith(("--post-file", "--body-file")) for w in words)) \
        or name in ("scp", "rsync", "sftp") \
        or (name in SENDERS and simple.position > 0)
    if not uploads:
        return []
    sources = " ".join(w for s in stages for w in s.argv) if stages else " ".join(words)
    if PRIVATE_DATA.search(sources):
        return [Finding(Level.DANGER, "Sends private data to another computer",
                        "Keys, passwords or shell history would leave this machine; this cannot be taken back.")]
    return [Finding(Level.CAUTION, "Sends data to another computer",
                    f"{name} uploads local data over the network.")]


FORK_BOMB = re.compile(r"(\w+|:)\s*\(\)\s*\{[^}]*\1\s*\|\s*\1")


def assess(command: str, cwd: Path | None = None) -> Assessment:
    """Assess the risk of running `command`, optionally in folder `cwd`."""
    findings: list[Finding] = []
    if FORK_BOMB.search(command):
        findings.append(Finding(Level.DANGER, "Fork bomb", "Starts copies of itself until the computer freezes."))

    simples, parsed = _collect(command)
    if not parsed:
        findings.append(Finding(Level.CAUTION, "Only partly understood",
                                "The command uses syntax the checker cannot fully parse, so some effects may be missed."))

    elevated = any(s.elevated for s in simples)
    if elevated:
        findings.append(Finding(Level.CAUTION, "Needs administrator rights",
                                "Runs with sudo or similar, so mistakes can affect the whole system."))

    by_pipeline: dict[int, list[_Simple]] = {}
    for simple in simples:
        if simple.argv:
            findings += _rule_program(simple)
        for op, target in simple.redirects:
            findings += _rule_redirect(op, target, cwd)
        if simple.argv and _base(simple.argv[0]) in SENDERS:
            same_pipeline = [s for s in simples if s.pipeline == simple.pipeline] if simple.pipeline >= 0 else []
            findings += _rule_upload(simple, same_pipeline)
        if simple.pipeline >= 0:
            by_pipeline.setdefault(simple.pipeline, []).append(simple)

    for stages in by_pipeline.values():
        # Keep one command per stage: the first one collected at each position
        # (find's -exec commands share the position of find itself).
        stages = list({s.position: s for s in reversed(stages)}.values())
        stages.sort(key=lambda s: s.position)
        names = [_base(s.argv[0]) if s.argv else "" for s in stages]
        for i, name in enumerate(names[1:], start=1):
            if name in INTERPRETERS and not any(w == "-c" for w in stages[i].argv[1:]):
                source = "downloaded" if set(names[:i]) & {"curl", "wget"} else "generated"
                findings.append(Finding(Level.DANGER, "Runs piped text as code",
                                        f"Feeds {source} text into {name}, which executes it unchecked."))
        # "find ROOT ... | xargs rm": the files come from the search, so the
        # deletion covers the search root.
        first = stages[0]
        if first.argv and _base(first.argv[0]) == "find":
            scope = _path_scope(_find_root(first.argv))
            for stage in stages[1:]:
                destructive = stage.argv and _base(stage.argv[0]) in {"rm", "shred", "unlink", "chmod", "chown", "mv"}
                if stage.via_xargs and destructive and scope and scope != "everything in the current folder":
                    findings.append(Finding(Level.DANGER, "Acts on every file found across a wide area",
                                            f"{_base(stage.argv[0])} runs on each file find returns from {scope}."))

    findings = _dedupe(findings)
    level = max((f.level for f in findings), default=Level.READ_ONLY)
    programs = tuple(dict.fromkeys(_base(s.argv[0]) for s in simples if s.argv))
    return Assessment(command, level, tuple(sorted(findings, key=lambda f: -f.level)), programs, elevated, parsed)


def _dedupe(findings: list[Finding]) -> list[Finding]:
    seen, out = set(), []
    for finding in findings:
        key = (finding.level, finding.title, finding.detail)
        if key not in seen:
            seen.add(key)
            out.append(finding)
    return out

"""HTML fragments for the interface.

Every value that comes from the user, the file system or a model goes through
html.escape (the function `e`) before it is placed in markup, so a file name,
request or model reply can never inject HTML or script into the page.
"""

import re
import socket
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from ..safety import Assessment, Finding, Level
from ..sandbox import FileChange, Preview

LEVEL_CLASS = {Level.READ_ONLY: "read", Level.CHANGES: "change", Level.CAUTION: "caution", Level.DANGER: "danger"}
LEVEL_GLYPH = {Level.READ_ONLY: "○", Level.CHANGES: "●", Level.CAUTION: "▲", Level.DANGER: "■"}
LEVEL_SUMMARY = {
    Level.READ_ONLY: "Only reads information. Nothing on your system changes.",
    Level.CHANGES: "Creates or edits files in an ordinary, recoverable way.",
    Level.CAUTION: "Can delete or overwrite data, or reaches beyond this folder.",
    Level.DANGER: "Can destroy data or break the system.",
}
LEVEL_MEANING = {
    Level.READ_ONLY: "Lists, searches, counts and prints. Runs on click.",
    Level.CHANGES: "Creates folders, archives or new files, or appends to files. Runs on click.",
    Level.CAUTION: "Deletes or overwrites files, needs admin rights, uses the network, or runs code the "
                   "checker cannot see into. Asks first, showing the files it would touch.",
    Level.DANGER: "Recursive deletes of large areas, disk wipes, system-wide permission changes, downloads "
                  "piped into a shell, private data sent away. Needs the word run typed.",
}

# The ghost's face is a shell prompt, ">_", like the app's mark. Drawn as
# pixel art: "#" body, "c" prompt (cyan), "m" cursor (magenta), "." empty.
GHOST = [
    "....########....",
    "..############..",
    ".##############.",
    "################",
    "###cc###########",
    "####cc##########",
    "#####cc#########",
    "####cc##mmmmm###",
    "###cc###mmmmm###",
    "################",
    "################",
    "################",
    "##.###..###..##.",
    "#...#....#....#.",
]


def ghost_svg(pixel: int = 9) -> str:
    """Pixel art for static/ghost.svg (regenerate the file after changing GHOST)."""
    rects = []
    for y, row in enumerate(GHOST):
        for x, cell in enumerate(row):
            colour = {"#": "#5CE1E6", "c": "#0B0E13", "m": "#E28CFF"}.get(cell)
            if colour:
                rects.append(f'<rect x="{x * pixel}" y="{y * pixel}" width="{pixel}" height="{pixel}" fill="{colour}"/>')
    width, height = len(GHOST[0]) * pixel, len(GHOST) * pixel
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" '
            f'height="{height}" shape-rendering="crispEdges">{"".join(rects)}</svg>')


def e(value: object) -> str:
    return escape(str(value), quote=True)


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def duration(seconds: float) -> str:
    return f"{seconds * 1000:.0f} ms" if seconds < 1 else f"{seconds:.1f} s"


def host_name() -> str:
    return socket.gethostname().split(".")[0] or "localhost"


def short_path(path: Path) -> str:
    home = Path.home()
    try:
        return "~/" + str(path.relative_to(home)) if path != home else "~"
    except ValueError:
        return str(path)


def display_path(path: Path, limit: int = 52) -> str:
    """Shorten a long path from the left, keeping the folders nearest to it."""
    text = short_path(path)
    if len(text) <= limit:
        return text
    parts = Path(text).parts
    kept: list[str] = []
    for part in reversed(parts):
        if len("/".join([part, *kept])) + 2 > limit:
            break
        kept.insert(0, part)
    return "…/" + "/".join(kept or [parts[-1]])


def time_ago(moment: datetime) -> str:
    seconds = (datetime.now(timezone.utc) - moment).total_seconds()
    if seconds < 60:
        return "just now"
    for limit, size, unit in ((3600, 60, "min"), (86400, 3600, "h"), (604800, 86400, "d")):
        if seconds < limit:
            return f"{int(seconds // size)} {unit} ago"
    return moment.astimezone().strftime("%d %b %Y")


def _inline_code(escaped: str) -> str:
    # Runs on text that is already escaped, so the backtick spans can only
    # contain escaped characters.
    return re.sub(r"`([^`\n]{1,80})`", r"<code>\1</code>", escaped)


# ---------------------------------------------------------------- shell

def status_bar(system_name: str, package_manager: str | None, folder: Path, ready: bool,
               feed_size: int, last: str) -> str:
    dot = "ok" if ready else "wait"
    cells = [
        f'<span class="sb-cell"><span class="sb-dot {dot}"></span>generator</span>',
        f'<span class="sb-cell"><span class="sb-dot {dot}"></span>explainer</span>',
        f'<span class="sb-cell sb-dim">{e(system_name)}{" · " + e(package_manager) if package_manager else ""}</span>',
        f'<span class="sb-cell sb-path">{e(display_path(folder, 46))}</span>',
        f'<span class="sb-cell sb-dim">{e(plural(feed_size, "block"))}</span>',
    ]
    if last:
        cells.append(f'<span class="sb-cell sb-dim">last {e(last)}</span>')
    right = ('<span class="sb-cell sb-keys"><b>ctrl k</b> commands</span>'
             '<span class="sb-cell sb-keys"><b>/</b> prompt</span>'
             '<span class="sb-cell sb-keys sb-offline">offline</span>')
    return f'<footer class="statusbar" role="status">{"".join(cells)}<span class="sb-fill"></span>{right}</footer>'


def sidebar_brand() -> str:
    return ('<div class="sbrand"><span class="sbrand-name">ghost<span class="sbrand-dim"> in the </span>shell</span>'
            '<span class="sbrand-tag">talk to linux in plain english</span></div>')


def sidebar_heading(text: str) -> str:
    return f'<div class="sside-h">{e(text)}</div>'


def title_bar(user: str, host: str, folder: Path, total: int, hidden: int) -> str:
    extra = f" · {hidden} hidden" if hidden else ""
    return (f'<div class="tbar" title="{e(folder)}"><span class="tbar-dots"><i></i><i></i><i></i></span>'
            f'<span class="tbar-title"><span class="u">{e(user)}@{e(host)}</span><span class="c">:</span>'
            f'<span class="p">{e(display_path(folder, 60))}</span></span>'
            f'<span class="tbar-meta">{e(plural(total - hidden, "item"))}{e(extra)}</span></div>')


def banner() -> str:
    return f"""
<section class="banner">
  <img class="banner-art" src="/app/static/ghost.svg" alt="" width="144" height="126">
  <div class="banner-text">
    <h1 class="banner-title">ghost in the shell</h1>
    <p class="banner-sub">Say what you want done. Get one command, a plain-English explanation, a risk
    rating and a dry run that lists every file it would touch. Nothing runs until you say so.</p>
    <dl class="banner-keys">
      <div><dt>enter</dt><dd>send</dd></div><div><dt>tab</dt><dd>ask ↔ explain</dd></div>
      <div><dt>↑ ↓</dt><dd>earlier requests</dd></div><div><dt>ctrl k</dt><dd>commands</dd></div>
    </dl>
  </div>
</section>
<div class="banner-try">try one of these</div>"""


def system_line(message: str, score: float | None, phrases: tuple[str, ...], tone: str = "warn") -> str:
    detail = ""
    if phrases:
        quoted = ", ".join(f"<q>{e(p)}</q>" for p in phrases)
        detail = (f"<p>It contains wording aimed at the assistant itself: {quoted}. Requests like this can trick "
                  f"a model into writing a harmful command.</p>")
    elif score is not None:
        detail = f"<p>Estimated chance that this is a shell task: {score:.0%}.</p>"
    if tone != "error":
        detail += ("<p>Rephrase it, or continue anyway: the command will still be rated and tried in the "
                   "sandbox before anything can run.</p>")
    return (f'<div class="sysline sysline--{tone}" role="alert"><span class="sysline-tag">ghost</span>'
            f'<div><strong>{e(message)}</strong>{detail}</div></div>')


# ---------------------------------------------------------------- inspector panels

def panel_head(label: str, meta: str = "", tone: str = "") -> str:
    tag = '<span class="ph-ai">ai</span>' if tone == "ai" else ""
    return (f'<div class="ph ph--{e(tone or "plain")}"><span class="ph-label">{tag}{e(label)}</span>'
            f'<span class="ph-rule"></span><span class="ph-meta">{e(meta)}</span></div>')


def risk_pill(level: Level) -> str:
    return (f'<span class="pill pill--{LEVEL_CLASS[level]}"><span aria-hidden="true">'
            f'{LEVEL_GLYPH[level]}</span>{e(level.label)}</span>')


def _findings(findings) -> str:
    items = "".join(
        f'<li class="fd fd--{LEVEL_CLASS[f.level]}"><span class="fd-g" aria-hidden="true">{LEVEL_GLYPH[f.level]}</span>'
        f'<span class="fd-b"><strong>{e(f.title)}</strong><span>{e(f.detail)}</span></span></li>'
        for f in findings)
    return f'<ul class="fds">{items}</ul>' if items else ""


def risk_body(assessment: Assessment, issues: tuple[str, ...]) -> str:
    level = assessment.level
    issue_html = ""
    if issues:
        rows = "".join(f"<li>{e(i)}</li>" for i in issues)
        issue_html = f'<div class="issues" role="alert"><strong>before you run it</strong><ul>{rows}</ul></div>'
    partial = ('<p class="note">Part of this command could not be analysed, so treat the rating as a minimum.</p>'
               if not assessment.fully_parsed else "")
    return (f'<div class="risk risk--{LEVEL_CLASS[level]}"><div class="risk-top">{risk_pill(level)}'
            f'<span>{e(LEVEL_SUMMARY[level])}</span></div>{_findings(assessment.findings)}</div>{issue_html}{partial}')


def explanation(text: str) -> str:
    paragraphs = "".join(f"<p>{_inline_code(e(p))}</p>" for p in text.split("\n") if p.strip())
    return f'<div class="explain">{paragraphs}</div>'


def explanation_live(text: str, done: bool) -> str:
    if not text:
        return ('<div class="explain explain--wait"><span class="caret"></span>'
                '<em>the base model is reading the command…</em></div>')
    return f'<div class="explain explain--live"><p>{_inline_code(e(text))}<span class="caret"></span></p></div>'


def change_tiles(preview: Preview) -> str:
    if preview.mode != "overlay":
        return ""
    tiles = "".join(
        f'<div class="tile tile--{kind}{" tile--zero" if not n else ""}">'
        f'<span class="tile-n">{n}</span><span class="tile-l">{kind}</span></div>'
        for kind, n in (("deleted", len(preview.changes_of("deleted"))),
                        ("modified", len(preview.changes_of("modified"))),
                        ("created", len(preview.changes_of("created")))))
    return f'<div class="tiles">{tiles}</div>'


def changes(items: tuple[FileChange, ...], limit: int = 300) -> str:
    if not items:
        return '<p class="note">No files would be created, changed or deleted.</p>'
    marks = {"created": "+", "modified": "~", "deleted": "−"}

    def path_html(change: FileChange) -> str:
        folder, _, name = change.path.rpartition("/")
        folder_html = f'<span class="ch-dir">{e(folder)}/</span>' if folder else ""
        return f'{folder_html}<span class="ch-name">{e(name)}{"/" if change.is_dir else ""}</span>'

    rows = "".join(
        f'<li class="ch ch--{c.kind}"><span class="ch-m" aria-label="{c.kind}">{marks[c.kind]}</span>'
        f'<span class="ch-p">{path_html(c)}</span></li>' for c in items[:limit])
    more = f'<li class="ch ch--more">and {len(items) - limit} more</li>' if len(items) > limit else ""
    return f'<ul class="chs">{rows}{more}</ul>'


def change_summary_text(preview: Preview) -> str:
    if preview.mode == "skipped":
        return "not previewed"
    if preview.mode == "read-only":
        return "read-only preview"
    parts = [f"{len(preview.changes_of(k))} {k}" for k in ("deleted", "modified", "created") if preview.changes_of(k)]
    return " · ".join(parts) or "no file changes"


def terminal_output(text: str, exit_code: int | None, truncated: bool) -> str:
    if not text.strip():
        return '<p class="note">The command printed nothing.</p>'
    lines = text.rstrip("\n").split("\n")
    body = "\n".join(e(line) for line in lines[:400])
    more = '\n<span class="tout-more">… output shortened</span>' if truncated or len(lines) > 400 else ""
    return f'<pre class="tout">{body}{more}</pre>'


def note(text: str) -> str:
    return f'<p class="note">{e(text)}</p>'


def dialog_summary(command: str, level: Level, findings: tuple[Finding, ...], preview: Preview, folder: str) -> str:
    counts = ""
    if preview.mode == "overlay":
        counts = change_tiles(preview) + changes(preview.changes, limit=12)
    elif preview.mode == "skipped":
        counts = note(preview.note)
    return (f'<div class="dlg"><div class="dlg-cmd"><span class="dlg-d">$</span><code>{e(command)}</code></div>'
            f'<div class="dlg-where">in <b>{e(folder)}</b> · {risk_pill(level)}</div>'
            f'{_findings(findings)}{counts}</div>')


# ---------------------------------------------------------------- history

def stat_strip(stats: list[tuple[str, str]]) -> str:
    cells = "".join(f'<div class="stat"><span class="stat-n">{e(v)}</span><span class="stat-l">{e(k)}</span></div>'
                    for k, v in stats)
    return f'<div class="stats">{cells}</div>'


def page_head(command: str, title: str, lede: str) -> str:
    return (f'<header class="phead"><div class="phead-cmd"><span>$</span> {e(command)}</div>'
            f'<h1 class="phead-title">{e(title)}</h1><p class="phead-lede">{e(lede)}</p></header>')


# ---------------------------------------------------------------- manual page

def man_page(sections: list[tuple[str, str]], version: str, date: str) -> str:
    """`sections` are (heading, html) pairs; the html must be built with this module's escaping helpers."""
    body = "".join(f'<section class="man-s"><h2>{e(h)}</h2><div class="man-b">{html}</div></section>'
                   for h, html in sections)
    return (f'<article class="man"><div class="man-top"><span>GHOST(1)</span><span>Ghost in the Shell Manual</span>'
            f'<span>GHOST(1)</span></div>{body}<div class="man-top man-bottom"><span>ghost-in-the-shell {e(version)}</span>'
            f'<span>{e(date)}</span><span>GHOST(1)</span></div></article>')


def man_paragraphs(*texts: str) -> str:
    return "".join(f"<p>{e(t)}</p>" for t in texts)


def man_options(rows: list[tuple[str, str]]) -> str:
    return "".join(f'<div class="man-o"><span class="man-k">{e(k)}</span><span>{e(v)}</span></div>' for k, v in rows)


def man_levels() -> str:
    return "".join(f'<div class="man-o">{risk_pill(level)}<span>{e(LEVEL_MEANING[level])}</span></div>' for level in Level)


def man_pipeline() -> str:
    stages = [
        ("clean", "Removes model control codes and invisible characters from what you type."),
        ("gate", "A TF-IDF classifier checks that it is a shell task; wording aimed at the assistant is flagged."),
        ("write", "The fine-tuned model writes exactly one line. Invalid answers are retried."),
        ("rate", "A bash parser unwraps sudo, pipes, xargs and nested shells, then applies risk rules."),
        ("try", "The command runs over a throwaway layer of your folder, with no network and your home hidden."),
        ("decide", "You see all of the above. Only you can run it, and never with admin rights."),
    ]
    return ('<ol class="man-flow">' + "".join(
        f'<li><span class="man-n">{i}</span><span class="man-k">{e(t)}</span><span>{e(d)}</span></li>'
        for i, (t, d) in enumerate(stages, start=1)) + "</ol>")

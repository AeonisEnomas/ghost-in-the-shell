"""Interactive components built with Streamlit's component API (v2).

Four pieces of the interface need real client-side behaviour: the terminal
prompt (Tab switches mode, arrow keys recall earlier requests), the command
blocks in the session feed (Run, Edit, Copy, Focus), the Ctrl+K command
palette, and the history table (click a row to reopen it).

The HTML, CSS and JavaScript here are fixed strings written for the app. All
dynamic values (requests, commands, file names, model output) arrive through
`data` and are inserted with `textContent`, never as HTML, so they cannot
inject markup or script into the page.
"""

import streamlit as st

_FONT = "'IBM Plex Mono', ui-monospace, monospace"

_BASE_CSS = f"""
:host {{ --bg: #0B0E13; --panel: #10141B; --panel2: #151A23; --line: #222936; --line2: #2E3746;
  --text: #D5DCE6; --muted: #8590A3; --faint: #576072; --cyan: #5CE1E6; --magenta: #E28CFF;
  --green: #7EE2A8; --blue: #6CB6FF; --yellow: #F5C451; --red: #FF6B7A; --sand: #D9CBA3;
  font-family: {_FONT}; color: var(--text); }}
* {{ box-sizing: border-box; }}
button {{ font: inherit; color: inherit; background: none; border: 0; cursor: pointer; }}
button:focus-visible, input:focus-visible {{ outline: 2px solid var(--cyan); outline-offset: 2px; }}
.lvl-read {{ --lvl: var(--green); }} .lvl-change {{ --lvl: var(--blue); }}
.lvl-caution {{ --lvl: var(--yellow); }} .lvl-danger {{ --lvl: var(--red); }}
"""

_HELPERS = """
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}
// Light syntax colouring of a shell command. Every piece is placed with
// textContent; the regex only decides which span a piece goes into.
function colourCommand(target, command) {
  target.replaceChildren();
  const parts = command.match(/(\\s+|'[^']*'?|"(?:[^"\\\\]|\\\\.)*"?|\\|\\||&&|[|;&<>]+|[^\\s|;&<>'"]+)/g) || [command];
  let expectProgram = true;
  for (const part of parts) {
    let cls = '';
    if (/^\\s+$/.test(part)) { target.append(document.createTextNode(part)); continue; }
    if (/^(\\|\\||&&|[|;&<>]+)$/.test(part)) { cls = 'op'; expectProgram = !/^[<>]/.test(part); }
    else if (/^['"]/.test(part)) cls = 'str';
    else if (/^-/.test(part)) cls = 'flag';
    else if (/^\\$/.test(part)) cls = 'var';
    else if (expectProgram && !/=/.test(part)) { cls = 'prog'; expectProgram = ['sudo','xargs','env','time','nohup','exec'].includes(part); }
    target.append(el('span', cls, part));
  }
}
"""

# ---------------------------------------------------------------- prompt

_PROMPT_CSS = _BASE_CSS + """
.prompt { background: linear-gradient(180deg, #121821, #0E131A); border: 1px solid var(--line2); border-radius: 10px;
  padding: 10px 12px 8px; box-shadow: 0 -12px 40px rgba(0,0,0,0.45), 0 0 0 1px rgba(92,225,230,0.04) inset; }
.prompt:focus-within { border-color: rgba(92,225,230,0.55); box-shadow: 0 -12px 40px rgba(0,0,0,0.45), 0 0 0 3px rgba(92,225,230,0.10); }
.line { display: flex; align-items: center; gap: 10px; min-width: 0; }
.mode { font-size: 11px; letter-spacing: .08em; text-transform: uppercase; padding: 3px 8px; border-radius: 4px;
  border: 1px solid; flex: none; }
.mode.ask { color: var(--cyan); border-color: rgba(92,225,230,.45); background: rgba(92,225,230,.08); }
.mode.explain { color: var(--magenta); border-color: rgba(226,140,255,.45); background: rgba(226,140,255,.08); }
.ps1 { flex: none; font-size: 13.5px; white-space: nowrap; max-width: 34%; overflow: hidden; text-overflow: ellipsis; }
.ps1 .u { color: var(--green); } .ps1 .cwd { color: var(--blue); } .ps1 .colon { color: var(--faint); }
.sym { color: var(--cyan); font-weight: 500; flex: none; }
.in { flex: 1; min-width: 0; background: transparent; border: 0; outline: none; color: var(--text); font: inherit;
  font-size: 15px; caret-color: var(--cyan); padding: 6px 0; }
.in::placeholder { color: var(--faint); }
.in:focus-visible { outline: none; }
.send { flex: none; color: var(--bg); background: var(--cyan); border-radius: 6px; padding: 6px 12px; font-size: 13px; font-weight: 500; }
.send:hover { filter: brightness(1.1); }
.prompt.explain .send { background: var(--magenta); }
.hints { display: flex; gap: 16px; margin-top: 7px; font-size: 11px; color: var(--faint); flex-wrap: wrap; }
.hints b { color: var(--muted); font-weight: 500; }
.working .send { opacity: .5; pointer-events: none; }
.working .hints::before { content: "working"; color: var(--cyan); animation: blink 1s steps(2) infinite; }
@keyframes blink { 50% { opacity: .3; } }
@media (max-width: 700px) { .ps1 { display: none; } .hints { display: none; } }
"""

_PROMPT_JS = _HELPERS + """
const PLACEHOLDER = {
  ask: 'describe a task, e.g. find files over 100 MB here',
  explain: 'paste a command to explain and check it',
};
export default function (component) {
  const { data, setTriggerValue, setStateValue, parentElement } = component;
  let root = parentElement.querySelector('.prompt');
  if (!root) {
    root = el('div', 'prompt');
    const line = el('div', 'line');
    const mode = el('button', 'mode'); mode.type = 'button'; mode.title = 'Switch mode (Tab)';
    const ps1 = el('span', 'ps1');
    const sym = el('span', 'sym', '❯');
    const input = el('input', 'in'); input.spellcheck = false; input.autocomplete = 'off';
    input.setAttribute('aria-label', 'Request');
    const send = el('button', 'send', 'run ⏎'); send.type = 'button';
    line.append(mode, ps1, sym, input, send);
    const hints = el('div', 'hints');
    for (const [k, t] of [['tab', 'switch mode'], ['↑ ↓', 'earlier requests'], ['enter', 'send'], ['ctrl k', 'commands']]) {
      const span = el('span'); span.append(el('b', '', k), document.createTextNode(' ' + t)); hints.append(span);
    }
    root.append(line, hints);
    parentElement.appendChild(root);

    let recall = -1;
    const setMode = (m) => {
      root.dataset.mode = m; mode.textContent = m; mode.className = 'mode ' + m;
      root.classList.toggle('explain', m === 'explain'); input.placeholder = PLACEHOLDER[m];
      input.setAttribute('aria-label', m === 'ask' ? 'Request' : 'Command');
      setStateValue('mode', m);
    };
    const submit = () => {
      const text = input.value.trim();
      if (!text) return;
      root.classList.add('working');
      setTriggerValue('submit', { text, mode: root.dataset.mode, at: Date.now() });
      input.value = ''; recall = -1;
    };
    mode.addEventListener('click', () => { setMode(root.dataset.mode === 'ask' ? 'explain' : 'ask'); input.focus(); });
    send.addEventListener('click', submit);
    input.addEventListener('keydown', (e) => {
      const past = root._history || [];
      if (e.key === 'Enter') { e.preventDefault(); submit(); }
      else if (e.key === 'Tab' && !e.shiftKey) { e.preventDefault(); setMode(root.dataset.mode === 'ask' ? 'explain' : 'ask'); }
      else if (e.key === 'ArrowUp' && past.length) { e.preventDefault(); recall = Math.min(recall + 1, past.length - 1); input.value = past[recall]; }
      else if (e.key === 'ArrowDown' && past.length) { e.preventDefault(); recall = Math.max(recall - 1, -1); input.value = recall < 0 ? '' : past[recall]; }
    });
    window.addEventListener('ghost:focus-prompt', () => input.focus());
    window.addEventListener('ghost:set-mode', (e) => { setMode(e.detail); input.focus(); });
    window.addEventListener('ghost:fill-prompt', (e) => { input.value = e.detail; input.focus(); });
    setMode(data.mode || 'ask');
  }
  root.classList.remove('working');
  root._history = data.history || [];
  const ps1 = root.querySelector('.ps1');
  ps1.replaceChildren(el('span', 'u', data.user + '@' + data.host), el('span', 'colon', ':'), el('span', 'cwd', data.folder));
  ps1.title = data.folder_full || data.folder;
  if (data.fill) { const input = root.querySelector('.in'); input.value = data.fill; input.focus(); }
}
"""

_prompt = st.components.v2.component("ghost.prompt", css=_PROMPT_CSS, js=_PROMPT_JS)


def prompt(*, mode: str, user: str, host: str, folder: str, folder_full: str, history: list[str],
           fill: str = "", on_submit=None, key: str = "prompt"):
    return _prompt(data={"mode": mode, "user": user, "host": host, "folder": folder, "folder_full": folder_full,
                         "history": history, "fill": fill},
                   key=key, on_submit_change=on_submit or (lambda: None), on_mode_change=lambda: None)


# ---------------------------------------------------------------- command block

_BLOCK_CSS = _BASE_CSS + """
.block { position: relative; border: 1px solid var(--line); border-radius: 10px; background: var(--panel);
  overflow: hidden; transition: border-color .15s; }
.block::before { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--lvl); opacity: .85; }
.block.focused { border-color: var(--line2); background: #121821; box-shadow: 0 0 0 1px rgba(92,225,230,.08); }
.block.danger-focus { border-color: rgba(255,107,122,.5); }
.head { display: flex; align-items: baseline; gap: 10px; padding: 9px 14px 0 16px; font-size: 12.5px; min-width: 0; }
.head .cwd { color: var(--blue); flex: none; max-width: 30%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.head .sym { color: var(--cyan); flex: none; }
.head .req { color: var(--text); font-family: 'IBM Plex Sans', system-ui, sans-serif; font-size: 13.5px; flex: 1;
  min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.head .req.pasted { color: var(--muted); font-style: italic; }
.head .time { color: var(--faint); flex: none; }
.cmdline { display: flex; align-items: flex-start; gap: 10px; padding: 8px 14px 8px 16px; }
.dollar { color: var(--faint); user-select: none; padding-top: 1px; }
.cmd { flex: 1; min-width: 0; font-size: 15px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; color: var(--text); }
.cmd .prog { color: #F2F5F9; font-weight: 500; } .cmd .flag { color: #9FB1CC; } .cmd .str { color: var(--sand); }
.cmd .op { color: var(--cyan); } .cmd .var { color: var(--magenta); }
.badge { flex: none; font-size: 11px; letter-spacing: .07em; text-transform: uppercase; color: var(--lvl);
  border: 1px solid color-mix(in srgb, var(--lvl) 45%, transparent); background: color-mix(in srgb, var(--lvl) 9%, transparent);
  border-radius: 4px; padding: 2px 7px; margin-top: 2px; white-space: nowrap; }
.foot { display: flex; align-items: center; gap: 12px; padding: 7px 10px 7px 16px; border-top: 1px dashed var(--line);
  font-size: 12px; color: var(--muted); flex-wrap: wrap; }
.sum { display: flex; gap: 10px; }
.sum .d { color: var(--red); } .sum .m { color: var(--yellow); } .sum .c { color: var(--green); } .sum .z { color: var(--faint); }
.meta { color: var(--faint); }
.spacer { flex: 1; }
.act { padding: 4px 9px; border-radius: 5px; color: var(--muted); border: 1px solid transparent; font-size: 12px; }
.act:hover { color: var(--text); background: var(--panel2); border-color: var(--line2); }
.act.run { color: var(--bg); background: var(--cyan); font-weight: 500; }
.act.run:hover { filter: brightness(1.1); color: var(--bg); }
.act.run.danger { background: var(--red); }
.act[disabled] { opacity: .45; pointer-events: none; }
.blocked { color: var(--faint); font-size: 11.5px; }
.ran { padding: 6px 16px 8px; font-size: 12px; border-top: 1px solid var(--line); }
.ran.ok { color: var(--green); } .ran.err { color: var(--yellow); }
.compact .cmdline { padding-bottom: 9px; } .compact .cmd { font-size: 13.5px; color: var(--muted); }
.compact .foot { display: none; }
.compact:hover { border-color: var(--line2); cursor: pointer; }
"""

_BLOCK_JS = _HELPERS + """
export default function (component) {
  const { data, setTriggerValue, parentElement } = component;
  let root = parentElement.querySelector('.block');
  if (!root) { root = el('article', 'block'); parentElement.appendChild(root); }
  root.className = 'block lvl-' + data.level + (data.focused ? ' focused' : ' compact') +
                   (data.focused && data.level === 'danger' ? ' danger-focus' : '');
  root.replaceChildren();

  const head = el('div', 'head');
  head.append(el('span', 'cwd', data.folder), el('span', 'sym', '❯'),
              el('span', 'req' + (data.source === 'ask' ? '' : ' pasted'), data.source === 'ask' ? data.request : 'pasted command'),
              el('span', 'time', data.time));
  const line = el('div', 'cmdline');
  const cmd = el('code', 'cmd'); colourCommand(cmd, data.command);
  line.append(el('span', 'dollar', '$'), cmd, el('span', 'badge', data.glyph + ' ' + data.level_label));
  root.append(head, line);

  if (data.focused) {
    const foot = el('div', 'foot');
    const sum = el('span', 'sum');
    if (data.counts) {
      for (const [n, label, cls] of [[data.counts.deleted, 'deleted', 'd'], [data.counts.modified, 'modified', 'm'], [data.counts.created, 'created', 'c']]) {
        sum.append(el('span', n ? cls : 'z', n + ' ' + label));
      }
    } else { sum.append(el('span', 'z', data.preview_label)); }
    foot.append(sum, el('span', 'meta', data.meta), el('span', 'spacer'));
    const button = (label, cls, action, title) => {
      const b = el('button', 'act ' + cls, label); b.type = 'button'; if (title) b.title = title;
      b.addEventListener('click', (e) => { e.stopPropagation(); setTriggerValue('action', { type: action, id: data.id, at: Date.now() }); });
      return b;
    };
    const copy = el('button', 'act', '⧉ copy'); copy.type = 'button';
    copy.addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(data.command); copy.textContent = '✓ copied'; }
      catch { copy.textContent = 'copy failed'; }
      setTimeout(() => { copy.textContent = '⧉ copy'; }, 1400);
    });
    foot.append(copy, button('✎ edit', '', 'edit', 'Edit and check again'));
    if (data.runnable) {
      foot.append(button(data.ran ? '↻ check again' : '▶ run', data.ran ? '' : 'run' + (data.level === 'danger' ? ' danger' : ''),
                         data.ran ? 'recheck' : 'run', data.ran ? '' : 'Run in ' + data.folder));
    } else {
      foot.append(el('span', 'blocked', data.blocked_reason));
    }
    root.append(foot);
    if (data.ran) root.append(el('div', 'ran ' + (data.ran.ok ? 'ok' : 'err'), data.ran.label));
  } else {
    root.title = 'Show this command';
    root.onclick = () => setTriggerValue('action', { type: 'focus', id: data.id, at: Date.now() });
  }
}
"""

_block = st.components.v2.component("ghost.block", css=_BLOCK_CSS, js=_BLOCK_JS)


def block(data: dict, key: str, on_action=None):
    return _block(data=data, key=key, on_action_change=on_action or (lambda: None))


# ---------------------------------------------------------------- command palette

_PALETTE_CSS = _BASE_CSS + """
.backdrop { position: fixed; inset: 0; background: rgba(5,7,10,.62); backdrop-filter: blur(3px); z-index: 1000000;
  display: none; align-items: flex-start; justify-content: center; padding-top: 14vh; }
.backdrop.open { display: flex; }
.box { width: min(560px, 92vw); background: #10151C; border: 1px solid var(--line2); border-radius: 12px;
  box-shadow: 0 30px 80px rgba(0,0,0,.6); overflow: hidden; }
.q { width: 100%; background: transparent; border: 0; border-bottom: 1px solid var(--line); color: var(--text);
  font: inherit; font-size: 15px; padding: 14px 16px; outline: none; caret-color: var(--cyan); }
.q::placeholder { color: var(--faint); }
ul { list-style: none; margin: 0; padding: 6px; max-height: 50vh; overflow-y: auto; }
li { display: flex; justify-content: space-between; gap: 12px; padding: 9px 12px; border-radius: 7px; font-size: 13.5px; cursor: pointer; }
li .g { color: var(--faint); font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }
li.sel { background: rgba(92,225,230,.1); color: #fff; }
li.sel .g { color: var(--cyan); }
.empty { padding: 12px 16px; color: var(--faint); font-size: 13px; }
.foot { display: flex; gap: 14px; padding: 8px 14px; border-top: 1px solid var(--line); font-size: 11px; color: var(--faint); }
"""

_PALETTE_JS = _HELPERS + """
export default function (component) {
  const { data, setTriggerValue, parentElement } = component;
  let root = parentElement.querySelector('.backdrop');
  if (!root) {
    root = el('div', 'backdrop');
    const box = el('div', 'box'); box.setAttribute('role', 'dialog'); box.setAttribute('aria-label', 'Commands');
    const q = el('input', 'q'); q.placeholder = 'Type a command…'; q.spellcheck = false;
    const list = el('ul'); list.setAttribute('role', 'listbox');
    const foot = el('div', 'foot');
    for (const t of ['↑↓ move', 'enter run', 'esc close']) foot.append(el('span', '', t));
    box.append(q, list, foot); root.append(box); parentElement.appendChild(root);
    let sel = 0, shown = [];
    const draw = () => {
      const term = q.value.trim().toLowerCase();
      shown = (root._items || []).filter((i) => !term || (i.label + ' ' + i.group).toLowerCase().includes(term));
      sel = Math.min(sel, Math.max(shown.length - 1, 0));
      list.replaceChildren();
      if (!shown.length) list.append(el('div', 'empty', 'No matching command'));
      shown.forEach((item, i) => {
        const li = el('li', i === sel ? 'sel' : ''); li.setAttribute('role', 'option');
        li.append(el('span', '', item.label), el('span', 'g', item.group));
        li.addEventListener('mousemove', () => { if (sel !== i) { sel = i; draw(); } });
        li.addEventListener('click', () => choose(item));
        list.append(li);
      });
    };
    const open = () => { root.classList.add('open'); q.value = ''; sel = 0; draw(); setTimeout(() => q.focus(), 0); };
    const close = () => { root.classList.remove('open'); };
    const choose = (item) => {
      close();
      if (item.client) { window.dispatchEvent(new CustomEvent(item.client, { detail: item.detail })); return; }
      setTriggerValue('action', { id: item.id, at: Date.now() });
    };
    q.addEventListener('input', () => { sel = 0; draw(); });
    q.addEventListener('keydown', (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, shown.length - 1); draw(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); draw(); }
      else if (e.key === 'Enter' && shown[sel]) { e.preventDefault(); choose(shown[sel]); }
      else if (e.key === 'Escape') { e.preventDefault(); close(); }
    });
    root.addEventListener('mousedown', (e) => { if (e.target === root) close(); });
    // One global listener, kept across reruns.
    if (window.__ghostKeys) window.removeEventListener('keydown', window.__ghostKeys);
    window.__ghostKeys = (e) => {
      const typing = /^(INPUT|TEXTAREA)$/.test((e.composedPath()[0] || {}).tagName || '');
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); root.classList.contains('open') ? close() : open(); }
      else if (e.key === '/' && !typing) { e.preventDefault(); window.dispatchEvent(new CustomEvent('ghost:focus-prompt')); }
      else if (e.key === 'Escape' && root.classList.contains('open')) close();
    };
    window.addEventListener('keydown', window.__ghostKeys);
    window.addEventListener('ghost:open-palette', open);
  }
  root._items = data.items || [];
}
"""

_palette = st.components.v2.component("ghost.palette", css=_PALETTE_CSS, js=_PALETTE_JS)


def palette(items: list[dict], on_action=None, key: str = "palette"):
    return _palette(data={"items": items}, key=key, on_action_change=on_action or (lambda: None))


# ---------------------------------------------------------------- history table

_TABLE_CSS = _BASE_CSS + """
.wrap { border: 1px solid var(--line); border-radius: 10px; overflow: hidden; background: var(--panel); }
table { width: 100%; border-collapse: collapse; font-size: 13px; table-layout: fixed; }
th { text-align: left; font-weight: 500; color: var(--faint); font-size: 11px; letter-spacing: .09em; text-transform: uppercase;
  padding: 10px 12px; border-bottom: 1px solid var(--line); background: #0E1218; }
td { padding: 9px 12px; border-bottom: 1px solid #1A202A; vertical-align: top; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
tr.row { cursor: pointer; }
tr.row:hover td, tr.row:focus td { background: rgba(92,225,230,.05); }
tr.row:focus { outline: none; } tr.row:focus td:first-child { box-shadow: inset 3px 0 0 var(--cyan); }
.n { color: var(--faint); width: 52px; } .t { color: var(--muted); width: 128px; }
.r { width: 130px; } .r span { color: var(--lvl); }
.q { font-family: 'IBM Plex Sans', system-ui, sans-serif; } .q.pasted { color: var(--muted); font-style: italic; }
.c { color: #C7D0DD; } .s { width: 92px; color: var(--muted); } .s.ok { color: var(--green); } .s.err { color: var(--yellow); }
.empty { padding: 26px; text-align: center; color: var(--faint); font-size: 13px; }
@media (max-width: 800px) { .t, .s, .n { display: none; } }
"""

_TABLE_JS = _HELPERS + """
export default function (component) {
  const { data, setTriggerValue, parentElement } = component;
  let root = parentElement.querySelector('.wrap');
  if (!root) { root = el('div', 'wrap'); parentElement.appendChild(root); }
  root.replaceChildren();
  if (!data.rows.length) { root.append(el('div', 'empty', data.empty)); return; }
  const table = el('table'); const head = el('tr');
  for (const [label, cls] of [['#', 'n'], ['when', 't'], ['risk', 'r'], ['request', 'q'], ['command', 'c'], ['run', 's']]) head.append(el('th', cls, label));
  const thead = el('thead'); thead.append(head); table.append(thead);
  const body = el('tbody');
  for (const row of data.rows) {
    const tr = el('tr', 'row lvl-' + row.level); tr.tabIndex = 0; tr.title = 'Open in the session';
    const risk = el('td', 'r'); risk.append(el('span', '', row.glyph + ' ' + row.level_label));
    tr.append(el('td', 'n', row.id), el('td', 't', row.when), risk,
              el('td', 'q' + (row.mode === 'ask' ? '' : ' pasted'), row.mode === 'ask' ? row.request : 'pasted command'),
              el('td', 'c', row.command), el('td', 's' + (row.ran ? (row.ok ? ' ok' : ' err') : ''), row.status));
    const open = () => setTriggerValue('open', { id: row.id, at: Date.now() });
    tr.addEventListener('click', open);
    tr.addEventListener('keydown', (e) => { if (e.key === 'Enter') open(); });
    body.append(tr);
  }
  table.append(body); root.append(table);
}
"""

_table = st.components.v2.component("ghost.history_table", css=_TABLE_CSS, js=_TABLE_JS)


def history_table(rows: list[dict], empty: str, on_open=None, key: str = "history-table"):
    return _table(data={"rows": rows, "empty": empty}, key=key, on_open_change=on_open or (lambda: None))

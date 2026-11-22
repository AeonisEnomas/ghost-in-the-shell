# Interactive components built with Streamlit's component API (v2).

import streamlit as st

_FONT = "'IBM Plex Mono', ui-monospace, monospace"

_BASE_CSS = f"""
:host {{ --bg: #0B0906; --bg2: #100C07; --line: #2E220C; --line2: #57400F; --amber: #FFB000; --bright: #FFD68A;
  --text: #E3A93C; --muted: #A87B26; --faint: #80601F; --ai: #C9A0FF; --cream: #F3E3B5;
  --green: #7FD98A; --blue: #6CB6FF; --yellow: #FFE14D; --red: #FF5C5C;
  font-family: {_FONT}; color: var(--text); }}
* {{ box-sizing: border-box; }}
button {{ font: inherit; color: inherit; background: none; border: 0; cursor: pointer; }}
button:focus-visible, input:focus-visible {{ outline: 2px solid var(--bright); outline-offset: 2px; }}
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


_PROMPT_CSS = _BASE_CSS + """
/* A pane with the mode and the key hints set into its top border. */
.prompt { border: 1px solid var(--line2); background: var(--bg); padding: 0 12px 7px; margin-top: 9px; }
.prompt:focus-within { border-color: var(--amber); }
.prompt.explain:focus-within { border-color: var(--ai); }
.top { display: flex; align-items: center; justify-content: space-between; gap: 12px; transform: translateY(-50%);
  margin: 0 -2px -3px; font-size: 11px; }
.mode { font-weight: 600; letter-spacing: .08em; text-transform: uppercase; padding: 0 8px; line-height: 1.65;
  color: var(--bg); flex: none; }
.mode.ask { background: var(--amber); } .mode.explain { background: var(--ai); }
.hints { display: flex; gap: 14px; color: var(--muted); background: var(--bg); padding: 0 8px; white-space: nowrap; overflow: hidden; }
.hints b { color: var(--text); font-weight: 500; }
.line { display: flex; align-items: center; gap: 10px; min-width: 0; }
.ps1 { flex: none; font-size: 13.5px; white-space: nowrap; max-width: 36%; overflow: hidden; text-overflow: ellipsis; }
.ps1 .u { color: var(--bright); } .ps1 .cwd { color: var(--amber); } .ps1 .colon { color: var(--faint); }
.sym { color: var(--amber); font-weight: 600; flex: none; }
.in { flex: 1; min-width: 0; background: transparent; border: 0; outline: none; color: var(--bright); font: inherit;
  font-size: 15px; caret-color: var(--amber); padding: 5px 0; }
.in::placeholder { color: var(--faint); }
.in:focus-visible { outline: none; }
.send { flex: none; color: var(--bg); background: var(--amber); padding: 2px 10px; font-size: 12.5px; font-weight: 600; }
.send:hover { background: var(--bright); }
.prompt.explain .send { background: var(--ai); }
.working .send { opacity: .5; pointer-events: none; }
.working .hints::before { content: "working"; color: var(--amber); animation: blink 1s steps(2) infinite; }
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
    const top = el('div', 'top');
    const line = el('div', 'line');
    const mode = el('button', 'mode'); mode.type = 'button'; mode.title = 'Switch mode (Tab)';
    const ps1 = el('span', 'ps1');
    const sym = el('span', 'sym', '❯');
    const input = el('input', 'in'); input.spellcheck = false; input.autocomplete = 'off';
    input.setAttribute('aria-label', 'Request');
    const send = el('button', 'send', '⏎ send'); send.type = 'button';
    line.append(ps1, sym, input, send);
    const hints = el('div', 'hints');
    for (const [k, t] of [['enter', 'send'], ['tab', 'mode'], ['↑↓', 'recall'], ['^k', 'commands']]) {
      const span = el('span'); span.append(el('b', '', k), document.createTextNode(' ' + t)); hints.append(span);
    }
    top.append(mode, hints);
    root.append(top, line);
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



_BLOCK_CSS = _BASE_CSS + """
/* A pane: the time, folder and risk tag sit in the top border. */
.block { border: 1px solid var(--line2); background: var(--bg); margin-top: 9px; }
.block.focused { border-color: var(--amber); }
.block.danger-focus { border-color: var(--red); }
.top { display: flex; align-items: center; gap: 4px; transform: translateY(-50%); margin: 0 8px -6px; font-size: 11.5px; }
.top .time, .top .cwd { background: var(--bg); padding: 0 6px; white-space: nowrap; }
.top .time { color: var(--muted); }
.top .cwd { color: var(--text); overflow: hidden; text-overflow: ellipsis; max-width: 50%; }
.top .fill { flex: 1; }
.badge { flex: none; font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--bg);
  background: var(--lvl); padding: 0 8px; line-height: 1.65; white-space: nowrap; }
.head { display: flex; align-items: baseline; gap: 10px; padding: 0 14px; font-size: 13.5px; min-width: 0; }
.head .sym { color: var(--amber); flex: none; font-weight: 600; }
.head .req { color: var(--text); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.head .req.pasted { color: var(--muted); font-style: italic; }
.cmdline { display: flex; align-items: flex-start; gap: 10px; padding: 5px 14px 9px; }
.dollar { color: var(--muted); user-select: none; padding-top: 1px; }
.cmd { flex: 1; min-width: 0; font-size: 15px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; color: var(--text); }
.cmd .prog { color: var(--bright); font-weight: 600; } .cmd .flag { color: var(--muted); } .cmd .str { color: var(--cream); }
.cmd .op { color: var(--amber); font-weight: 600; } .cmd .var { color: var(--ai); }
.foot { display: flex; align-items: center; gap: 12px; padding: 6px 10px 6px 14px; border-top: 1px dashed var(--line2);
  font-size: 12px; color: var(--muted); flex-wrap: wrap; }
.sum { display: flex; gap: 12px; }
.sum .d { color: var(--red); } .sum .m { color: var(--yellow); } .sum .c { color: var(--green); } .sum .z { color: var(--faint); }
.meta { color: var(--muted); }
.spacer { flex: 1; }
.act { padding: 1px 8px; color: var(--text); font-size: 12px; }
.act b { color: var(--muted); font-weight: 500; margin-right: 6px; }
.act:hover { background: var(--amber); color: var(--bg); }
.act:hover b { color: var(--bg); }
.act.run { color: var(--bg); background: var(--amber); font-weight: 600; }
.act.run b { color: var(--bg); }
.act.run:hover { background: var(--bright); }
.act.run.danger { background: var(--red); }
.act[disabled] { opacity: .45; pointer-events: none; }
.blocked { color: var(--muted); font-size: 11.5px; }
.ran { padding: 5px 14px 7px; font-size: 12px; border-top: 1px dashed var(--line2); }
.ran.ok { color: var(--green); } .ran.err { color: var(--yellow); }
.compact { border-color: var(--line); }
.compact .cmd { font-size: 13.5px; color: var(--muted); } .compact .cmd .prog { color: var(--text); }
.compact .head .req { color: var(--muted); }
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

  const top = el('div', 'top');
  top.append(el('span', 'time', data.time), el('span', 'cwd', data.folder), el('span', 'fill'),
             el('span', 'badge', data.glyph + ' ' + data.level_label));
  const head = el('div', 'head');
  head.append(el('span', 'sym', '❯'),
              el('span', 'req' + (data.source === 'ask' ? '' : ' pasted'), data.source === 'ask' ? data.request : 'pasted command'));
  const line = el('div', 'cmdline');
  const cmd = el('code', 'cmd'); colourCommand(cmd, data.command);
  line.append(el('span', 'dollar', '$'), cmd);
  root.append(top, head, line);

  if (data.focused) {
    const foot = el('div', 'foot');
    const sum = el('span', 'sum');
    if (data.counts) {
      for (const [n, label, cls] of [[data.counts.deleted, 'deleted', 'd'], [data.counts.modified, 'modified', 'm'], [data.counts.created, 'created', 'c']]) {
        sum.append(el('span', n ? cls : 'z', n + ' ' + label));
      }
    } else { sum.append(el('span', 'z', data.preview_label)); }
    foot.append(sum, el('span', 'meta', data.meta), el('span', 'spacer'));
    // Each action shows its key, as in a terminal program's key bar.
    const label = (b, key, text) => { b.replaceChildren(el('b', '', key), document.createTextNode(text)); };
    const send = (action) => setTriggerValue('action', { type: action, id: data.id, at: Date.now() });
    const button = (key, text, cls, action, title) => {
      const b = el('button', 'act ' + cls); b.type = 'button'; if (title) b.title = title; label(b, key, text);
      b.addEventListener('click', (e) => { e.stopPropagation(); send(action); });
      return b;
    };
    const copy = el('button', 'act'); copy.type = 'button'; label(copy, 'c', 'copy');
    const doCopy = async () => {
      try { await navigator.clipboard.writeText(data.command); copy.textContent = '✓ copied'; }
      catch { copy.textContent = 'copy failed'; }
      setTimeout(() => label(copy, 'c', 'copy'), 1400);
    };
    copy.addEventListener('click', doCopy);
    foot.append(copy, button('e', 'edit', '', 'edit', 'Edit and check again'));
    let runAction = null;
    if (data.runnable) {
      runAction = data.ran ? 'recheck' : 'run';
      foot.append(data.ran ? button('^⏎', 'check again', '', 'recheck', '')
                           : button('^⏎', 'run', 'run' + (data.level === 'danger' ? ' danger' : ''), 'run', 'Run in ' + data.folder));
    } else {
      foot.append(el('span', 'blocked', data.blocked_reason));
    }
    root.append(foot);
    if (data.ran) root.append(el('div', 'ran ' + (data.ran.ok ? 'ok' : 'err'), data.ran.label));

    // Keys for the focused block: c copies, e edits, Ctrl+Enter runs. Running
    // from the keyboard still goes through the same confirmation as a click.
    window.__ghostBlock = { root, copy: doCopy, edit: () => send('edit'), run: runAction ? () => send(runAction) : null };
    if (!window.__ghostBlockKeys) {
      window.__ghostBlockKeys = (e) => {
        const b = window.__ghostBlock;
        if (!b || !b.root.isConnected || !b.root.classList.contains('focused')) return;
        if (e.altKey || e.metaKey || document.querySelector('[role="dialog"]')) return;
        const target = e.composedPath()[0] || {};
        const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName || '') || target.isContentEditable;
        if (e.ctrlKey && e.key === 'Enter') {
          if (typing && target.value) return;          // text waiting in the prompt: Enter belongs to it
          if (b.run) { e.preventDefault(); b.run(); }
          return;
        }
        if (typing || e.ctrlKey) return;
        if (e.key === 'e') { e.preventDefault(); b.edit(); }
        else if (e.key === 'c') { e.preventDefault(); b.copy(); }
      };
      window.addEventListener('keydown', window.__ghostBlockKeys);
    }
  } else {
    root.title = 'Show this command';
    root.onclick = () => setTriggerValue('action', { type: 'focus', id: data.id, at: Date.now() });
  }
}
"""

_block = st.components.v2.component("ghost.block", css=_BLOCK_CSS, js=_BLOCK_JS)


def block(data: dict, key: str, on_action=None):
    return _block(data=data, key=key, on_action_change=on_action or (lambda: None))



_PALETTE_CSS = _BASE_CSS + """
.backdrop { position: fixed; inset: 0; background: rgba(5,4,2,.72); z-index: 1000000;
  display: none; align-items: flex-start; justify-content: center; padding-top: 14vh; }
.backdrop.open { display: flex; }
.box { width: min(560px, 92vw); background: var(--bg); border: 1px solid var(--amber);
  box-shadow: 0 0 0 1px var(--bg), 0 30px 80px rgba(0,0,0,.8); overflow: hidden; }
.q { width: 100%; background: transparent; border: 0; border-bottom: 1px solid var(--line2); color: var(--bright);
  font: inherit; font-size: 15px; padding: 12px 16px; outline: none; caret-color: var(--amber); }
.q::placeholder { color: var(--faint); }
ul { list-style: none; margin: 0; padding: 4px 0; max-height: 50vh; overflow-y: auto; }
li { display: flex; justify-content: space-between; gap: 12px; padding: 6px 16px; font-size: 13.5px; cursor: pointer; }
li .g { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }
/* The selected row is reverse video. */
li.sel { background: var(--amber); color: var(--bg); font-weight: 500; }
li.sel .g { color: var(--bg); }
.empty { padding: 12px 16px; color: var(--muted); font-size: 13px; }
.foot { display: flex; gap: 14px; padding: 6px 16px; border-top: 1px solid var(--line2); font-size: 11px; color: var(--muted); }
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



_TABLE_CSS = _BASE_CSS + """
.wrap { border: 1px solid var(--line2); overflow: hidden; background: var(--bg); }
table { width: 100%; border-collapse: collapse; font-size: 13px; table-layout: fixed; }
th { text-align: left; font-weight: 500; color: var(--muted); font-size: 11px; letter-spacing: .08em; text-transform: uppercase;
  padding: 7px 12px; border-bottom: 1px solid var(--line2); }
td { padding: 6px 12px; border-bottom: 1px dashed var(--line); vertical-align: top; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
tr.row { cursor: pointer; }
tr.row:hover td { background: var(--line); }
/* The row with keyboard focus is reverse video. */
tr.row:focus { outline: none; }
tr.row:focus td, tr.row:focus td span { background: var(--amber); color: var(--bg); }
.n { color: var(--muted); width: 52px; } .t { color: var(--muted); width: 128px; }
.r { width: 130px; } .r span { color: var(--lvl); }
.q { color: var(--text); } .q.pasted { color: var(--muted); font-style: italic; }
.c { color: var(--bright); } .s { width: 92px; color: var(--muted); } .s.ok { color: var(--green); } .s.err { color: var(--yellow); }
.empty { padding: 26px; text-align: center; color: var(--muted); font-size: 13px; }
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

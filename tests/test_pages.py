from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from recovery_worker.pages import _SCRIPT, closed_page, recovery_page


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is unavailable")
def test_inline_browser_script_parses() -> None:
  result = subprocess.run(
    ["node", "--check"],
    input=_SCRIPT,
    text=True,
    capture_output=True,
    check=False,
  )
  assert result.returncode == 0, result.stderr


def test_browser_heartbeat_redirects_a_lost_session() -> None:
  assert "error.status = response.status" in _SCRIPT
  assert "error.code = data.error?.code" in _SCRIPT
  assert "if (error?.status === 401)" in _SCRIPT
  assert "const data = await api('/api/turn')" in _SCRIPT
  assert "redirectLost(error)" in _SCRIPT


def test_browser_explains_agent_start_and_server_backed_expiry() -> None:
  assert "Recovery agent is starting" in _SCRIPT
  assert "first response can take about a minute" in _SCRIPT
  assert "api('/api/session/activity'" in _SCRIPT
  assert "Math.min(idleDeadline, absoluteDeadline)" in _SCRIPT
  assert "payload.code === 'provider_auth_required'" in _SCRIPT
  assert "data.started_at_ms" in _SCRIPT
  assert "if (!targetReady) refreshTarget();" in _SCRIPT


def test_browser_keeps_tool_calls_in_transcript_order() -> None:
  assert "assistantSegment = null;" in _SCRIPT
  assert "addTool(payload.name, payload.detail)" in _SCRIPT
  assert "if (message.role === 'tool')" in _SCRIPT
  assert "command.textContent = detail" in _SCRIPT
  assert "Working remotely" not in _SCRIPT


def test_recovery_page_has_one_end_action_and_an_explicit_idle_policy() -> None:
  now = datetime.now(timezone.utc)
  page = recovery_page(
    "nonce",
    idle_expires_at=now + timedelta(minutes=20),
    expires_at=now + timedelta(hours=1),
    idle_timeout_seconds=20 * 60,
  )
  assert "Ends automatically" in page
  assert "After 20 minutes without activity" in page
  assert page.count("End recovery") == 3
  assert "Cancel session" not in page
  assert "Secure remote access" in page
  assert "stops any active recovery agent" in page
  assert "const initialSession = null;" not in page
  assert 'id="messages" aria-live=' not in page
  assert "Session details" not in page
  assert "Bound target only" not in page


def test_closed_page_has_one_final_state() -> None:
  page = closed_page("nonce", return_url="https://mobius.example")
  assert "Recovery finished." in page
  assert "cancel" not in page.lower()
  assert "outcome" not in page.lower()


def test_end_recovery_remains_available_while_agent_is_working() -> None:
  assert "$('#finish').disabled = finishing" in _SCRIPT
  assert "$('#finish-mobile').disabled = finishing" in _SCRIPT
  assert "disabled || !targetReady || !providerReady" in _SCRIPT
  assert "Wait for the active recovery turn" not in _SCRIPT


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is unavailable")
def test_activity_lines_read_like_the_shell() -> None:
  start = _SCRIPT.index("const ACTIVITIES = new Map(")
  end = _SCRIPT.index("function renderActivity()")
  harness = _SCRIPT[start:end] + r"""
const cases = [
  [['Bash'], false, 'Ran a command'],
  [['Bash', 'Bash', 'Read'], false, 'Ran commands, read a file'],
  [['Skill'], false, 'Used a skill'],
  [['Read', 'Grep'], true, 'Searching the code · Reading a file'],
  [['mcp_custom'], false, 'mcp_custom'],
];
for (const [names, live, expected] of cases) {
  const actual = activitySummary(names, live);
  if (actual !== expected) throw new Error(`${names} ${live}: ${actual} !== ${expected}`);
}
"""
  result = subprocess.run(
    ["node", "-e", harness], text=True, capture_output=True, check=False,
  )
  assert result.returncode == 0, result.stderr


def test_transcript_is_built_from_text_nodes() -> None:
  assert "innerHTML" not in _SCRIPT
  assert "renderMarkdown(content, rawText.get(content)" in _SCRIPT
  now = datetime.now(timezone.utc)
  page = recovery_page(
    "nonce",
    idle_expires_at=now + timedelta(minutes=20),
    expires_at=now + timedelta(hours=1),
    idle_timeout_seconds=20 * 60,
  )
  for kind in ("terminal", "files", "search", "edit", "web", "plan", "sparkle"):
    assert f'<template id="icon-{kind}">' in page


# A minimal DOM: just enough for the renderer, serialised as compact markup so
# each case reads as the structure the browser would build. Text is escaped in
# the serialisation, so a raw "<" in a case proves it never became markup.
_DOM_SHIM = r"""
class Node {
  constructor(tag) {
    this.tag = tag; this.children = []; this.style = {}; this.className = '';
    this.isConnected = true; this.parentElement = null;
  }
  append(...items) {
    for (const item of items) {
      if (typeof item !== 'string') item.parentElement = this;
      this.children.push(item);
    }
  }
  replaceChildren() { this.children = []; }
  set textContent(value) { this.children = [String(value)]; }
  scrollIntoView() { globalThis.scrolls = (globalThis.scrolls || 0) + 1; }
}
globalThis.document = { createElement: tag => new Node(tag) };
const escape = text => text.replace(/&/g, '&amp;').replace(/</g, '&lt;');
function serialise(node) {
  if (typeof node === 'string') return escape(node);
  const attrs = [];
  if (node.className) attrs.push(`.${node.className}`);
  for (const key of ['href', 'target', 'rel', 'start']) {
    if (node[key] !== undefined) attrs.push(`${key}=${node[key]}`);
  }
  for (const [key, value] of Object.entries(node.style)) attrs.push(`${key}:${value}`);
  const open = attrs.length ? `${node.tag} ${attrs.join(' ')}` : node.tag;
  return `<${open}>${node.children.map(serialise).join('')}</${node.tag}>`;
}
function md(text) {
  const root = new Node('div');
  renderMarkdown(root, text);
  return root.children.map(serialise).join('');
}
function expect(actual, expected, name) {
  if (actual !== expected) throw new Error(`${name}\n  got:  ${actual}\n  want: ${expected}`);
}
"""


def _renderer() -> str:
  start = _SCRIPT.index("const LIST_ITEM = ")
  end = _SCRIPT.index("function addMessage(")
  return _DOM_SHIM + _SCRIPT[start:end]


def _run_node(harness: str) -> None:
  result = subprocess.run(
    ["node", "-e", harness], text=True, capture_output=True, check=False,
  )
  assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is unavailable")
def test_markdown_renders_the_documented_subset() -> None:
  _run_node(_renderer() + r"""
expect(md('| File | Status |\n|---|:--:|\n| a.py | ok |\n| b\\|c.py | **bad** |'),
  '<div .md-table-wrap><table .md-table><thead><tr><th>File</th><th textAlign:center>Status</th></tr></thead>'
  + '<tbody><tr><td>a.py</td><td textAlign:center>ok</td></tr>'
  + '<tr><td>b|c.py</td><td textAlign:center><strong>bad</strong></td></tr></tbody></table></div>',
  'pipe table');
expect(md('Summary:\n> quoted line\n> - item\nAfter'),
  '<p .md-paragraph>Summary:</p><blockquote .md-quote><p .md-paragraph>quoted line</p>'
  + '<ul .md-list><li>item</li></ul></blockquote><p .md-paragraph>After</p>',
  'quote does not merge into the paragraph');
expect(md('See [docs](https://example.com/a?b=1) now'),
  '<p .md-paragraph>See <a .md-link href=https://example.com/a?b=1 target=_blank '
  + 'rel=noopener noreferrer>docs</a> now</p>',
  'safe link');
for (const href of ['javascript:alert(1)', 'data:text/html,<b>x</b>', '/relative', 'mailto:a@b.c']) {
  expect(md(`[x](${href})`), `<p .md-paragraph>${escape(`[x](${href})`)}</p>`, `unsafe link ${href}`);
}
expect(md('An *italic* and _also_ word, not snake_case_name or 2 * 3 * 4'),
  '<p .md-paragraph>An <em>italic</em> and <em>also</em> word, not snake_case_name or 2 * 3 * 4</p>',
  'italics');
expect(md('**bold *nested* text** and `*code*`'),
  '<p .md-paragraph><strong>bold <em>nested</em> text</strong> and <code .md-inline-code>*code*</code></p>',
  'nesting and code wins');
expect(md('# Title\n\n1. one\n   more\n2. two\n  - sub\n\n---\n```\n<b>raw</b>\n```'),
  '<p .md-heading>Title</p><ol .md-list start=1><li>one\nmore</li><li>two</li>'
  + '<li marginLeft:1.25em>sub</li></ol><hr .md-rule></hr><pre .md-code-block>&lt;b>raw&lt;/b></pre>',
  'headings, lists, rules and fences');
expect(md('3. three\n4. four'), '<ol .md-list start=3><li>three</li><li>four</li></ol>', 'ordered start');
""")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is unavailable")
def test_unknown_markdown_keeps_its_raw_form_and_line_breaks() -> None:
  _run_node(_renderer() + r"""
expect(md('first line\nsecond line\n<details>\n[^1]: note'),
  '<p .md-paragraph>first line\nsecond line\n&lt;details>\n[^1]: note</p>',
  'unknown syntax keeps line breaks');
expect(md('a | b\nnot a delimiter\n| x |'),
  '<p .md-paragraph>a | b\nnot a delimiter\n| x |</p>',
  'pipes without a delimiter row stay raw');
expect(md('| a | b |\n|---|\n| 1 | 2 |'),
  '<p .md-paragraph>| a | b |\n|---|\n| 1 | 2 |</p>',
  'mismatched delimiter stays raw');
""")


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is unavailable")
def test_streamed_deltas_render_once_per_animation_frame() -> None:
  _run_node(_renderer() + r"""
const frames = [];
globalThis.requestAnimationFrame = callback => frames.push(callback);
const message = new Node('div');
const content = new Node('div');
message.append(content);
for (const delta of ['Hello ', '**wor', 'ld** and', ' **more']) appendAssistant(content, delta);
expect(String(frames.length), '1', 'one frame scheduled for many deltas');
expect(String(content.children.length), '0', 'nothing rendered before the frame');
frames.shift()();
expect(String(globalThis.scrolls), '1', 'one scroll per frame');
expect(serialise(content), '<div><p .md-paragraph>Hello <strong>world</strong> and **more</p></div>', 'rendered the whole text');
appendAssistant(content, '**');
expect(String(frames.length), '1', 'a later delta schedules a new frame');
frames.shift()();
expect(serialise(content).includes('<strong>more</strong>') ? 'ok' : serialise(content), 'ok', 'later delta rendered');
""")

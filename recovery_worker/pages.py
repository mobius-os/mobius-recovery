"""Recovery's dependency-free incident interface.

THESIS: privilege is visibly elsewhere; this worker is a calm window into one
fixed target, never a red emergency dashboard or a grid of admin cards.
OWN-WORLD: near-black planes, one violet action, crisp region borders, native UI
type, and monospace only for protocol facts.
STORY: authenticate, confirm isolation and target state, connect one provider,
repair conversationally, verify, then deliberately finish.
FIRST VIEWPORT: context rail at left, active recovery transcript at right, with
the composer anchored to the working edge.
FORM: focused two-pane operator workspace, derived directly from the required
incident sequence; no open staging choice or concept seed was needed.
"""

from __future__ import annotations

import html
import json
from datetime import datetime


def _brand_mark(class_name: str = "mark") -> str:
  """The inline Möbius loop used by the core product's zero-request surfaces."""
  return f'''<svg class="{html.escape(class_name)}" viewBox="0 0 24 24" fill="none" aria-hidden="true">
<path d="M4 12c0-3.2 3-5 6.2-3.4C13 10 11 14 13.8 15.4 17 17 20 15.2 20 12s-3-5-6.2-3.4C11 10 13 14 10.2 15.4 7 17 4 15.2 4 12Z" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/></svg>'''


_STYLE = """
:root {
  color-scheme: dark;
  --canvas: #08080a;
  --rail: #0e0e11;
  --raised: #141419;
  --raised-hover: #1b1b21;
  --text: #f4f2f7;
  --muted: #a8a4b0;
  --faint: #8f8a99;
  --border: rgba(255, 255, 255, .11);
  --hairline: rgba(255, 255, 255, .07);
  --accent: #9b82ff;
  --accent-hover: #b3a0ff;
  --accent-dim: rgba(155, 130, 255, .14);
  --success: #34d399;
  --warning: #f2c879;
  --danger: #fb7185;
  --focus: #b3a0ff;
  --shadow: inset 0 1px 0 rgba(255,255,255,.06), 0 18px 48px -24px rgba(0,0,0,.9);
}
* { box-sizing: border-box; }
html, body { min-height: 100%; margin: 0; background: var(--canvas); }
html { scrollbar-color: var(--border) transparent; }
body {
  min-height: 100vh;
  color: var(--text);
  font: 15px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  -webkit-font-smoothing: antialiased;
  -webkit-tap-highlight-color: transparent;
}
::selection { background: var(--accent); color: #100d18; }
button, input, textarea { font: inherit; }
button { cursor: pointer; }
a { color: var(--focus); text-underline-offset: 3px; }
:focus-visible { outline: 2px solid var(--focus); outline-offset: 3px; }
h1, h2, p { margin-top: 0; }
h1 { margin-bottom: 14px; font-size: clamp(2rem, 7vw, 3.3rem); line-height: 1.03; letter-spacing: -.025em; }
h2 { margin-bottom: 10px; font-size: 1rem; letter-spacing: -.015em; }
.start { display: grid; min-height: 100vh; place-items: center; padding: 24px; }
.start-main { width: min(100%, 460px); }
.mark { display: block; flex: none; width: 34px; height: 34px; color: var(--accent); }
.start-main > .mark { width: 46px; height: 46px; margin-bottom: 28px; }
.lede { max-width: 68ch; margin-bottom: 28px; color: var(--muted); line-height: 1.65; }
label { display: block; margin-bottom: 8px; font-size: .84rem; font-weight: 650; }
.input {
  width: 100%; padding: 13px 14px; border: 1px solid var(--border); border-radius: 12px;
  background: var(--raised); color: var(--text); caret-color: var(--accent);
}
.button {
  min-height: 44px; padding: 11px 15px; border: 0; border-radius: 12px;
  background: var(--accent); color: #100d18; font-weight: 720;
}
.button:hover { background: var(--accent-hover); }
.button:disabled { cursor: not-allowed; opacity: .5; }
.button.secondary { border: 1px solid var(--border); background: var(--raised); color: var(--text); }
.button.secondary:hover { background: var(--raised-hover); }
.button.compact { min-height: 34px; padding: 6px 10px; font-size: .78rem; }
.error { padding: 12px 14px; border: 1px solid rgba(251,113,133,.35); border-radius: 12px; background: rgba(251,113,133,.12); color: #ffd7de; line-height: 1.5; }
.stack { display: grid; gap: 12px; }
.shell { display: grid; min-height: 100vh; grid-template-columns: 296px minmax(0, 1fr); }
.rail {
  display: flex; min-width: 0; flex-direction: column; gap: 24px; padding: 22px;
  border-inline-end: 1px solid var(--border); background: var(--rail);
}
.brand { display: flex; align-items: center; gap: 10px; font-weight: 720; letter-spacing: -.015em; }
.status-line { display: flex; align-items: flex-start; gap: 10px; color: var(--muted); font-size: .86rem; line-height: 1.45; }
.status-line strong { color: var(--text); font-weight: 650; }
.dot { flex: none; width: 8px; height: 8px; margin-top: 6px; border-radius: 50%; background: var(--success); }
.dot.pending { background: var(--accent); animation: pulse 1.8s ease-out infinite; }
.dot.error-dot { background: var(--danger); animation: none; }
.session-life { padding-block: 18px; border-block: 1px solid var(--border); }
.session-life-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.session-life h2 { margin: 0; }
.countdown { font-variant-numeric: tabular-nums; font-size: 1.05rem; font-weight: 700; }
.session-life p { margin: 7px 0 13px; color: var(--muted); font-size: .8rem; line-height: 1.5; }
.session-life.warning .countdown { color: var(--warning); }
.providers { display: grid; gap: 5px; }
.provider { display: flex; min-width: 0; align-items: center; justify-content: space-between; gap: 10px; padding: 8px 0; }
.provider-name { display: flex; align-items: center; gap: 9px; margin: 0; }
.provider input { accent-color: var(--accent); }
.link-button { padding: 6px; border: 0; background: none; color: var(--focus); font-size: .8rem; }
.link-button:disabled { color: var(--faint); cursor: default; }
.session-details { color: var(--muted); font-size: .78rem; }
.session-details summary { cursor: pointer; color: var(--faint); }
.facts { display: grid; gap: 10px; padding-top: 12px; }
.fact span { display: block; }
.fact-label { margin-bottom: 2px; color: var(--faint); font-size: .7rem; }
.mono { overflow-wrap: anywhere; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .74rem; }
.rail-end { display: grid; gap: 9px; margin-top: auto; }
.rail-end p { margin: 0; color: var(--faint); font-size: .75rem; line-height: 1.45; }
.workspace { display: grid; min-width: 0; height: 100vh; grid-template-rows: auto minmax(0, 1fr) auto; }
.workspace-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 18px 28px; border-bottom: 1px solid var(--border); }
.workspace-head p { margin: 3px 0 0; color: var(--muted); font-size: .82rem; }
.remote-badge { padding: 5px 9px; border: 1px solid var(--border); border-radius: 999px; color: var(--muted); font-size: .72rem; }
.mobile-end { display: none; }
.messages { overflow: auto; padding: 34px max(24px, calc((100% - 760px) / 2)); }
.empty { max-width: 630px; margin: 11vh auto 0; }
.empty h1 { max-width: 13ch; font-size: clamp(2.4rem, 5vw, 4.5rem); text-wrap: balance; }
.empty p { max-width: 58ch; }
.empty-note { display: flex; max-width: 60ch; gap: 10px; margin-top: 24px; color: var(--faint); font-size: .8rem; }
.empty-note svg { flex: none; width: 16px; height: 16px; margin-top: 2px; }
.message { max-width: 720px; margin: 0 auto 26px; overflow-wrap: anywhere; line-height: 1.65; white-space: pre-wrap; }
.message.user { padding: 14px 16px; border-radius: 14px; background: var(--raised); box-shadow: inset 0 1px 0 rgba(255,255,255,.04); }
.message.error-message { color: #ffd7de; }
.message-label { display: block; margin-bottom: 6px; color: var(--faint); font-size: .7rem; font-weight: 700; letter-spacing: .03em; }
.tool, .agent-activity { max-width: 720px; margin: 0 auto 14px; color: var(--muted); font-size: .82rem; }
.tool { padding-inline-start: 22px; }
.agent-activity { display: flex; align-items: flex-start; gap: 10px; padding: 2px 0 10px 4px; }
.spinner { flex: none; width: 10px; height: 10px; margin-top: 5px; border: 1.5px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin .75s linear infinite; }
.agent-activity strong { position: relative; display: inline-block; color: var(--muted); font-weight: 500; }
.agent-activity strong::after { content: attr(data-label); position: absolute; inset: 0; overflow: hidden; color: var(--text); white-space: nowrap; -webkit-mask: linear-gradient(90deg, transparent, #000 35%, transparent 70%) 120% 0 / 300% 100% no-repeat; mask: linear-gradient(90deg, transparent, #000 35%, transparent 70%) 120% 0 / 300% 100% no-repeat; animation: sweep 2.4s steps(48,end) infinite; }
.agent-activity small { display: block; margin-top: 2px; color: var(--faint); font-variant-numeric: tabular-nums; }
.composer-wrap { padding: 16px max(18px, calc((100% - 810px) / 2)) max(22px, env(safe-area-inset-bottom)); background: linear-gradient(transparent, var(--canvas) 24%); }
.composer { padding: 11px; border: 1px solid var(--border); border-radius: 16px; background: var(--raised); box-shadow: var(--shadow); }
textarea { display: block; width: 100%; min-height: 72px; max-height: 220px; padding: 5px 6px 10px; resize: vertical; border: 0; background: transparent; color: var(--text); caret-color: var(--accent); line-height: 1.5; }
textarea::placeholder { color: var(--faint); opacity: 1; }
textarea:focus { outline: 0; }
.composer-foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.hint { color: var(--faint); font-size: .74rem; }
.inline-error { max-width: 720px; margin: 0 auto 14px; padding: 10px 12px; border-radius: 12px; background: rgba(251,113,133,.12); color: #ffd7de; font-size: .84rem; }
dialog { width: min(calc(100% - 32px), 500px); padding: 22px; border: 1px solid var(--border); border-radius: 16px; background: var(--rail); color: var(--text); box-shadow: 0 24px 64px -18px #000; }
dialog::backdrop { background: rgba(5,5,6,.84); }
.dialog-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; }
.code { padding: 16px; border-radius: 12px; background: var(--canvas); font: 700 1.5rem ui-monospace,SFMono-Regular,monospace; letter-spacing: .06em; text-align: center; user-select: all; }
.sr { position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0; overflow: hidden; clip: rect(0,0,0,0); border: 0; white-space: nowrap; }
@keyframes pulse { 50% { opacity: .45; } }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes sweep { 0% { -webkit-mask-position: 120% 0; mask-position: 120% 0; } 42%, 100% { -webkit-mask-position: -50% 0; mask-position: -50% 0; } }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 1ms !important; animation-iteration-count: 1 !important; scroll-behavior: auto !important; }
  .spinner { border-color: var(--accent); opacity: .65; }
  .agent-activity strong::after { display: none; }
}
@media (max-width: 760px) {
  .shell { display: block; }
  .rail { gap: 14px; padding: 16px 18px; border-inline-end: 0; border-bottom: 1px solid var(--border); }
  .session-life { padding-block: 14px; }
  .session-life p { margin: 5px 0 9px; font-size: .75rem; }
  .provider { padding: 5px 0; }
  .session-details { display: none; }
  .rail-end { display: none; }
  .workspace { min-height: 76vh; height: auto; grid-template-rows: auto auto auto; }
  .workspace-head { padding: 16px 18px; }
  .remote-badge { display: none; }
  .mobile-end { display: block; }
  .messages { min-height: 300px; overflow: visible; padding: 24px 18px; }
  .empty { margin: 4vh 0; }
  .empty h1 { max-width: none; font-size: clamp(1.75rem, 8.5vw, 2rem); white-space: nowrap; }
  .empty .lede, .empty-note { display: none; }
  .composer-wrap { position: sticky; bottom: 0; z-index: 3; padding: 12px; background: rgba(8,8,10,.96); }
  .hint { max-width: 19ch; }
}
"""


def _document(title: str, body: str, nonce: str, script: str = "") -> str:
  script_tag = f'<script nonce="{html.escape(nonce)}">{script}</script>' if script else ""
  return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="dark"><title>{html.escape(title)}</title>
<style nonce="{html.escape(nonce)}">{_STYLE}</style></head><body>{body}{script_tag}</body></html>"""


def launch_page(nonce: str, *, error: str = "", return_url: str | None) -> str:
  error_html = f'<p class="error" role="alert">{html.escape(error)}</p>' if error else ""
  action = (
    f'<a class="button" href="{html.escape(return_url, quote=True)}">'
    "Return to Möbius</a>"
    if return_url else ""
  )
  body = f"""<main class="start"><div class="start-main">{_brand_mark()}
<h1>Repair from outside.</h1><p class="lede">This temporary worker is separate from your Möbius instance.
Its code cannot be changed by the recovery agent, and its repair capability is fixed to one target.</p>
{error_html}<p class="lede">Open Recovery from mobius.you to create a fresh one-time handoff.</p>
{action}</div></main>"""
  return _document("Möbius Recovery", body, nonce)


def lost_page(nonce: str, *, return_url: str | None) -> str:
  """Explains a managed worker restart without inviting code replay."""
  action = ""
  if return_url:
    action = (
      f'<a class="button" href="{html.escape(return_url, quote=True)}">'
      "Return to Möbius</a>"
    )
  body = f"""<main class="start"><div class="start-main">{_brand_mark()}
<h1>Recovery needs a fresh launch.</h1><p class="lede">This on-demand worker restarted while the page was inactive, so its in-memory session was safely erased. Return to Möbius and open Recovery again to create a new one-time capability.</p>{action}</div></main>"""
  return _document("Fresh launch required · Möbius Recovery", body, nonce)


def closed_page(
  nonce: str,
  *,
  outcome: str,
  return_url: str | None,
) -> str:
  if outcome == "recovered":
    title = "Recovery finished."
    detail = (
      "The temporary capability is closed. Möbius kept running in place while "
      "you worked, and mobius.you is removing this recovery worker."
    )
  else:
    title = "Recovery session cancelled."
    detail = (
      "The temporary capability is closed. Return to mobius.you when you are "
      "ready to start another recovery."
    )
  action = ""
  if return_url:
    action = (
      f'<a class="button" href="{html.escape(return_url, quote=True)}">'
      "Return to Möbius</a>"
    )
  body = f"""<main class="start"><div class="start-main">{_brand_mark()}
<h1>{html.escape(title)}</h1><p class="lede">{html.escape(detail)}</p>{action}</div></main>"""
  return _document("Recovery closed · Möbius", body, nonce)


def recovery_page(
  nonce: str,
  *,
  protocol_version: str,
  build_sha: str,
  session_id: str,
  idle_expires_at: datetime,
  expires_at: datetime,
  idle_timeout_seconds: int,
  readiness_error: str | None = None,
  finishing: bool = False,
) -> str:
  facts = {"protocol": protocol_version, "build": build_sha, "session": session_id}
  dot_class = "dot pending" if readiness_error or finishing else "dot"
  target_text = (
    "Finishing recovery…"
    if finishing else readiness_error or "Connected to one repair target"
  )
  idle_minutes = max(1, idle_timeout_seconds // 60)
  body = f"""<main class="shell"><aside class="rail"><div class="brand">{_brand_mark()}
<span>Möbius Recovery</span></div><div class="status-line"><span id="target-dot" class="{dot_class}"></span><span><strong>Secure remote access</strong><br>
<span id="target-status">{html.escape(target_text)}</span><br><button class="link-button" id="target-retry" type="button" hidden>Retry target check</button></span></div>
<section class="session-life" id="session-life" aria-labelledby="session-life-title">
<div class="session-life-head"><h2 id="session-life-title">Ends automatically</h2><span class="countdown" id="session-countdown">--:--</span></div>
<p id="session-expiry-copy">After {idle_minutes} minutes without activity. Activity resets the timer; every session ends within one hour.</p>
<button class="button secondary compact" id="keep-open" type="button">Keep open</button></section>
<section><h2>AI provider</h2><div class="providers" id="providers">
<div class="provider"><label class="provider-name"><input type="radio" name="provider" value="claude" checked>Claude</label>
<button class="link-button" data-connect="claude" type="button">Connect Claude</button></div>
<div class="provider"><label class="provider-name"><input type="radio" name="provider" value="codex">Codex</label>
<button class="link-button" data-connect="codex" type="button">Connect Codex</button></div></div></section>
<details class="session-details"><summary>Session details</summary><div class="facts">"""
  for label, value in facts.items():
    body += f'<div class="fact"><span class="fact-label">{html.escape(label.title())}</span><span class="mono">{html.escape(value)}</span></div>'
  body += f"""</div></details>
<div class="rail-end"><p>You can close this tab. Recovery will end on its own, or you can remove the worker now.</p>
<button class="button secondary" id="finish" type="button">End recovery</button></div></aside>
<section class="workspace"><header class="workspace-head"><div><strong>Repair conversation</strong>
<p id="provider-state">Checking provider connection…</p></div><span class="remote-badge">Bound target only</span><button class="link-button mobile-end" id="finish-mobile" type="button">End recovery</button></header>
<div class="messages" id="messages" aria-live="polite"><div class="empty" id="empty"><h1>What needs fixing?</h1>
<p class="lede">Describe what failed, what changed just before it, and what still works. The agent can inspect and repair only this Möbius container.</p>
<div class="empty-note"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M12 3 4.5 6v5.5c0 4.5 3.1 7.6 7.5 9.5 4.4-1.9 7.5-5 7.5-9.5V6L12 3Z"/><path d="m9 12 2 2 4-4"/></svg><span>Möbius keeps running while you work. Commands use temporary root access through the fixed recovery relay.</span></div></div></div>
<div class="composer-wrap"><form class="composer" id="composer"><label class="sr" for="message">Message recovery agent</label>
<textarea id="message" maxlength="32000" placeholder="Describe the problem…" required></textarea><div class="composer-foot">
<span class="hint">Enter to send · Shift+Enter for a new line</span><button class="button" id="send" type="submit">Send</button>
</div></form></div></section></main>
<dialog id="provider-dialog"><h2 id="dialog-title">Connect provider</h2><div id="dialog-body"></div>
<div class="dialog-actions"><button class="button secondary" id="dialog-close" type="button">Close</button></div></dialog>
<dialog id="finish-dialog"><h2>End Recovery?</h2><p class="lede">This stops any active recovery agent, closes temporary access, and removes the recovery worker. Möbius keeps running in place. If you leave instead, the session ends automatically after {idle_minutes} minutes without activity.</p>
<div class="dialog-actions"><button class="button secondary" data-finish-close type="button">Keep working</button>
<button class="button" data-finish-confirm type="button">End recovery</button></div></dialog>"""
  initial_session = json.dumps({
    "finishing": finishing,
    "targetReady": not readiness_error,
    "idleExpiresAt": idle_expires_at.isoformat(),
    "expiresAt": expires_at.isoformat(),
    "idleTimeoutSeconds": idle_timeout_seconds,
  }, separators=(",", ":"))
  script = _SCRIPT.replace(
    "const initialSession = null;",
    f"const initialSession = {initial_session};",
  )
  return _document("Repair · Möbius Recovery", body, nonce, script)


_SCRIPT = r"""
history.replaceState(null, '', '/');
const $ = selector => document.querySelector(selector);
const initialSession = null;
const messages = $('#messages');
let empty = $('#empty');
let busy = false;
let remoteBusy = false;
let finishing = initialSession.finishing;
let targetReady = initialSession.targetReady;
let providerReady = false;
let finishTimer;
let heartbeatTimer;
let countdownTimer;
let targetRetryTimer;
let targetAttempts = 0;
let providerPoll;
let idleDeadline = Date.parse(initialSession.idleExpiresAt);
let absoluteDeadline = Date.parse(initialSession.expiresAt);
let lastActivityTouch = 0;
let activityElement;
let activityStartedAt = 0;
let activityTimer;

function setBusy(value) {
  busy = value;
  const disabled = value || finishing;
  $('#send').disabled = disabled || !targetReady || !providerReady;
  $('#message').disabled = disabled;
  $('#finish').disabled = finishing;
  $('#finish-mobile').disabled = finishing;
  $('#keep-open').disabled = finishing;
  $('#send').textContent = value ? 'Agent working…' : 'Send';
  document.querySelectorAll('input[name=provider]').forEach(element => { element.disabled = disabled; });
  document.querySelectorAll('[data-connect]').forEach(element => {
    element.disabled = disabled || element.dataset.connected === 'true';
  });
}

function enterFinishing(message = 'Ending Recovery…') {
  finishing = true;
  setBusy(true);
  $('#finish-dialog').close();
  $('#target-dot').className = 'dot pending';
  $('#target-status').textContent = message;
  clearInterval(heartbeatTimer);
  clearInterval(countdownTimer);
  clearInterval(providerPoll);
  clearTimeout(targetRetryTimer);
  stopAgentActivity();
}

function removeEmpty() {
  empty?.remove();
  empty = null;
}

function addMessage(role, text, isError = false) {
  removeEmpty();
  const element = document.createElement('div');
  element.className = `message ${role}${isError ? ' error-message' : ''}`;
  const label = document.createElement('span');
  label.className = 'message-label';
  label.textContent = role === 'user' ? 'YOU' : 'RECOVERY AGENT';
  const content = document.createElement('span');
  content.textContent = text;
  element.append(label, content);
  messages.append(element);
  element.scrollIntoView({ block: 'end' });
  return content;
}

function addTool(name) {
  const element = document.createElement('div');
  element.className = 'tool';
  element.textContent = `Working remotely · ${name}`;
  messages.append(element);
  element.scrollIntoView({ block: 'end' });
}

function showInlineError(message) {
  document.querySelector('.inline-error')?.remove();
  const element = document.createElement('div');
  element.className = 'inline-error';
  element.role = 'alert';
  element.textContent = message;
  messages.append(element);
  element.scrollIntoView({ block: 'end' });
}

function elapsedLabel(milliseconds) {
  const total = Math.max(0, Math.floor(milliseconds / 1000));
  const minutes = Math.floor(total / 60);
  return `${minutes}:${String(total % 60).padStart(2, '0')}`;
}

function updateAgentActivity(label) {
  if (!activityElement) return;
  const headline = activityElement.querySelector('strong');
  headline.textContent = label;
  headline.dataset.label = label;
}

function startAgentActivity(provider, label = 'Recovery agent is starting') {
  stopAgentActivity();
  removeEmpty();
  activityStartedAt = Date.now();
  activityElement = document.createElement('div');
  activityElement.className = 'agent-activity';
  activityElement.role = 'status';
  activityElement.setAttribute('aria-live', 'polite');
  const spinner = document.createElement('span');
  spinner.className = 'spinner';
  spinner.setAttribute('aria-hidden', 'true');
  const body = document.createElement('span');
  const headline = document.createElement('strong');
  headline.textContent = label;
  headline.dataset.label = label;
  const detail = document.createElement('small');
  const providerName = provider === 'codex' ? 'Codex' : 'Claude';
  detail.textContent = `${providerName} is connecting · 0:00 elapsed · first response can take about a minute`;
  body.append(headline, detail);
  activityElement.append(spinner, body);
  messages.append(activityElement);
  activityElement.scrollIntoView({ block: 'end' });
  activityTimer = setInterval(() => {
    const elapsed = Date.now() - activityStartedAt;
    detail.textContent = elapsed < 60000
      ? `${providerName} is connecting · ${elapsedLabel(elapsed)} elapsed · first response can take about a minute`
      : `Still working · ${elapsedLabel(elapsed)} elapsed`;
  }, 1000);
}

function stopAgentActivity() {
  clearInterval(activityTimer);
  activityElement?.remove();
  activityElement = null;
}

function redirectLost(error) {
  if (error?.status === 401) {
    location.replace('/');
    return true;
  }
  return false;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  const data = await response.json().catch(() => ({ error: { message: 'Unexpected server response.' } }));
  if (!response.ok) {
    const error = new Error(data.error?.message || 'Request failed.');
    error.status = response.status;
    error.code = data.error?.code;
    redirectLost(error);
    throw error;
  }
  return data;
}

function applyDeadlines(data) {
  const nextIdle = Date.parse(data.idle_expires_at || data.idleExpiresAt || '');
  const nextAbsolute = Date.parse(data.expires_at || data.expiresAt || '');
  if (Number.isFinite(nextIdle)) idleDeadline = nextIdle;
  if (Number.isFinite(nextAbsolute)) absoluteDeadline = nextAbsolute;
  updateCountdown();
}

function updateCountdown() {
  const deadline = Math.min(idleDeadline, absoluteDeadline);
  const remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
  const minutes = Math.floor(remaining / 60);
  $('#session-countdown').textContent = `${minutes}:${String(remaining % 60).padStart(2, '0')}`;
  $('#session-life').classList.toggle('warning', remaining <= 120);
  const absoluteWins = absoluteDeadline <= idleDeadline;
  $('#session-expiry-copy').textContent = absoluteWins
    ? 'This session will close automatically at its one-hour maximum.'
    : `After ${Math.round(initialSession.idleTimeoutSeconds / 60)} minutes without activity. Activity resets the timer; every session ends within one hour.`;
  if (remaining === 0 && !finishing) {
    setBusy(true);
    $('#session-countdown').textContent = 'Ending…';
    $('#keep-open').disabled = true;
    $('#target-dot').className = 'dot pending';
    $('#target-status').textContent = 'The inactive session is closing automatically';
  }
}

async function touchActivity(force = false) {
  if (finishing || document.visibilityState !== 'visible') return;
  const now = Date.now();
  if (!force && now - lastActivityTouch < 45000) return;
  lastActivityTouch = now;
  try {
    const data = await api('/api/session/activity', { method: 'POST', body: '{}' });
    applyDeadlines(data);
    if (force) {
      const button = $('#keep-open');
      button.textContent = 'Kept open';
      setTimeout(() => { if (!finishing) button.textContent = 'Keep open'; }, 1600);
    }
  } catch (error) {
    if (!redirectLost(error) && force) showInlineError(error.message);
  }
}

async function refreshProviders() {
  try {
    const status = await api('/api/providers');
    document.querySelectorAll('[data-connect]').forEach(button => {
      const provider = button.dataset.connect;
      const name = provider[0].toUpperCase() + provider.slice(1);
      const connected = Boolean(status[provider]);
      button.dataset.connected = String(connected);
      button.textContent = connected ? `${name} connected` : `Connect ${name}`;
      button.disabled = connected || busy || finishing;
    });
    const chosen = $('input[name=provider]:checked').value;
    providerReady = Boolean(status[chosen]);
    $('#provider-state').textContent = providerReady
      ? `${chosen[0].toUpperCase() + chosen.slice(1)} is connected`
      : `Connect ${chosen} before sending`;
    setBusy(busy);
  } catch (error) {
    providerReady = false;
    setBusy(busy);
    if (!redirectLost(error)) $('#provider-state').textContent = error.message;
  }
}

document.querySelectorAll('input[name=provider]').forEach(radio => {
  radio.addEventListener('change', refreshProviders);
});

async function refreshTarget() {
  clearTimeout(targetRetryTimer);
  try {
    const data = await api('/api/target/health');
    applyDeadlines(data);
    targetReady = true;
    setBusy(busy);
    targetAttempts = 0;
    $('#target-dot').className = 'dot';
    $('#target-status').textContent = 'Connected to one repair target';
    $('#target-retry')?.setAttribute('hidden', '');
  } catch (error) {
    if (redirectLost(error)) return;
    targetReady = false;
    setBusy(busy);
    targetAttempts += 1;
    $('#target-dot').className = 'dot pending';
    $('#target-status').textContent = error.message;
    if (document.visibilityState === 'visible' && targetAttempts < 4) {
      targetRetryTimer = setTimeout(refreshTarget, 2500);
    } else {
      $('#target-retry')?.removeAttribute('hidden');
    }
  }
}

document.querySelectorAll('[data-connect]').forEach(button => {
  button.addEventListener('click', async () => {
    const provider = button.dataset.connect;
    const dialog = $('#provider-dialog');
    await touchActivity(true);
    $('#dialog-title').textContent = `Connect ${provider === 'claude' ? 'Claude' : 'Codex'}`;
    $('#dialog-body').textContent = 'Starting secure login…';
    dialog.showModal();
    try {
      if (provider === 'claude') {
        const data = await api('/api/providers/claude/start', { method: 'POST', body: '{}' });
        const box = document.createElement('div');
        box.className = 'stack';
        const link = document.createElement('a');
        link.href = data.auth_url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = 'Open Claude authorization';
        const input = document.createElement('input');
        input.className = 'input';
        input.placeholder = 'Paste the authorization code';
        input.autocomplete = 'off';
        const submit = document.createElement('button');
        submit.className = 'button';
        submit.textContent = 'Complete connection';
        submit.onclick = async () => {
          submit.disabled = true;
          try {
            await api('/api/providers/claude/exchange', { method: 'POST', body: JSON.stringify({ code: input.value }) });
            dialog.close();
            refreshProviders();
          } catch (error) {
            submit.disabled = false;
            $('#dialog-body').append(Object.assign(document.createElement('p'), { className: 'error', textContent: error.message }));
          }
        };
        box.append(link, input, submit);
        $('#dialog-body').replaceChildren(box);
      } else {
        const data = await api('/api/providers/codex/start', { method: 'POST', body: '{}' });
        const box = document.createElement('div');
        box.className = 'stack';
        const link = document.createElement('a');
        link.href = data.url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = 'Open Codex authorization';
        const code = document.createElement('div');
        code.className = 'code';
        code.textContent = data.code;
        const state = document.createElement('p');
        state.className = 'lede';
        state.textContent = 'Waiting for authorization…';
        box.append(link, code, state);
        $('#dialog-body').replaceChildren(box);
        providerPoll = setInterval(async () => {
          if (document.visibilityState !== 'visible') return;
          try {
            const status = await api('/api/providers/codex/status');
            if (status.state === 'complete') {
              clearInterval(providerPoll);
              dialog.close();
              refreshProviders();
            } else if (status.state === 'failed') {
              clearInterval(providerPoll);
              state.textContent = 'Login failed. Close this window and try again.';
            }
          } catch (error) {
            clearInterval(providerPoll);
            if (!redirectLost(error)) state.textContent = error.message;
          }
        }, 1200);
      }
    } catch (error) {
      if (!redirectLost(error)) $('#dialog-body').textContent = error.message;
    }
  });
});

$('#dialog-close').onclick = () => {
  clearInterval(providerPoll);
  $('#provider-dialog').close();
};

$('#message').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    $('#composer').requestSubmit();
  }
});

$('#composer').addEventListener('submit', async event => {
  event.preventDefault();
  if (busy) return;
  const input = $('#message');
  const text = input.value.trim();
  if (!text) return;
  const provider = $('input[name=provider]:checked').value;
  setBusy(true);
  addMessage('user', text);
  input.value = '';
  startAgentActivity(provider);
  let assistant;
  let reportedError = false;
  try {
    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, provider }),
    });
    if (!response.ok) {
      const data = await response.json();
      const error = new Error(data.error?.message || 'Could not start recovery agent.');
      error.status = response.status;
      error.code = data.error?.code;
      redirectLost(error);
      throw error;
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let split;
      while ((split = buffer.indexOf('\n\n')) >= 0) {
        const block = buffer.slice(0, split);
        buffer = buffer.slice(split + 2);
        const line = block.split('\n').find(item => item.startsWith('data: '));
        if (!line) continue;
        const payload = JSON.parse(line.slice(6));
        if (payload.type === 'text') {
          stopAgentActivity();
          if (!assistant) assistant = addMessage('assistant', '');
          assistant.textContent += payload.content;
          assistant.parentElement.scrollIntoView({ block: 'end' });
        } else if (payload.type === 'tool') {
          updateAgentActivity(`Working remotely · ${payload.name}`);
          addTool(payload.name);
        } else if (payload.type === 'error') {
          stopAgentActivity();
          addMessage('assistant', payload.message, true);
          reportedError = true;
        }
      }
    }
    if (!assistant && !reportedError) {
      stopAgentActivity();
      addMessage('assistant', 'The recovery agent finished without returning a message.', true);
    }
  } catch (error) {
    stopAgentActivity();
    if (!redirectLost(error) && !reportedError) addMessage('assistant', error.message, true);
  } finally {
    stopAgentActivity();
    setBusy(false);
    input.focus();
    heartbeat();
  }
});

$('#finish').onclick = () => $('#finish-dialog').showModal();
$('#finish-mobile').onclick = () => $('#finish-dialog').showModal();
$('[data-finish-close]').onclick = () => $('#finish-dialog').close();

function handleFinish(data) {
  if (data.status === 'finished') {
    location.replace('/');
    return;
  }
  if (data.status === 'resumed') {
    location.reload();
    return;
  }
  if (data.status === 'failed') {
    enterFinishing(data.error?.message || 'Recovery could not be ended.');
    return;
  }
  clearTimeout(finishTimer);
  finishTimer = setTimeout(pollFinish, 1200);
}

async function pollFinish() {
  if (!finishing) return;
  try {
    handleFinish(await api('/api/finish/status'));
  } catch (error) {
    if (redirectLost(error)) return;
    $('#target-status').textContent = `Still confirming closure · ${error.message}`;
    finishTimer = setTimeout(pollFinish, 1800);
  }
}

async function finish() {
  enterFinishing();
  try {
    handleFinish(await api('/api/finish', { method: 'POST', body: JSON.stringify({ outcome: 'recovered' }) }));
  } catch (error) {
    if (redirectLost(error)) return;
    if (error.status && error.status < 500) {
      finishing = false;
      setBusy(false);
      showInlineError(error.message);
    } else {
      $('#target-status').textContent = 'Confirming that temporary access is closed…';
      finishTimer = setTimeout(pollFinish, 1200);
    }
  }
}

$('[data-finish-confirm]').onclick = finish;
$('#keep-open').onclick = () => touchActivity(true);
$('#target-retry')?.addEventListener('click', () => { targetAttempts = 0; refreshTarget(); });

async function loadHistory(replace = false) {
  try {
    const data = await api('/api/history');
    if (!Array.isArray(data.messages) || data.messages.length === 0) return;
    if (replace) {
      messages.replaceChildren();
      empty = null;
    }
    if (!replace && !empty) return;
    data.messages.forEach(message => addMessage(message.role, message.content));
  } catch (error) {
    redirectLost(error);
  }
}

async function heartbeat() {
  if (document.visibilityState !== 'visible' || finishing) return;
  try {
    const data = await api('/api/turn');
    applyDeadlines(data);
    if (data.active && !busy) {
      remoteBusy = true;
      setBusy(true);
      startAgentActivity($('input[name=provider]:checked').value, 'Recovery agent is still working');
      const detail = activityElement?.querySelector('small');
      if (detail) detail.textContent = 'This page will restore the result when the active turn finishes.';
    } else if (!data.active && remoteBusy) {
      remoteBusy = false;
      stopAgentActivity();
      setBusy(false);
      await loadHistory(true);
    }
  } catch (error) {
    redirectLost(error);
  }
}

function heartbeatVisibility() {
  clearInterval(heartbeatTimer);
  clearTimeout(targetRetryTimer);
  if (document.visibilityState === 'visible') {
    heartbeat();
    refreshTarget();
    heartbeatTimer = setInterval(heartbeat, 15000);
  }
}

document.addEventListener('pointerdown', event => {
  if (!event.target.closest('#keep-open,#finish,#finish-mobile,[data-finish-confirm],[data-finish-close]')) touchActivity();
}, { passive: true });
document.addEventListener('keydown', () => touchActivity());
document.addEventListener('visibilitychange', heartbeatVisibility);
window.addEventListener('pagehide', () => {
  clearInterval(heartbeatTimer);
  clearInterval(countdownTimer);
  clearInterval(providerPoll);
  clearInterval(activityTimer);
  clearTimeout(targetRetryTimer);
});

applyDeadlines(initialSession);
setBusy(false);
countdownTimer = setInterval(updateCountdown, 1000);
if (finishing) {
  enterFinishing();
  pollFinish();
} else {
  loadHistory();
  refreshProviders();
  heartbeatVisibility();
}
"""

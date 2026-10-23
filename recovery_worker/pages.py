"""Recovery's dependency-free incident interface.

THESIS: Recovery is Möbius working from outside itself, so it wears the same
skin as the shell: the same near-black theme tokens, Inter, the Möbius mark,
quiet sidebar rows, plain assistant prose, accent user bubbles, compact activity
rows, and the rounded composer pill.
SCOPE: privilege is still visibly elsewhere; the sidebar names the one fixed
target, the session clock, and the provider, and nothing else.
STORY: authenticate, confirm isolation and target state, connect one provider,
repair conversationally, verify, then deliberately finish.
ZERO REQUESTS ELSEWHERE: fonts and the mark are baked into the image and served
from this worker's own origin; nothing is fetched from another host.
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path


_ASSET_DIR = Path(__file__).with_name("assets")
_ASSET_TYPES = {
  "inter-400.woff2": "font/woff2",
  "inter-500.woff2": "font/woff2",
  "inter-600.woff2": "font/woff2",
  "jetbrains-mono-400.woff2": "font/woff2",
  "mobius-mark.png": "image/png",
}
# Read once at import: the set is fixed and served by name, never by path.
ASSETS: dict[str, tuple[bytes, str]] = {
  name: ((_ASSET_DIR / name).read_bytes(), media_type)
  for name, media_type in _ASSET_TYPES.items()
}


def _brand_mark(class_name: str = "mark") -> str:
  """The Möbius mark the shell shows beside its wordmark."""
  return (
    f'<img class="{html.escape(class_name)}" src="/assets/mobius-mark.png" '
    'alt="" width="28" height="28">'
  )


_LATIN = (
  "U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, "
  "U+0300-036F, U+0370-0377, U+037A-037F, U+0384-038A, U+038C, U+038E-03A1, U+03A3-03FF"
)


def _face(family: str, weight: int, file: str) -> str:
  return (
    f"@font-face {{ font-family: '{family}'; font-style: normal; font-weight: {weight}; "
    f"font-display: swap; src: url('/assets/{file}') format('woff2'); unicode-range: {_LATIN}; }}\n"
  )


# Same faces and metric-matched fallbacks as the shell's mobius-fonts.css.
_FONTS = (
  "@font-face { font-family: 'Inter Fallback'; src: local('Arial'); size-adjust: 107.6%; "
  "ascent-override: 90.1%; descent-override: 22.4%; line-gap-override: 0%; }\n"
  "@font-face { font-family: 'JetBrains Mono Fallback'; src: local('Menlo'), local('Consolas'), "
  "local('DejaVu Sans Mono'); size-adjust: 99.7%; ascent-override: 102.3%; "
  "descent-override: 30.1%; line-gap-override: 0%; }\n"
  + _face("Inter", 400, "inter-400.woff2")
  + _face("Inter", 500, "inter-500.woff2")
  + _face("Inter", 600, "inter-600.woff2")
  + _face("JetBrains Mono", 400, "jetbrains-mono-400.woff2")
)


_STYLE = _FONTS + """
:root {
  color-scheme: dark;
  --font: 'Inter', 'Inter Fallback', system-ui, -apple-system, sans-serif;
  --mono: 'JetBrains Mono', 'JetBrains Mono Fallback', ui-monospace, 'SF Mono', monospace;
  /* The shell's default dark theme tokens. */
  --bg: #0d0d0d;
  --surface: #171717;
  --surface-2: #212121;
  --border: #2a2a2a;
  --border-light: #1f1f1f;
  --text: #ececec;
  --muted: #a8a8a8;
  --accent: #8b6cf7;
  --accent-hover: #7c5ce6;
  --accent-dim: rgba(139, 108, 247, .14);
  --accent-fg: #ffffff;
  --danger: #f87171;
  --green: #10b981;
  --warning: #fbbf24;
}
* { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
html, body { min-height: 100%; margin: 0; background: var(--bg); }
html { scrollbar-color: var(--border) transparent; }
body {
  min-height: 100vh;
  color: var(--text);
  font: 15px/1.6 var(--font);
  -webkit-font-smoothing: antialiased;
}
::selection { background: rgba(139, 108, 247, .35); }
button, input, textarea { font: inherit; color: inherit; }
button { cursor: pointer; }
a { color: var(--accent); text-underline-offset: 3px; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
h1, h2, p { margin-top: 0; }
h1 { margin-bottom: 10px; font-size: 28px; font-weight: 600; line-height: 1.25; letter-spacing: -.01em; }
h2 { margin-bottom: 8px; font-size: 15px; font-weight: 600; }
.start { display: grid; min-height: 100vh; place-items: center; padding: 24px; }
.start-main { width: min(100%, 440px); }
.mark { display: block; flex: none; width: 28px; height: 28px; border-radius: 6px; }
.start-main > .mark { width: 48px; height: 48px; margin-bottom: 24px; border-radius: 11px; }
.lede { max-width: 64ch; margin-bottom: 24px; color: var(--muted); line-height: 1.6; }
label { display: block; margin-bottom: 8px; font-size: 13px; font-weight: 500; }
.input {
  width: 100%; padding: 11px 14px; border: 1px solid var(--border); border-radius: 12px;
  background: var(--surface); color: var(--text); caret-color: var(--accent);
}
.input:focus { border-color: var(--accent); outline: 0; }
.button {
  display: inline-flex; min-height: 40px; align-items: center; justify-content: center; gap: 8px;
  padding: 8px 16px; border: 1px solid transparent; border-radius: 10px;
  background: var(--accent); color: var(--accent-fg); font-weight: 500; text-decoration: none;
  transition: background-color .12s;
}
.button:not(:disabled):hover { background: var(--accent-hover); }
.button:disabled { cursor: not-allowed; opacity: .5; }
.button.secondary { border-color: var(--border); background: var(--surface); color: var(--text); }
.button.secondary:not(:disabled):hover { background: var(--surface-2); }
.button.compact { min-height: 32px; padding: 5px 12px; font-size: 13px; }
.error { padding: 10px 14px; border: 1px solid rgba(248,113,113,.3); border-radius: 12px; background: rgba(248,113,113,.1); color: #fecaca; line-height: 1.5; }
.stack { display: grid; gap: 12px; }
.shell { display: grid; min-height: 100vh; grid-template-columns: 320px minmax(0, 1fr); }
.rail {
  display: flex; min-width: 0; flex-direction: column; gap: 20px; padding: 14px 12px 16px;
  border-inline-end: 1px solid var(--border-light); background: var(--bg);
}
.brand { display: flex; align-items: center; gap: 10px; min-height: 40px; padding: 0 8px; }
.mobile-end { display: none; margin-left: auto; }
.wordmark { font-size: 20px; font-weight: 600; }
.brand-tag { padding: 2px 8px; border-radius: 999px; background: var(--accent-dim); color: var(--accent); font-size: 12px; font-weight: 500; }
.status-line { display: flex; align-items: flex-start; gap: 10px; padding: 0 12px; color: var(--muted); font-size: 13px; line-height: 1.5; }
.status-line strong { color: var(--text); font-size: 15px; font-weight: 500; }
.dot { flex: none; width: 8px; height: 8px; margin-top: 8px; border-radius: 50%; background: var(--green); }
.dot.pending { background: var(--accent); animation: pulse 1.8s ease-out infinite; }
.dot.error-dot { background: var(--danger); animation: none; }
.session-life { margin: 0 4px; padding: 12px 14px; border: 1px solid var(--border-light); border-radius: 12px; background: rgba(23,23,23,.6); }
.session-life-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.session-life h2 { margin: 0; }
.countdown { font-variant-numeric: tabular-nums; font-size: 15px; font-weight: 600; }
.session-life p { margin: 4px 0 12px; color: var(--muted); font-size: 13px; line-height: 1.5; }
.session-life.warning { border-color: rgba(251,191,36,.35); }
.session-life.warning .countdown { color: var(--warning); }
.section-title { margin: 0 0 4px; padding: 0 12px; }
.providers { display: grid; gap: 2px; }
.provider {
  display: flex; min-width: 0; min-height: 40px; align-items: center; justify-content: space-between; gap: 8px;
  padding: 0 4px 0 12px; border-radius: 10px; transition: background-color .12s;
}
.provider:has(input:checked) { background: var(--accent-dim); }
.provider:has(input:checked) .provider-name { color: var(--accent); }
.provider-name { display: flex; min-height: 40px; flex: 1; align-items: center; gap: 10px; margin: 0; font-size: 15px; font-weight: 400; cursor: pointer; }
.provider input { margin: 0; accent-color: var(--accent); }
.link-button { min-height: 32px; padding: 4px 8px; border: 0; border-radius: 8px; background: none; color: var(--accent); font-size: 13px; }
.link-button:not(:disabled):hover { background: var(--surface); }
.link-button:disabled { color: var(--muted); cursor: default; }
.provider-state { margin: 6px 0 0; padding: 0 12px; color: var(--muted); font-size: 12px; }
.rail-end { display: grid; gap: 10px; margin-top: auto; padding: 14px 4px 0; border-top: 1px solid var(--border-light); }
.rail-end p { margin: 0; padding: 0 8px; color: var(--muted); font-size: 13px; line-height: 1.5; }
.workspace { display: grid; min-width: 0; height: 100vh; grid-template-columns: minmax(0, 1fr); grid-template-rows: minmax(0, 1fr) auto; }
.messages { overflow: auto; padding: 28px max(20px, calc((100% - 720px) / 2)); }
.empty { max-width: 560px; margin: 24vh auto 0; text-align: center; }
.empty .lede { margin-inline: auto; }
.message { margin: 0 0 16px; overflow-wrap: anywhere; line-height: 1.7; white-space: pre-wrap; }
.message.user {
  width: fit-content; max-width: min(85%, 640px); margin-left: auto; padding: 11px 16px;
  border-radius: 18px 18px 5px 18px; color: #fff;
  background: linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 78%, #000));
  box-shadow: 0 2px 14px -4px var(--accent-dim);
}
.message.error-message { padding: 0 8px; color: #fecaca; }
.md { white-space: normal; }
.md > * { margin: 0 0 .75rem; padding: 0 8px; }
.md > :last-child { margin-bottom: 0; }
.md-heading { font-weight: 600; }
.md-list { padding-left: 30px; }
.md-list li + li { margin-top: 4px; }
.md-inline-code { padding: 1px 5px; border-radius: 5px; background: var(--surface-2); font: .87em var(--mono); }
.md-code-block { margin-inline: 8px; padding: 10px 12px; overflow: auto; border: 1px solid var(--border-light); border-radius: 10px; background: var(--surface); font: 13px/1.55 var(--mono); white-space: pre; }
/* The shell's activity line: muted 13px prose, a 14px type glyph, a shimmer
   while live, and a quiet timeline of raw steps when expanded. */
.activity, .agent-activity { margin: 0 0 8px; padding-left: 6px; }
.activity-header, .agent-activity { display: flex; min-height: 32px; align-items: center; gap: 6px; color: var(--muted); font-size: 13px; }
.activity-header { width: 100%; padding: 2px 2px 2px 0; border: 0; background: none; text-align: left; }
.activity-header:hover .activity-label { color: var(--text); }
.activity-header:focus-visible { outline-offset: -2px; border-radius: 6px; }
.activity-icon { display: inline-flex; flex: none; width: 14px; height: 14px; align-items: center; justify-content: center; }
.activity-icon svg { width: 14px; height: 14px; }
.activity-label { position: relative; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.activity-sweep { display: none; }
.activity.running .activity-sweep { display: block; position: absolute; inset: 0; overflow: hidden; color: color-mix(in srgb, var(--text) 94%, var(--bg)); white-space: nowrap; -webkit-mask: linear-gradient(90deg, transparent 0%, #000 18%, #000 32%, transparent 50%) 120% 0 / 300% 100% no-repeat; mask: linear-gradient(90deg, transparent 0%, #000 18%, #000 32%, transparent 50%) 120% 0 / 300% 100% no-repeat; animation: sweep 2.4s steps(48,end) infinite; }
.activity-timeline { display: flex; flex-direction: column; gap: 4px; margin: 4px 0 4px 20px; padding-left: 11px; border-left: 1px solid color-mix(in srgb, var(--border) 70%, transparent); }
.activity-timeline[hidden] { display: none; }
.activity-step { padding: 4px 0; }
.activity-step-name { color: var(--muted); font: 12px var(--mono); }
.tool-detail { margin: 4px 0 0; padding: 8px 10px 10px; overflow: auto; max-height: 320px; border: 1px solid var(--border-light); border-radius: 10px; background: var(--surface); color: var(--text); font: 12px/1.55 var(--mono); white-space: pre-wrap; overflow-wrap: anywhere; }
.agent-activity strong { position: relative; display: inline-block; color: var(--muted); font-weight: 400; }
.agent-activity strong::after { content: attr(data-label); position: absolute; inset: 0; overflow: hidden; color: color-mix(in srgb, var(--text) 94%, var(--bg)); white-space: nowrap; -webkit-mask: linear-gradient(90deg, transparent 0%, #000 18%, #000 32%, transparent 50%) 120% 0 / 300% 100% no-repeat; mask: linear-gradient(90deg, transparent 0%, #000 18%, #000 32%, transparent 50%) 120% 0 / 300% 100% no-repeat; animation: sweep 2.4s steps(48,end) infinite; }
.agent-activity small { margin-left: 6px; color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; opacity: .8; }
.spinner { flex: none; width: 12px; height: 12px; margin-top: 4px; border: 1.5px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin .75s linear infinite; }
.composer-wrap { padding: 12px max(16px, calc((100% - 760px) / 2)) max(20px, env(safe-area-inset-bottom)); background: linear-gradient(transparent, var(--bg) 30%); }
.composer {
  display: flex; align-items: flex-end; gap: 6px; padding: 4px;
  border: 1px solid var(--border-light); border-radius: 24px; background: rgba(23,23,23,.6);
  transition: border-color .12s;
}
.composer:focus-within { border-color: var(--border); }
textarea { display: block; flex: 1; min-width: 0; height: 40px; min-height: 40px; max-height: 200px; padding: 8px 8px 8px 14px; resize: none; border: 0; background: transparent; color: var(--text); caret-color: var(--accent); font-size: 16px; line-height: 1.45; }
textarea::placeholder { color: var(--muted); opacity: 1; }
textarea:focus { outline: 0; }
.send { display: grid; flex: none; width: 40px; height: 40px; place-items: center; padding: 0; border: 0; border-radius: 50%; background: var(--accent); color: var(--accent-fg); transition: background-color .12s, opacity .12s; }
.send:not(:disabled):hover { background: var(--accent-hover); }
.send:disabled { background: var(--border); cursor: not-allowed; }
.send svg { width: 18px; height: 18px; }
.send .spinner { display: none; margin: 0; border-color: rgba(255,255,255,.35); border-top-color: #fff; }
.send.working { background: var(--accent); }
.send.working svg { display: none; }
.send.working .spinner { display: block; }
.inline-error { margin: 0 0 12px; padding: 10px 12px; border-radius: 12px; background: rgba(248,113,113,.1); color: #fecaca; font-size: 13px; }
dialog { width: min(calc(100% - 32px), 460px); padding: 20px; border: 1px solid var(--border); border-radius: 16px; background: var(--surface); color: var(--text); box-shadow: 0 24px 64px -18px #000; }
dialog::backdrop { background: rgba(0,0,0,.6); }
dialog .lede { margin-bottom: 0; }
.dialog-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 20px; }
.code { padding: 14px; border-radius: 12px; background: var(--bg); font: 500 1.4rem var(--mono); letter-spacing: .06em; text-align: center; user-select: all; }
.sr { position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0; overflow: hidden; clip: rect(0,0,0,0); border: 0; white-space: nowrap; }
@keyframes pulse { 50% { opacity: .45; } }
@keyframes spin { to { transform: rotate(360deg); } }
@keyframes sweep { 0% { -webkit-mask-position: 120% 0; mask-position: 120% 0; } 42%, 100% { -webkit-mask-position: -50% 0; mask-position: -50% 0; } }
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 1ms !important; animation-iteration-count: 1 !important; scroll-behavior: auto !important; transition: none !important; }
  .spinner { border-color: var(--accent); opacity: .65; }
  .agent-activity strong::after, .activity-sweep { display: none !important; }
}
@media (forced-colors: active) {
  .dot, .spinner { forced-color-adjust: none; }
  .button, .input, .composer, .send, dialog { border: 1px solid ButtonText; }
}
@media (max-width: 760px) {
  .shell { display: block; }
  .rail { gap: 12px; padding: 10px 8px 12px; border-inline-end: 0; border-bottom: 1px solid var(--border-light); }
  .session-life { padding: 10px 12px; }
  .session-life p { display: none; }
  .session-life-head { margin-bottom: 8px; }
  .rail-end { display: none; }
  .workspace { min-height: 70vh; height: auto; grid-template-rows: auto auto; }
  .mobile-end { display: block; }
  .messages { min-height: 280px; overflow: visible; padding: 20px 14px; }
  .messages > * { scroll-margin-bottom: 140px; }
  .empty { margin: 6vh auto; }
  .empty h1 { font-size: 22px; }
  .empty .lede { font-size: 14px; }
  .composer-wrap { position: sticky; bottom: 0; z-index: 3; padding: 10px 12px max(12px, env(safe-area-inset-bottom)); background: var(--bg); }
}
"""


def _document(title: str, body: str, nonce: str, script: str = "") -> str:
  script_tag = f'<script nonce="{html.escape(nonce)}">{script}</script>' if script else ""
  return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="dark"><meta name="theme-color" content="#0d0d0d">
<title>{html.escape(title)}</title>
<link rel="preload" href="/assets/inter-400.woff2" as="font" type="font/woff2" crossorigin>
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
  return_url: str | None,
) -> str:
  title = "Recovery finished."
  detail = (
    "The temporary capability is closed. Möbius kept running in place while "
    "you worked, and mobius.you is removing this recovery worker."
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
  idle_expires_at: datetime,
  expires_at: datetime,
  idle_timeout_seconds: int,
  readiness_error: str | None = None,
  finishing: bool = False,
) -> str:
  dot_class = "dot pending" if readiness_error or finishing else "dot"
  target_text = (
    "Finishing recovery…"
    if finishing else readiness_error or "Connected to one repair target"
  )
  idle_minutes = max(1, idle_timeout_seconds // 60)
  body = f"""<main class="shell"><aside class="rail"><div class="brand">{_brand_mark()}
<span class="wordmark">Möbius</span><span class="brand-tag">Recovery</span>
<button class="link-button mobile-end" id="finish-mobile" type="button">End recovery</button></div>
<div class="status-line"><span id="target-dot" class="{dot_class}"></span><span><strong>Secure remote access</strong><br>
<span id="target-status">{html.escape(target_text)}</span><br><button class="link-button" id="target-retry" type="button" hidden>Retry target check</button></span></div>
<section class="session-life" id="session-life" aria-labelledby="session-life-title">
<div class="session-life-head"><h2 id="session-life-title">Ends automatically</h2><span class="countdown" id="session-countdown">--:--</span></div>
<p id="session-expiry-copy">After {idle_minutes} minutes without activity. Activity resets the timer; every session ends within one hour.</p>
<button class="button secondary compact" id="keep-open" type="button">Keep open</button></section>
<section><h2 class="section-title">AI provider</h2><div class="providers" id="providers">
<div class="provider"><label class="provider-name"><input type="radio" name="provider" value="claude" checked>Claude</label>
<button class="link-button" data-connect="claude" type="button">Connect Claude</button></div>
<div class="provider"><label class="provider-name"><input type="radio" name="provider" value="codex">Codex</label>
<button class="link-button" data-connect="codex" type="button">Connect Codex</button></div></div>
<p class="provider-state" id="provider-state">Checking provider connection…</p></section>
<div class="rail-end"><p>You can close this tab. Recovery ends on its own, or you can remove the worker now.</p>
<button class="button secondary" id="finish" type="button">End recovery</button></div></aside>
<section class="workspace" aria-label="Repair conversation">
<div class="messages" id="messages"><div class="empty" id="empty"><h1>What needs fixing?</h1>
<p class="lede">Describe what broke and what changed just before. Möbius keeps running while the agent repairs this one container.</p></div></div>
<div class="composer-wrap"><form class="composer" id="composer"><label class="sr" for="message">Message recovery agent</label>
<textarea id="message" rows="1" maxlength="32000" placeholder="Message the recovery agent…" aria-describedby="composer-hint" required></textarea>
<span class="sr" id="composer-hint">Enter to send, Shift+Enter for a new line</span>
<button class="send" id="send" type="submit" aria-label="Send"><svg width="1em" height="1em" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path fill-rule="evenodd" d="M11.293 5.293a1 1 0 0 1 1.414 0l5 5a1 1 0 0 1-1.414 1.414L13 8.414V18a1 1 0 1 1-2 0V8.414l-3.293 3.293a1 1 0 0 1-1.414-1.414l5-5Z" clip-rule="evenodd"></path></svg><span class="spinner" aria-hidden="true"></span></button>
</form></div></section></main>
<template id="icon-terminal"><svg width="1em" height="1em" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8.7587 3H15.2413C16.0463 2.99999 16.7106 2.99998 17.2518 3.04419C17.8139 3.09012 18.3306 3.18868 18.816 3.43597C19.5686 3.81947 20.1805 4.43139 20.564 5.18404C20.8113 5.66937 20.9099 6.18608 20.9558 6.74817C21 7.28936 21 7.95372 21 8.75868V15.2413C21 16.0463 21 16.7106 20.9558 17.2518C20.9099 17.8139 20.8113 18.3306 20.564 18.816C20.1805 19.5686 19.5686 20.1805 18.816 20.564C18.3306 20.8113 17.8139 20.9099 17.2518 20.9558C16.7106 21 16.0463 21 15.2413 21H8.75868C7.95372 21 7.28936 21 6.74817 20.9558C6.18608 20.9099 5.66937 20.8113 5.18404 20.564C4.43139 20.1805 3.81947 19.5686 3.43597 18.816C3.18868 18.3306 3.09012 17.8139 3.04419 17.2518C2.99998 16.7106 2.99999 16.0463 3 15.2413V8.7587C2.99999 7.95373 2.99998 7.28937 3.04419 6.74817C3.09012 6.18608 3.18868 5.66937 3.43597 5.18404C3.81947 4.43139 4.43139 3.81947 5.18404 3.43597C5.66937 3.18868 6.18608 3.09012 6.74817 3.04419C7.28937 2.99998 7.95373 2.99999 8.7587 3ZM6.91104 5.03755C6.47262 5.07337 6.24842 5.1383 6.09202 5.21799C5.7157 5.40973 5.40973 5.7157 5.21799 6.09202C5.1383 6.24842 5.07337 6.47262 5.03755 6.91104C5.00078 7.36113 5 7.94342 5 8.8V15.2C5 16.0566 5.00078 16.6389 5.03755 17.089C5.07337 17.5274 5.1383 17.7516 5.21799 17.908C5.40973 18.2843 5.7157 18.5903 6.09202 18.782C6.24842 18.8617 6.47262 18.9266 6.91104 18.9624C7.36113 18.9992 7.94342 19 8.8 19H15.2C16.0566 19 16.6389 18.9992 17.089 18.9624C17.5274 18.9266 17.7516 18.8617 17.908 18.782C18.2843 18.5903 18.5903 18.2843 18.782 17.908C18.8617 17.7516 18.9266 17.5274 18.9624 17.089C18.9992 16.6389 19 16.0566 19 15.2V8.8C19 7.94342 18.9992 7.36113 18.9624 6.91104C18.9266 6.47262 18.8617 6.24842 18.782 6.09202C18.5903 5.7157 18.2843 5.40973 17.908 5.21799C17.7516 5.1383 17.5274 5.07337 17.089 5.03755C16.6389 5.00078 16.0566 5 15.2 5H8.8C7.94342 5 7.36113 5.00078 6.91104 5.03755ZM7.29289 9.29289C7.68342 8.90237 8.31658 8.90237 8.70711 9.29289L10.7071 11.2929C11.0976 11.6834 11.0976 12.3166 10.7071 12.7071L8.70711 14.7071C8.31658 15.0976 7.68342 15.0976 7.29289 14.7071C6.90237 14.3166 6.90237 13.6834 7.29289 13.2929L8.58579 12L7.29289 10.7071C6.90237 10.3166 6.90237 9.68342 7.29289 9.29289ZM12 14C12 13.4477 12.4477 13 13 13H16C16.5523 13 17 13.4477 17 14C17 14.5523 16.5523 15 16 15H13C12.4477 15 12 14.5523 12 14Z" fill="currentColor"></path></svg></template><template id="icon-files"><svg width="1em" height="1em" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M3.5 15.7002V8.29981C3.5 7.47632 3.49898 6.79843 3.54395 6.24805C3.58988 5.686 3.68827 5.16891 3.93555 4.6836L4.08985 4.40821C4.47414 3.7817 5.02513 3.2711 5.6836 2.93555L5.86719 2.84962C6.29892 2.66443 6.7562 2.58414 7.24805 2.54395C7.79843 2.49898 8.47632 2.50001 9.29981 2.50001H13.5117C14.1979 2.50001 14.7043 2.49341 15.1914 2.61036L15.4941 2.6963C15.7926 2.79335 16.0794 2.92547 16.3477 3.08985L16.5049 3.19239C16.8652 3.44372 17.1889 3.7748 17.6133 4.19923L18.8008 5.38673L19.1426 5.7295C19.4613 6.05339 19.7139 6.3322 19.9102 6.65235L20.0645 6.92676C20.207 7.20655 20.3162 7.50257 20.3897 7.8086L20.4277 7.99317C20.5048 8.42563 20.5 8.88807 20.5 9.48829V15.7002C20.5 16.5237 20.501 17.2016 20.4561 17.752C20.4159 18.2438 20.3356 18.7011 20.1504 19.1328L20.0645 19.3164C19.7289 19.9749 19.2183 20.5259 18.5918 20.9102L18.3164 21.0645C17.8311 21.3117 17.314 21.4101 16.752 21.4561C16.2016 21.501 15.5237 21.5 14.7002 21.5H9.29981C8.47632 21.5 7.79843 21.501 7.24805 21.4561C6.7562 21.4159 6.29892 21.3356 5.86719 21.1504L5.6836 21.0645C5.02513 20.7289 4.47414 20.2183 4.08985 19.5918L3.93555 19.3164C3.68827 18.8311 3.58988 18.314 3.54395 17.752C3.49898 17.2016 3.5 16.5237 3.5 15.7002ZM13 13C13.5523 13 14 13.4477 14 14C14 14.5523 13.5523 15 13 15H9C8.44772 15 8 14.5523 8 14C8 13.4477 8.44772 13 9 13H13ZM15 9.00001C15.5523 9.00001 16 9.44772 16 10C16 10.5523 15.5523 11 15 11H9C8.44772 11 8 10.5523 8 10C8 9.44772 8.44772 9.00001 9 9.00001H15ZM5.5 15.7002C5.5 16.5566 5.50035 17.1388 5.53711 17.5889C5.57293 18.0273 5.63809 18.2518 5.71778 18.4082L5.79492 18.5459C5.98707 18.8592 6.26256 19.1145 6.5918 19.2822L6.72461 19.3389C6.87418 19.3924 7.08253 19.4361 7.41113 19.4629C7.86117 19.4997 8.44342 19.5 9.29981 19.5H14.7002C15.5566 19.5 16.1388 19.4997 16.5889 19.4629C17.0273 19.4271 17.2518 19.3619 17.4082 19.2822L17.5459 19.2051C17.8592 19.0129 18.1145 18.7374 18.2822 18.4082L18.3389 18.2754C18.3924 18.1258 18.436 17.9175 18.4629 17.5889C18.4997 17.1388 18.5 16.5566 18.5 15.7002V9.48829C18.5 8.9025 18.496 8.62789 18.4736 8.44141L18.4443 8.2754C18.4076 8.12258 18.3534 7.9747 18.2822 7.83497L18.2051 7.69727C18.1231 7.56363 18.0144 7.43719 17.7324 7.14942L17.3867 6.80079L16.1992 5.61329C15.7849 5.19901 15.5881 5.00666 15.4404 4.89063L15.3027 4.79493C15.1686 4.71275 15.0252 4.64619 14.876 4.59766L14.7246 4.55567C14.5212 4.50684 14.2931 4.50001 13.5117 4.50001H9.29981C8.44342 4.50001 7.86117 4.50036 7.41113 4.53712C7.08253 4.56396 6.87418 4.60763 6.72461 4.66114L6.5918 4.71778C6.26256 4.88555 5.98707 5.14086 5.79492 5.45411L5.71778 5.5918C5.63809 5.7482 5.57293 5.97272 5.53711 6.41114C5.50035 6.86118 5.5 7.44342 5.5 8.29981V15.7002Z" fill="currentColor"></path></svg></template><template id="icon-search"><svg width="1em" height="1em" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path fill-rule="evenodd" clip-rule="evenodd" d="M10.875 4.5C7.35418 4.5 4.5 7.35418 4.5 10.875C4.5 14.3958 7.35418 17.25 10.875 17.25C14.3958 17.25 17.25 14.3958 17.25 10.875C17.25 7.35418 14.3958 4.5 10.875 4.5ZM2.5 10.875C2.5 6.24962 6.24962 2.5 10.875 2.5C15.5004 2.5 19.25 6.24962 19.25 10.875C19.25 12.8273 18.582 14.6236 17.462 16.0478L21.2071 19.7929C21.5976 20.1834 21.5976 20.8166 21.2071 21.2071C20.8166 21.5976 20.1834 21.5976 19.7929 21.2071L16.0478 17.462C14.6236 18.582 12.8273 19.25 10.875 19.25C6.24962 19.25 2.5 15.5004 2.5 10.875Z" fill="currentColor"></path></svg></template><template id="icon-edit"><svg width="1em" height="1em" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M18.293 5.70712C17.3028 4.71693 15.6974 4.71693 14.7072 5.70712L14.4143 6.00001L18.0001 9.5858L18.293 9.2929C19.2832 8.30272 19.2832 6.69731 18.293 5.70712ZM16.5859 11L13.0001 7.41422L7.15744 13.2569C6.59313 13.8212 6.40354 14.0164 6.25776 14.2298C6.11763 14.4349 6.00352 14.6566 5.91806 14.8899C5.82914 15.1325 5.78049 15.4003 5.64929 16.1875L5.21663 18.7835L7.8126 18.3508C8.5998 18.2196 8.86755 18.1709 9.1102 18.082C9.34345 17.9966 9.56519 17.8825 9.77031 17.7423C9.9837 17.5965 10.1789 17.407 10.7432 16.8426L16.5859 11ZM13.293 4.29291C15.0642 2.52167 17.9359 2.52167 19.7072 4.2929C21.4784 6.06414 21.4784 8.93588 19.7072 10.7071L12.1574 18.2569C12.1364 18.2779 12.1157 18.2986 12.0952 18.3191C11.6165 18.798 11.2849 19.1298 10.8985 19.3938C10.5566 19.6273 10.1871 19.8175 9.79829 19.9599C9.35884 20.121 8.89618 20.198 8.22816 20.3091C8.19962 20.3139 8.17071 20.3187 8.1414 20.3236L5.26923 20.8023C5.25973 20.8039 5.25015 20.8055 5.2405 20.8071C5.07988 20.8339 4.90018 20.8639 4.74411 20.8757C4.57393 20.8885 4.3032 20.893 4.01707 20.7703C3.66337 20.6186 3.38151 20.3367 3.2298 19.983C3.10708 19.6969 3.11156 19.4262 3.1244 19.256C3.13618 19.0999 3.16619 18.9202 3.19302 18.7596C3.19463 18.7499 3.19622 18.7403 3.19781 18.7309L3.6765 15.8587C3.68139 15.8294 3.6862 15.8004 3.69096 15.7719C3.80213 15.1039 3.87913 14.6412 4.04015 14.2018C4.1826 13.813 4.37278 13.4435 4.60632 13.1016C4.87033 12.7152 5.20204 12.3836 5.681 11.9049C5.70147 11.8844 5.72221 11.8637 5.74323 11.8426L13.293 4.29291Z" fill="currentColor"></path></svg></template><template id="icon-web"><svg width="1em" height="1em" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path fill-rule="evenodd" clip-rule="evenodd" d="M2 12C2 6.47715 6.47715 2 12 2C17.5228 2 22 6.47715 22 12C22 17.5228 17.5228 22 12 22C6.47715 22 2 17.5228 2 12ZM11.9851 4.00291C11.9744 4.00615 11.953 4.01416 11.921 4.03356C11.7908 4.11248 11.5742 4.32444 11.325 4.77696C11.0839 5.21453 10.8521 5.8046 10.6514 6.53263C10.3148 7.75315 10.0844 9.29169 10.019 11H13.981C13.9156 9.29169 13.6852 7.75315 13.3486 6.53263C13.1479 5.8046 12.9161 5.21453 12.675 4.77696C12.4258 4.32444 12.2092 4.11248 12.079 4.03356C12.047 4.01416 12.0256 4.00615 12.0149 4.00291C12.0067 4.00046 12.001 4.00006 11.9996 4C11.9982 4.00006 11.9933 4.00046 11.9851 4.00291ZM8.01766 11C8.08396 9.13314 8.33431 7.41167 8.72334 6.00094C8.87366 5.45584 9.04762 4.94639 9.24523 4.48694C6.48462 5.49946 4.43722 7.9901 4.06189 11H8.01766ZM4.06189 13H8.01766C8.09487 15.1737 8.42177 17.1555 8.93 18.6802C9.02641 18.9694 9.13134 19.2483 9.24522 19.5131C6.48461 18.5005 4.43722 16.0099 4.06189 13ZM10.019 13C10.0955 14.9972 10.3973 16.7574 10.8274 18.0477C11.0794 18.8038 11.3575 19.3436 11.6177 19.6737C11.7455 19.8359 11.8494 19.9225 11.9186 19.9649C11.9515 19.9852 11.9736 19.9935 11.9847 19.9969C11.9948 20 11.9999 20 11.9999 20C11.9999 20 12.0049 20.0001 12.0153 19.9969C12.0264 19.9935 12.0485 19.9852 12.0814 19.9649C12.1506 19.9225 12.2545 19.8359 12.3823 19.6737C12.6425 19.3436 12.9206 18.8038 13.1726 18.0477C13.6027 16.7574 13.9045 14.9972 13.981 13H10.019ZM15.9823 13C15.9051 15.1737 15.5782 17.1555 15.07 18.6802C14.9736 18.9694 14.8687 19.2483 14.7548 19.5131C17.5154 18.5005 19.5628 16.0099 19.9381 13H15.9823ZM19.9381 11C19.5628 7.99009 17.5154 5.49946 14.7548 4.48694C14.9524 4.94639 15.1263 5.45584 15.2767 6.00094C15.6657 7.41167 15.916 9.13314 15.9823 11H19.9381Z"></path></svg></template><template id="icon-plan"><svg width="1em" height="1em" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M9.30002 5.6C9.6314 5.15817 9.54185 4.53137 9.10003 4.2C8.6582 3.86863 8.0314 3.95817 7.70003 4.4L5.33158 7.55792L4.64021 6.98178C4.21593 6.62821 3.58537 6.68554 3.2318 7.10981C2.87824 7.53409 2.93556 8.16465 3.35984 8.51822L4.85984 9.76822C5.07041 9.9437 5.34379 10.025 5.61604 9.99325C5.8883 9.96144 6.13556 9.81928 6.30002 9.6L9.30002 5.6Z" fill="currentColor"></path><path d="M12 7C12 6.44771 12.4477 6 13 6H20C20.5523 6 21 6.44771 21 7C21 7.55228 20.5523 8 20 8H13C12.4477 8 12 7.55228 12 7Z" fill="currentColor"></path><path fill-rule="evenodd" clip-rule="evenodd" d="M6.00003 14C4.34317 14 3.00003 15.3431 3.00003 17C3.00003 18.6569 4.34317 20 6.00003 20C7.65688 20 9.00002 18.6569 9.00002 17C9.00002 15.3431 7.65688 14 6.00003 14ZM5.00003 17C5.00003 16.4477 5.44774 16 6.00003 16C6.55231 16 7.00002 16.4477 7.00002 17C7.00002 17.5523 6.55231 18 6.00003 18C5.44774 18 5.00003 17.5523 5.00003 17Z" fill="currentColor"></path><path d="M13 16C12.4477 16 12 16.4477 12 17C12 17.5523 12.4477 18 13 18H20C20.5523 18 21 17.5523 21 17C21 16.4477 20.5523 16 20 16H13Z" fill="currentColor"></path></svg></template><template id="icon-sparkle"><svg width="1em" height="1em" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M11.997 5.9c-.482 1.462-1.233 2.749-2.29 3.806-1.058 1.058-2.345 1.809-3.806 2.291 1.451.475 2.744 1.213 3.81 2.255 1.048 1.025 1.806 2.275 2.286 3.704.472-1.42 1.217-2.675 2.25-3.708 1.034-1.034 2.29-1.779 3.709-2.251-1.429-.48-2.679-1.238-3.704-2.287-1.042-1.065-1.78-2.358-2.255-3.81Zm.005-4.15c.726 0 1.336.546 1.417 1.268.503 4.44 3.021 7.159 7.529 7.559a1.429 1.429 0 0 1-.003 2.846c-4.444.385-7.137 3.078-7.522 7.522a1.429 1.429 0 0 1-2.846.003c-.4-4.508-3.119-7.026-7.56-7.529a1.429 1.429 0 0 1-.002-2.838c4.504-.52 7.046-3.062 7.566-7.566A1.429 1.429 0 0 1 12 1.75Z"></path></svg></template>
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
let currentTurnStartedAt = 0;
let activityTimer;

function setBusy(value) {
  busy = value;
  const disabled = value || finishing;
  $('#send').disabled = disabled || !targetReady || !providerReady;
  $('#message').disabled = disabled;
  $('#finish').disabled = finishing;
  $('#finish-mobile').disabled = finishing;
  $('#keep-open').disabled = finishing;
  $('#send').classList.toggle('working', value);
  $('#send').setAttribute('aria-label', value ? 'Agent working…' : 'Send');
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

// Assistant prose renders the small Markdown subset agents actually write
// (paragraphs, headings, lists, code, bold), built from text nodes only.
const LIST_ITEM = /^\s*([-*+]|\d+[.)])\s+/;
const FENCE = /^\s*```/;
const HEADING = /^#{1,6}\s+/;
const rawText = new WeakMap();

function make(tag, className) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  return element;
}

function renderInline(target, text) {
  const pattern = /`[^`\n]+`|\*\*[^*\n]+\*\*|__[^_\n]+__/g;
  let last = 0;
  let match;
  while ((match = pattern.exec(text))) {
    if (match.index > last) target.append(text.slice(last, match.index));
    const token = match[0];
    const element = token[0] === '`' ? make('code', 'md-inline-code') : make('strong');
    element.textContent = token[0] === '`' ? token.slice(1, -1) : token.slice(2, -2);
    target.append(element);
    last = pattern.lastIndex;
  }
  if (last < text.length) target.append(text.slice(last));
}

function renderMarkdown(target, text) {
  target.replaceChildren();
  const lines = text.split('\n');
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (FENCE.test(line)) {
      const code = [];
      index += 1;
      while (index < lines.length && !FENCE.test(lines[index])) code.push(lines[index++]);
      index += 1;
      const block = make('pre', 'md-code-block');
      block.textContent = code.join('\n');
      target.append(block);
    } else if (!line.trim()) {
      index += 1;
    } else if (HEADING.test(line)) {
      const heading = make('p', 'md-heading');
      renderInline(heading, line.replace(HEADING, ''));
      target.append(heading);
      index += 1;
    } else if (LIST_ITEM.test(line)) {
      const list = make(/^\s*\d/.test(line) ? 'ol' : 'ul', 'md-list');
      while (index < lines.length && LIST_ITEM.test(lines[index])) {
        const item = make('li');
        renderInline(item, lines[index++].replace(LIST_ITEM, ''));
        list.append(item);
      }
      target.append(list);
    } else {
      const paragraph = [];
      while (
        index < lines.length && lines[index].trim() && !FENCE.test(lines[index])
        && !HEADING.test(lines[index]) && !LIST_ITEM.test(lines[index])
      ) paragraph.push(lines[index++].trim());
      const element = make('p', 'md-paragraph');
      renderInline(element, paragraph.join(' '));
      target.append(element);
    }
  }
}

function appendAssistant(content, text) {
  const next = (rawText.get(content) || '') + text;
  rawText.set(content, next);
  renderMarkdown(content, next);
  content.parentElement.scrollIntoView({ block: 'end' });
}

function addMessage(role, text, isError = false) {
  removeEmpty();
  settleActivity();
  const element = make('div', `message ${role}${isError ? ' error-message' : ''}`);
  const label = make('span', 'message-label sr');
  label.textContent = role === 'user' ? 'YOU' : 'RECOVERY AGENT';
  const prose = role === 'assistant' && !isError;
  const content = make(prose ? 'div' : 'span', prose ? 'md' : '');
  element.append(label, content);
  messages.append(element);
  if (prose) appendAssistant(content, text);
  else content.textContent = text;
  element.scrollIntoView({ block: 'end' });
  return content;
}

// Consecutive tool calls form one activity line, worded exactly like the
// shell's: live "Running a command · Reading files", settled "Read files, ran
// commands". Expanding it lists each raw tool name with what it ran.
const ACTIVITIES = new Map([
  ['Read', ['Reading files', 'Read files', 'files']],
  ['Glob', ['Reading files', 'Read files', 'files']],
  ['Grep', ['Searching the code', 'Searched the code', 'search']],
  ['Edit', ['Editing code', 'Edited code', 'edit']],
  ['Write', ['Editing code', 'Edited code', 'edit']],
  ['MultiEdit', ['Editing code', 'Edited code', 'edit']],
  ['NotebookEdit', ['Editing code', 'Edited code', 'edit']],
  ['Bash', ['Running commands', 'Ran commands', 'terminal']],
  ['shell', ['Running commands', 'Ran commands', 'terminal']],
  ['Command', ['Running commands', 'Ran commands', 'terminal']],
  ['WebFetch', ['Browsing the web', 'Browsed the web', 'web']],
  ['WebSearch', ['Browsing the web', 'Browsed the web', 'web']],
  ['TodoWrite', ['Planning', 'Planned', 'plan']],
  ['ToolSearch', ['Planning', 'Planned', 'plan']],
  ['Task', ['Working in the background', 'Worked in the background', 'sparkle']],
  ['Agent', ['Working in the background', 'Worked in the background', 'sparkle']],
  ['Skill', ['Using skills', 'Used skills', 'sparkle']],
]);
const SINGULAR = new Map([
  ['Running commands', 'Running a command'], ['Ran commands', 'Ran a command'],
  ['Reading files', 'Reading a file'], ['Read files', 'Read a file'],
  ['Using skills', 'Using a skill'], ['Used skills', 'Used a skill'],
]);
let activity = null;

function activitySummary(names, live) {
  const seen = [];
  const counts = new Map();
  const words = name => ACTIVITIES.get(name)?.[live ? 0 : 1];
  for (const name of live ? [names[names.length - 1], ...names] : names) {
    const label = words(name) || name || 'Tool';
    if (!seen.some(entry => entry.label === label)) seen.push({ label, known: Boolean(words(name)) });
  }
  for (const name of names) {
    const label = words(name) || name || 'Tool';
    counts.set(label, (counts.get(label) || 0) + 1);
  }
  const shown = seen.slice(0, 3).map(({ label, known }, position) => {
    const text = counts.get(label) === 1 ? (SINGULAR.get(label) || label) : label;
    return !live && position > 0 && known ? text[0].toLowerCase() + text.slice(1) : text;
  });
  const extra = seen.length > 3 ? ` +${seen.length - 3}` : '';
  return shown.join(live ? ' · ' : ', ') + extra;
}

function renderActivity() {
  const { names, label, sweep, icon, element } = activity;
  const live = activity.live;
  const text = activitySummary(names, live);
  label.firstChild.textContent = text;
  sweep.textContent = text;
  element.classList.toggle('running', live);
  const kind = ACTIVITIES.get(live ? names[names.length - 1] : names[0])?.[2] || 'sparkle';
  icon.replaceChildren($(`#icon-${kind}`).content.cloneNode(true));
}

function addTool(name, detail = '') {
  removeEmpty();
  stopAgentActivity();
  if (!activity) {
    const element = make('div', 'activity');
    const header = make('button', 'activity-header');
    header.type = 'button';
    header.setAttribute('aria-expanded', 'false');
    const icon = make('span', 'activity-icon');
    const label = make('span', 'activity-label');
    label.append(document.createTextNode(''));
    const sweep = make('span', 'activity-sweep');
    sweep.setAttribute('aria-hidden', 'true');
    label.append(sweep);
    header.append(icon, label);
    const timeline = make('div', 'activity-timeline');
    timeline.hidden = true;
    header.addEventListener('click', () => {
      timeline.hidden = !timeline.hidden;
      header.setAttribute('aria-expanded', String(!timeline.hidden));
    });
    element.append(header, timeline);
    messages.append(element);
    activity = { element, timeline, label, sweep, icon, names: [], live: busy || remoteBusy };
  }
  activity.names.push(name || 'Tool');
  const step = make('div', 'activity-step');
  const stepName = make('span', 'activity-step-name');
  stepName.textContent = name || 'Tool';
  step.append(stepName);
  if (detail) {
    const command = make('pre', 'tool-detail');
    command.textContent = detail;
    step.append(command);
  }
  activity.timeline.append(step);
  renderActivity();
  activity.element.scrollIntoView({ block: 'end' });
}

function settleActivity() {
  if (!activity) return;
  activity.live = false;
  renderActivity();
  activity = null;
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

function startAgentActivity(
  provider,
  label = 'Recovery agent is starting',
  startedAt = Date.now(),
) {
  stopAgentActivity();
  removeEmpty();
  const candidate = Number(startedAt);
  activityStartedAt = Number.isFinite(candidate) && candidate > 0
    ? Math.min(candidate, Date.now())
    : Date.now();
  currentTurnStartedAt = activityStartedAt;
  activityElement = make('div', 'agent-activity');
  activityElement.role = 'status';
  const icon = make('span', 'activity-icon');
  icon.append($('#icon-sparkle').content.cloneNode(true));
  const body = make('span');
  const headline = make('strong');
  headline.textContent = label;
  headline.dataset.label = label;
  const detail = make('small');
  detail.setAttribute('aria-hidden', 'true');
  const providerName = provider === 'codex' ? 'Codex' : 'Claude';
  body.append(headline, detail);
  activityElement.append(icon, body);
  messages.append(activityElement);
  activityElement.scrollIntoView({ block: 'end' });
  const updateDetail = () => {
    const elapsed = Date.now() - activityStartedAt;
    detail.textContent = elapsed < 60000
      ? `${providerName} is connecting · ${elapsedLabel(elapsed)} elapsed · first response can take about a minute`
      : `Still working · ${elapsedLabel(elapsed)} elapsed`;
  };
  updateDetail();
  activityTimer = setInterval(updateDetail, 1000);
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

function fitComposer() {
  const input = $('#message');
  input.style.height = 'auto';
  input.style.height = `${Math.min(input.scrollHeight, 200)}px`;
}

$('#message').addEventListener('input', fitComposer);

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
  fitComposer();
  currentTurnStartedAt = Date.now();
  startAgentActivity(provider, 'Recovery agent is starting', currentTurnStartedAt);
  let assistantSegment;
  let receivedText = false;
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
          if (!assistantSegment) assistantSegment = addMessage('assistant', '');
          appendAssistant(assistantSegment, payload.content);
          receivedText = true;
        } else if (payload.type === 'tool') {
          assistantSegment = null;
          addTool(payload.name, payload.detail);
        } else if (payload.type === 'error') {
          stopAgentActivity();
          assistantSegment = null;
          addMessage('assistant', payload.message, true);
          if (payload.code === 'provider_auth_required') refreshProviders();
          reportedError = true;
        }
      }
    }
    if (!receivedText && !reportedError) {
      stopAgentActivity();
      addMessage('assistant', 'The recovery agent finished without returning a message.', true);
    }
  } catch (error) {
    stopAgentActivity();
    if (!redirectLost(error) && !reportedError) addMessage('assistant', error.message, true);
  } finally {
    stopAgentActivity();
    settleActivity();
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
    handleFinish(await api('/api/finish', { method: 'POST', body: '{}' }));
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
      activity = null;
    }
    if (!replace && !empty) return;
    data.messages.forEach(message => {
      if (message.role === 'tool') {
        addTool(message.name, message.content);
      } else if (message.role === 'user' || message.role === 'assistant') {
        addMessage(message.role, message.content);
      }
    });
    settleActivity();
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
      const provider = ['claude', 'codex'].includes(data.provider)
        ? data.provider
        : $('input[name=provider]:checked').value;
      startAgentActivity(
        provider,
        'Recovery agent is still working',
        data.started_at_ms,
      );
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
    if (!targetReady) refreshTarget();
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
  async function initializeWorkspace() {
    await loadHistory();
    await refreshProviders();
    heartbeatVisibility();
  }
  initializeWorkspace();
}
"""

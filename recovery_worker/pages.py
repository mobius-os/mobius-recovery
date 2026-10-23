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
.rail-end { display: grid; gap: 10px; margin-top: auto; padding: 14px 4px 0; border-top: 1px solid var(--border-light); }
.rail-end p { margin: 0; padding: 0 8px; color: var(--muted); font-size: 13px; line-height: 1.5; }
.workspace { display: grid; min-width: 0; height: 100vh; grid-template-columns: minmax(0, 1fr); grid-template-rows: auto minmax(0, 1fr) auto; }
.workspace-head { display: flex; min-height: 58px; align-items: center; justify-content: space-between; gap: 16px; padding: 10px 24px; border-bottom: 1px solid var(--border-light); }
.workspace-head strong { font-weight: 600; }
.workspace-head p { margin: 1px 0 0; color: var(--muted); font-size: 13px; }
.mobile-end { display: none; }
.messages { overflow: auto; padding: 28px max(20px, calc((100% - 720px) / 2)); }
.empty { max-width: 600px; margin: 14vh auto 0; text-align: center; }
.empty .lede { margin-inline: auto; }
.empty-note { display: flex; max-width: 52ch; gap: 8px; margin: 0 auto; color: var(--muted); font-size: 13px; text-align: start; }
.empty-note svg { flex: none; width: 16px; height: 16px; margin-top: 2px; }
.message { margin: 0 0 16px; overflow-wrap: anywhere; line-height: 1.7; white-space: pre-wrap; }
.message.assistant { padding: 0 8px; }
.message.user {
  width: fit-content; max-width: min(85%, 640px); margin-left: auto; padding: 11px 16px;
  border-radius: 18px 18px 5px 18px; color: #fff;
  background: linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 78%, #000));
  box-shadow: 0 2px 14px -4px var(--accent-dim);
}
.message.error-message { color: #fecaca; }
.tool { margin: 0 0 8px; padding-left: 6px; color: var(--muted); font-size: 13px; }
.tool > summary { display: flex; min-width: 0; align-items: center; gap: 8px; width: fit-content; max-width: 100%; padding: 2px 0; list-style: none; cursor: pointer; }
.tool > summary::-webkit-details-marker { display: none; }
.tool > summary:hover { color: var(--text); }
.tool > summary svg { flex: none; width: 14px; height: 14px; }
.tool-label { flex: none; }
.tool-preview { min-width: 0; overflow: hidden; color: var(--muted); font: 12px var(--mono); text-overflow: ellipsis; white-space: nowrap; opacity: .8; }
.tool[open] .tool-preview { display: none; }
.tool-detail { margin: 6px 0 4px; padding: 10px 12px; overflow: auto; max-height: 320px; border: 1px solid var(--border-light); border-radius: 10px; background: var(--surface); color: var(--text); font: 12px/1.55 var(--mono); white-space: pre-wrap; overflow-wrap: anywhere; }
.agent-activity { display: flex; align-items: flex-start; gap: 8px; margin: 0 0 12px; padding-left: 6px; color: var(--muted); font-size: 13px; }
.spinner { flex: none; width: 12px; height: 12px; margin-top: 4px; border: 1.5px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin .75s linear infinite; }
.agent-activity strong { position: relative; display: inline-block; color: var(--muted); font-weight: 400; }
.agent-activity strong::after { content: attr(data-label); position: absolute; inset: 0; overflow: hidden; color: var(--text); white-space: nowrap; -webkit-mask: linear-gradient(90deg, transparent, #000 35%, transparent 70%) 120% 0 / 300% 100% no-repeat; mask: linear-gradient(90deg, transparent, #000 35%, transparent 70%) 120% 0 / 300% 100% no-repeat; animation: sweep 2.4s steps(48,end) infinite; }
.agent-activity small { display: block; margin-top: 1px; color: var(--muted); font-size: 12px; font-variant-numeric: tabular-nums; opacity: .8; }
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
.send:disabled { cursor: not-allowed; opacity: .4; }
.send svg { width: 18px; height: 18px; }
.send .spinner { display: none; margin: 0; border-color: rgba(255,255,255,.35); border-top-color: #fff; }
.send.working { opacity: 1; }
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
  .agent-activity strong::after { display: none; }
}
@media (forced-colors: active) {
  .dot, .spinner { forced-color-adjust: none; }
  .button, .input, .composer, .send, dialog { border: 1px solid ButtonText; }
}
@media (max-width: 760px) {
  .shell { display: block; }
  .rail { gap: 12px; padding: 10px 8px 12px; border-inline-end: 0; border-bottom: 1px solid var(--border-light); }
  .session-life { padding: 10px 12px; }
  .session-life p { margin: 2px 0 8px; font-size: 12px; }
  .rail-end { display: none; }
  .workspace { min-height: 76vh; height: auto; grid-template-rows: auto auto auto; }
  .workspace-head { padding: 10px 16px; }
  .mobile-end { display: block; }
  .messages { min-height: 280px; overflow: visible; padding: 20px 14px; }
  .messages > * { scroll-margin-bottom: 140px; }
  .empty { margin: 4vh 0; }
  .empty h1 { font-size: 22px; }
  .empty .lede, .empty-note { display: none; }
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
<span class="wordmark">Möbius</span><span class="brand-tag">Recovery</span></div><div class="status-line"><span id="target-dot" class="{dot_class}"></span><span><strong>Secure remote access</strong><br>
<span id="target-status">{html.escape(target_text)}</span><br><button class="link-button" id="target-retry" type="button" hidden>Retry target check</button></span></div>
<section class="session-life" id="session-life" aria-labelledby="session-life-title">
<div class="session-life-head"><h2 id="session-life-title">Ends automatically</h2><span class="countdown" id="session-countdown">--:--</span></div>
<p id="session-expiry-copy">After {idle_minutes} minutes without activity. Activity resets the timer; every session ends within one hour.</p>
<button class="button secondary compact" id="keep-open" type="button">Keep open</button></section>
<section><h2 class="section-title">AI provider</h2><div class="providers" id="providers">
<div class="provider"><label class="provider-name"><input type="radio" name="provider" value="claude" checked>Claude</label>
<button class="link-button" data-connect="claude" type="button">Connect Claude</button></div>
<div class="provider"><label class="provider-name"><input type="radio" name="provider" value="codex">Codex</label>
<button class="link-button" data-connect="codex" type="button">Connect Codex</button></div></div></section>
<div class="rail-end"><p>You can close this tab. Recovery will end on its own, or you can remove the worker now.</p>
<button class="button secondary" id="finish" type="button">End recovery</button></div></aside>
<section class="workspace"><header class="workspace-head"><div><strong>Repair conversation</strong>
<p id="provider-state">Checking provider connection…</p></div><button class="link-button mobile-end" id="finish-mobile" type="button">End recovery</button></header>
<div class="messages" id="messages"><div class="empty" id="empty"><h1>What needs fixing?</h1>
<p class="lede">Describe what failed, what changed just before it, and what still works. The agent can inspect and repair only this Möbius container.</p>
<div class="empty-note"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M12 3 4.5 6v5.5c0 4.5 3.1 7.6 7.5 9.5 4.4-1.9 7.5-5 7.5-9.5V6L12 3Z"/><path d="m9 12 2 2 4-4"/></svg><span>Möbius keeps running while you work. Commands use temporary root access through the fixed recovery relay.</span></div></div></div>
<div class="composer-wrap"><form class="composer" id="composer"><label class="sr" for="message">Message recovery agent</label>
<textarea id="message" rows="1" maxlength="32000" placeholder="Describe the problem…" aria-describedby="composer-hint" required></textarea>
<span class="sr" id="composer-hint">Enter to send, Shift+Enter for a new line</span>
<button class="send" id="send" type="submit" aria-label="Send"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M5.5 11.5 12 5l6.5 6.5"/></svg><span class="spinner" aria-hidden="true"></span></button>
</form></div></section></main>
<template id="tool-icon"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 8 4 4-4 4M12 17h7"/></svg></template>
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

function addMessage(role, text, isError = false) {
  removeEmpty();
  const element = document.createElement('div');
  element.className = `message ${role}${isError ? ' error-message' : ''}`;
  const label = document.createElement('span');
  label.className = 'message-label sr';
  label.textContent = role === 'user' ? 'YOU' : 'RECOVERY AGENT';
  const content = document.createElement('span');
  content.textContent = text;
  element.append(label, content);
  messages.append(element);
  element.scrollIntoView({ block: 'end' });
  return content;
}

function addTool(name, detail = '') {
  removeEmpty();
  const element = document.createElement(detail ? 'details' : 'div');
  element.className = 'tool';
  const summary = document.createElement(detail ? 'summary' : 'div');
  summary.append($('#tool-icon').content.cloneNode(true));
  const label = document.createElement('span');
  label.className = 'tool-label';
  label.textContent = /^(bash|command|exec|shell)$/i.test(name || '')
    ? 'Ran a command on Möbius'
    : `Used ${name || 'a tool'} on Möbius`;
  summary.append(label);
  element.append(summary);
  if (detail) {
    const preview = document.createElement('span');
    preview.className = 'tool-preview';
    preview.textContent = detail.split('\n', 1)[0];
    summary.append(preview);
    const command = document.createElement('pre');
    command.className = 'tool-detail';
    command.textContent = detail;
    element.append(command);
  }
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
  activityElement = document.createElement('div');
  activityElement.className = 'agent-activity';
  activityElement.role = 'status';
  const spinner = document.createElement('span');
  spinner.className = 'spinner';
  spinner.setAttribute('aria-hidden', 'true');
  const body = document.createElement('span');
  const headline = document.createElement('strong');
  headline.textContent = label;
  headline.dataset.label = label;
  const detail = document.createElement('small');
  detail.setAttribute('aria-hidden', 'true');
  const providerName = provider === 'codex' ? 'Codex' : 'Claude';
  body.append(headline, detail);
  activityElement.append(spinner, body);
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
          assistantSegment.textContent += payload.content;
          assistantSegment.parentElement.scrollIntoView({ block: 'end' });
          receivedText = true;
        } else if (payload.type === 'tool') {
          stopAgentActivity();
          assistantSegment = null;
          addTool(payload.name, payload.detail);
          startAgentActivity(
            provider,
            'Recovery agent is continuing',
            currentTurnStartedAt,
          );
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
    }
    if (!replace && !empty) return;
    data.messages.forEach(message => {
      if (message.role === 'tool') {
        addTool(message.name, message.content);
      } else if (message.role === 'user' || message.role === 'assistant') {
        addMessage(message.role, message.content);
      }
    });
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

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


_STYLE = """
:root{color-scheme:dark;--canvas:#0c0c0e;--rail:#131316;--raised:#1a1a1f;
--text:#f3f1f7;--muted:#b9b4c2;--border:#34313a;--accent:#9177ff;
--accent2:#7259dd;--success:#55c995;--danger:#ff7b82;--focus:#c8baff}
*{box-sizing:border-box}html,body{margin:0;min-height:100%;background:var(--canvas);
color:var(--text);font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
body{min-height:100vh}button,input,textarea{font:inherit}button{cursor:pointer}
a{color:var(--focus)}:focus-visible{outline:3px solid var(--focus);outline-offset:3px}
.start{min-height:100vh;display:grid;place-items:center;padding:24px}.start-main{width:min(100%,430px)}
.mark{width:42px;height:42px;display:grid;place-items:center;border:1px solid var(--border);
border-radius:14px;font-size:26px;margin-bottom:28px;background:var(--rail)}
h1,h2,p{margin-top:0}h1{font-size:clamp(2rem,7vw,3.3rem);line-height:1.02;
letter-spacing:-.025em;margin-bottom:14px}h2{font-size:1.05rem;letter-spacing:-.015em}
.lede{color:var(--muted);line-height:1.65;margin-bottom:28px;max-width:62ch}
label{display:block;font-size:.84rem;font-weight:650;margin-bottom:8px}.input{width:100%;
border:1px solid var(--border);background:var(--raised);color:var(--text);border-radius:12px;
padding:13px 14px}.button{border:0;border-radius:12px;padding:12px 15px;font-weight:700;
background:var(--accent);color:#100d18}.button:hover{background:#a38dff}.button:disabled{opacity:.48;
cursor:not-allowed}.button.secondary{background:var(--raised);color:var(--text);border:1px solid var(--border)}
.button.secondary:hover{background:#24232a}.button.danger{background:transparent;color:var(--danger);
border:1px solid #78494e}.error{color:#ffd0d2;background:#351d20;border:1px solid #704146;
padding:12px 14px;border-radius:12px;line-height:1.5}.stack{display:grid;gap:12px}
.shell{min-height:100vh;display:grid;grid-template-columns:310px minmax(0,1fr)}
.rail{background:var(--rail);border-right:1px solid var(--border);padding:24px;display:flex;
flex-direction:column;gap:28px}.brand{display:flex;align-items:center;gap:11px;font-weight:750}
.brand .mark{width:34px;height:34px;font-size:20px;margin:0;border-radius:11px}.status-line{display:flex;
align-items:flex-start;gap:10px;color:var(--muted);font-size:.9rem;line-height:1.45}.dot{width:9px;
height:9px;border-radius:50%;margin-top:5px;background:var(--success);box-shadow:0 2px 10px #55c99555}
.dot.pending{background:var(--accent);animation:pulse 1.8s ease-out infinite}.facts{display:grid;gap:13px;
padding:18px 0;border-top:1px solid var(--border);border-bottom:1px solid var(--border)}
.fact span{display:block}.fact-label{color:var(--muted);font-size:.75rem;margin-bottom:3px}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.78rem;overflow-wrap:anywhere}
.providers{display:grid;gap:9px}.provider{display:flex;align-items:center;justify-content:space-between;
gap:10px;padding:10px 0}.provider-name{display:flex;align-items:center;gap:9px}.provider input{accent-color:var(--accent)}
.link-button{border:0;background:none;color:var(--focus);padding:5px;font-size:.82rem}
.rail-end{margin-top:auto;display:grid;gap:9px}.workspace{min-width:0;display:grid;
grid-template-rows:auto minmax(0,1fr) auto;height:100vh}.workspace-head{padding:22px 30px;
border-bottom:1px solid var(--border);display:flex;justify-content:space-between;gap:16px;align-items:center}
.workspace-head p{margin:3px 0 0;color:var(--muted);font-size:.85rem}.messages{overflow:auto;
padding:36px max(24px,calc((100% - 780px)/2));scrollbar-color:var(--border) transparent}
.empty{max-width:640px;margin:12vh auto 0}.empty h1{font-size:clamp(2rem,5vw,4.2rem);max-width:11ch}
.empty p{max-width:56ch}.message{max-width:720px;margin:0 auto 28px;line-height:1.65;white-space:pre-wrap;
overflow-wrap:anywhere}.message.user{background:var(--raised);border-radius:14px;padding:15px 17px;
box-shadow:0 7px 20px #00000028}.message-label{display:block;color:var(--muted);font-size:.72rem;
font-weight:700;margin-bottom:7px}.tool{max-width:720px;margin:0 auto 16px;color:var(--muted);
font-size:.82rem}.composer-wrap{padding:16px max(18px,calc((100% - 820px)/2)) 24px;
background:linear-gradient(transparent,var(--canvas) 25%)}.composer{border:1px solid #4a4555;
background:var(--raised);border-radius:16px;padding:12px;box-shadow:0 10px 28px #0008}
textarea{display:block;width:100%;min-height:74px;max-height:220px;resize:vertical;background:transparent;
border:0;color:var(--text);padding:4px 5px 10px;line-height:1.5}textarea:focus{outline:0}
.composer-foot{display:flex;align-items:center;justify-content:space-between;gap:12px}.hint{font-size:.75rem;
color:var(--muted)}dialog{color:var(--text);background:var(--rail);border:1px solid var(--border);
border-radius:16px;padding:22px;width:min(calc(100% - 32px),520px);box-shadow:0 18px 60px #000b}
dialog::backdrop{background:#050506cc}.dialog-actions{display:flex;gap:10px;justify-content:flex-end;margin-top:20px}
.code{font:700 1.5rem ui-monospace,SFMono-Regular,monospace;letter-spacing:.06em;padding:16px;
background:var(--canvas);border-radius:12px;text-align:center;user-select:all}.sr{position:absolute;width:1px;
height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
@keyframes pulse{50%{box-shadow:0 2px 18px #9177ffaa}}@media(prefers-reduced-motion:reduce){.dot{animation:none!important}}
@media(max-width:760px){.shell{display:block}.rail{border-right:0;border-bottom:1px solid var(--border);
padding:18px;gap:20px}.facts{grid-template-columns:1fr 1fr}.rail-end{margin:0}.workspace{height:auto;
min-height:78vh;grid-template-rows:auto auto auto}.workspace-head{padding:18px}.messages{overflow:visible;padding:28px 18px;
min-height:42vh}.empty{margin:5vh 0}.composer-wrap{position:static;padding:12px;background:var(--canvas)}}
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
  body = f"""<main class="start"><div class="start-main"><div class="mark" aria-hidden="true">∞</div>
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
  body = f"""<main class="start"><div class="start-main"><div class="mark" aria-hidden="true">∞</div>
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
  body = f"""<main class="start"><div class="start-main"><div class="mark" aria-hidden="true">∞</div>
<h1>{html.escape(title)}</h1><p class="lede">{html.escape(detail)}</p>{action}</div></main>"""
  return _document("Recovery closed · Möbius", body, nonce)


def recovery_page(
  nonce: str,
  *,
  protocol_version: str,
  build_sha: str,
  session_id: str,
  readiness_error: str | None = None,
  finishing: bool = False,
) -> str:
  facts = {"protocol": protocol_version, "build": build_sha, "session": session_id}
  dot_class = "dot pending" if readiness_error or finishing else "dot"
  target_text = (
    "Finishing recovery…"
    if finishing else readiness_error or "Connected to one repair target"
  )
  body = f"""<main class="shell"><aside class="rail"><div class="brand"><div class="mark" aria-hidden="true">∞</div>
<span>Möbius Recovery</span></div><div class="status-line"><span id="target-dot" class="{dot_class}"></span><span><strong>Isolated worker</strong><br>
<span id="target-status">{html.escape(target_text)}</span></span></div><div class="facts">"""
  for label, value in facts.items():
    body += f'<div class="fact"><span class="fact-label">{html.escape(label.title())}</span><span class="mono">{html.escape(value)}</span></div>'
  body += """</div><section><h2>AI provider</h2><div class="providers" id="providers">
<div class="provider"><label class="provider-name"><input type="radio" name="provider" value="claude" checked>Claude</label>
<button class="link-button" data-connect="claude" type="button">Connect Claude</button></div>
<div class="provider"><label class="provider-name"><input type="radio" name="provider" value="codex">Codex</label>
<button class="link-button" data-connect="codex" type="button">Connect Codex</button></div></div></section>
<div class="rail-end"><button class="button secondary" id="finish" type="button">Finish recovery</button>
<button class="button danger" id="cancel" type="button">Cancel session</button></div></aside>
<section class="workspace"><header class="workspace-head"><div><strong>Repair conversation</strong>
<p id="provider-state">Checking provider connection…</p></div><span class="mono">remote only</span></header>
<div class="messages" id="messages" aria-live="polite"><div class="empty" id="empty"><h1>What went wrong?</h1>
<p class="lede">Describe the failure, what changed just before it, and what still works. The agent can inspect and repair only the bound target.</p></div></div>
<div class="composer-wrap"><form class="composer" id="composer"><label class="sr" for="message">Message recovery agent</label>
<textarea id="message" maxlength="32000" placeholder="Describe the problem…" required></textarea><div class="composer-foot">
<span class="hint">Enter to send · Shift+Enter for a new line</span><button class="button" id="send" type="submit">Send</button>
</div></form></div></section></main>
<dialog id="provider-dialog"><h2 id="dialog-title">Connect provider</h2><div id="dialog-body"></div>
<div class="dialog-actions"><button class="button secondary" id="dialog-close" type="button">Close</button></div></dialog>
<dialog id="finish-dialog"><h2>Finish this recovery?</h2><p class="lede">Möbius will keep running in place. This closes the temporary capability and removes the recovery worker.</p>
<div class="dialog-actions"><button class="button secondary" data-finish-close type="button">Keep working</button>
<button class="button" data-finish-confirm type="button">Finish recovery</button></div></dialog>"""
  script = _SCRIPT.replace(
    "const initialFinishing=false;",
    f"const initialFinishing={'true' if finishing else 'false'};",
  )
  return _document("Repair · Möbius Recovery", body, nonce, script)


_SCRIPT = r"""
history.replaceState(null,'','/');
const $=s=>document.querySelector(s), messages=$('#messages'), empty=$('#empty');
const initialFinishing=false;
let busy=false,finishing=initialFinishing,finishTimer;
function setBusy(value){busy=value;const disabled=value||finishing;$('#send').disabled=disabled;$('#message').disabled=disabled;$('#finish').disabled=disabled;$('#cancel').disabled=disabled;
 $('#finish').title=value?'Wait for the active recovery turn to finish.':'';$('#cancel').title=$('#finish').title}
function enterFinishing(message='Finishing recovery…'){finishing=true;setBusy(true);$('#finish-dialog').close();
 document.querySelectorAll('[data-connect],input[name=provider]').forEach(el=>el.disabled=true);$('#target-dot').className='dot pending';$('#target-status').textContent=message;
 clearInterval(heartbeatTimer);clearTimeout(targetRetryTimer)}
function addMessage(role,text){empty?.remove();const el=document.createElement('div');el.className='message '+role;
 const label=document.createElement('span');label.className='message-label';label.textContent=role==='user'?'YOU':'RECOVERY AGENT';
 const content=document.createElement('span');content.textContent=text;el.append(label,content);messages.append(el);el.scrollIntoView({block:'end'});return content}
function addTool(name){const el=document.createElement('div');el.className='tool';el.textContent='Working remotely · '+name;messages.append(el)}
function redirectLost(error){if(error?.status===401){location.replace('/');return true}return false}
async function api(path,options={}){const r=await fetch(path,{...options,headers:{'Content-Type':'application/json',...(options.headers||{})}});
 const data=await r.json().catch(()=>({error:{message:'Unexpected server response.'}}));if(!r.ok){const error=new Error(data.error?.message||'Request failed.');error.status=r.status;error.code=data.error?.code;redirectLost(error);throw error}return data}
async function refreshProviders(){try{const s=await api('/api/providers');document.querySelectorAll('[data-connect]').forEach(b=>{
 const name=b.dataset.connect[0].toUpperCase()+b.dataset.connect.slice(1),connected=!!s[b.dataset.connect];b.textContent=connected?name+' connected':'Connect '+name;b.disabled=connected});const chosen=$('input[name=provider]:checked').value;
 $('#provider-state').textContent=s[chosen]?chosen[0].toUpperCase()+chosen.slice(1)+' is connected':'Connect '+chosen+' before sending';}catch(e){if(!redirectLost(e))$('#provider-state').textContent=e.message}}
document.querySelectorAll('input[name=provider]').forEach(r=>r.addEventListener('change',refreshProviders));
let targetRetryTimer;
async function refreshTarget(){try{await api('/api/target/health');$('#target-dot').className='dot';$('#target-status').textContent='Connected to one repair target'}
 catch(e){if(redirectLost(e))return;$('#target-dot').className='dot pending';$('#target-status').textContent=e.message;if(document.visibilityState==='visible')targetRetryTimer=setTimeout(refreshTarget,2500)}}
document.querySelectorAll('[data-connect]').forEach(b=>b.addEventListener('click',async()=>{const provider=b.dataset.connect,d=$('#provider-dialog');
 $('#dialog-title').textContent='Connect '+(provider==='claude'?'Claude':'Codex');$('#dialog-body').textContent='Starting secure login…';d.showModal();
 try{if(provider==='claude'){const data=await api('/api/providers/claude/start',{method:'POST',body:'{}'});const box=document.createElement('div');
 box.className='stack';const link=document.createElement('a');link.href=data.auth_url;link.target='_blank';link.rel='noopener noreferrer';link.textContent='Open Claude authorization';
 const input=document.createElement('input');input.className='input';input.placeholder='Paste the authorization code';input.autocomplete='off';
 const submit=document.createElement('button');submit.className='button';submit.textContent='Complete connection';submit.onclick=async()=>{await api('/api/providers/claude/exchange',{method:'POST',body:JSON.stringify({code:input.value})});d.close();refreshProviders()};box.append(link,input,submit);$('#dialog-body').replaceChildren(box)
 }else{const data=await api('/api/providers/codex/start',{method:'POST',body:'{}'});const box=document.createElement('div');box.className='stack';
 const link=document.createElement('a');link.href=data.url;link.target='_blank';link.rel='noopener noreferrer';link.textContent='Open Codex authorization';
 const code=document.createElement('div');code.className='code';code.textContent=data.code;const state=document.createElement('p');state.className='lede';state.textContent='Waiting for authorization…';box.append(link,code,state);$('#dialog-body').replaceChildren(box);
 const poll=setInterval(async()=>{if(document.visibilityState!=='visible')return;try{const s=await api('/api/providers/codex/status');if(s.state==='complete'){clearInterval(poll);d.close();refreshProviders()}else if(s.state==='failed'){clearInterval(poll);state.textContent='Login failed. Close and try again.'}}catch(e){clearInterval(poll);if(!redirectLost(e))state.textContent=e.message}},1200)}}catch(e){if(!redirectLost(e))$('#dialog-body').textContent=e.message}}));
$('#dialog-close').onclick=()=>$('#provider-dialog').close();
$('#message').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();$('#composer').requestSubmit()}});
$('#composer').addEventListener('submit',async e=>{e.preventDefault();if(busy)return;const input=$('#message'),text=input.value.trim();if(!text)return;
 const provider=$('input[name=provider]:checked').value;setBusy(true);addMessage('user',text);input.value='';let assistant;
 try{const response=await fetch('/api/chat/stream',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text,provider})});
 if(!response.ok){const d=await response.json();const error=new Error(d.error?.message||'Could not start recovery agent.');error.status=response.status;error.code=d.error?.code;redirectLost(error);throw error}const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
 while(true){const {done,value}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});let split;
 while((split=buffer.indexOf('\n\n'))>=0){const block=buffer.slice(0,split);buffer=buffer.slice(split+2);const line=block.split('\n').find(x=>x.startsWith('data: '));if(!line)continue;
 const ev=JSON.parse(line.slice(6));if(ev.type==='text'){if(!assistant)assistant=addMessage('assistant','');assistant.textContent+=ev.content;assistant.parentElement.scrollIntoView({block:'end'})}
 else if(ev.type==='tool')addTool(ev.name);else if(ev.type==='error')addMessage('assistant','Error: '+ev.message)}}
 }catch(err){addMessage('assistant','Error: '+err.message)}finally{setBusy(false);input.focus()}});
$('#finish').onclick=()=>$('#finish-dialog').showModal();$('[data-finish-close]').onclick=()=>$('#finish-dialog').close();
function handleFinish(data){if(data.status==='finished'){location.replace('/');return}if(data.status==='resumed'){location.reload();return}
 if(data.status==='failed'||data.status==='resumed'){const message=data.error?.message||'Recovery could not be finished.';enterFinishing(message);return}
 clearTimeout(finishTimer);finishTimer=setTimeout(pollFinish,1200)}
async function pollFinish(){if(!finishing)return;try{handleFinish(await api('/api/finish/status'))}catch(e){if(redirectLost(e))return;
 $('#target-status').textContent='Still waiting for finish status · '+e.message;finishTimer=setTimeout(pollFinish,1800)}}
async function finish(outcome){enterFinishing();try{handleFinish(await api('/api/finish',{method:'POST',body:JSON.stringify({outcome})}))}
 catch(e){if(redirectLost(e))return;if(e.status&&e.status<500){finishing=false;setBusy(false);alert(e.message)}else{
 $('#target-status').textContent='Confirming finish status…';finishTimer=setTimeout(pollFinish,1200)}}}
$('[data-finish-confirm]').onclick=()=>finish('recovered');$('#cancel').onclick=()=>{if(confirm('Cancel this recovery session?'))finish('cancelled')};
let heartbeatTimer;
async function heartbeat(){if(document.visibilityState!=='visible'||busy)return;try{await api('/api/turn')}catch(error){redirectLost(error)}}
function heartbeatVisibility(){clearInterval(heartbeatTimer);clearTimeout(targetRetryTimer);if(document.visibilityState==='visible'){heartbeat();refreshTarget();heartbeatTimer=setInterval(heartbeat,45000)}}
document.addEventListener('visibilitychange',heartbeatVisibility);window.addEventListener('pagehide',()=>{clearInterval(heartbeatTimer);clearTimeout(targetRetryTimer)});
if(initialFinishing){enterFinishing();pollFinish()}else{refreshProviders();heartbeatVisibility()}
"""

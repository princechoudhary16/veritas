"""Veritas live UI — policy-driven verification, streamed over SSE.

Pick a Policy Pack, run it, and watch the tiered DAG verify each artifact in
real time: copy and image stream in, SAM 3.1 boxes are drawn over the image
(red = rejected, green = verified), short-circuited tiers are shown as skipped,
and the final cryptographic receipt is downloadable.

    pip install -r requirements.txt
    set -a; source .env; set +a
    python app.py          # http://127.0.0.1:5050

Modes: live (real Meta Model API) | replay (last saved run, no API spend).
"""

import asyncio
import glob
import json
import os
import queue
import threading
import time

from flask import Flask, Response, request, send_from_directory

from veritas.config import PARTNER_MODEL, load_api_key, make_partner_provider
from veritas.engine import run_engine
from veritas.meta_client import MetaClient
from veritas.policy import load_policy

HERE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)


def _policy_files():
    return sorted(glob.glob(os.path.join(HERE, "policies", "*.yaml")))


def _policy_path(name):
    for p in _policy_files():
        try:
            if load_policy(p).name == name:
                return p
        except Exception:
            continue
    return None


@app.route("/out/<path:filename>")
def out_file(filename):
    return send_from_directory(os.path.join(HERE, "out"), filename)


@app.route("/policies")
def policies():
    items = []
    for p in _policy_files():
        try:
            pol = load_policy(p)
            items.append({"name": pol.name, "theme": pol.theme,
                          "description": " ".join(pol.description.split())})
        except Exception:
            continue
    return Response(json.dumps(items), mimetype="application/json")


@app.route("/capabilities")
def capabilities():
    return Response(json.dumps({"partner": bool(os.environ.get("BASETEN_API_KEY")),
                                "partner_model": PARTNER_MODEL}), mimetype="application/json")


@app.route("/api/export-dpo-dataset")
def export_dpo():
    from veritas.dpo import build_dpo_pairs
    pairs = build_dpo_pairs(os.path.join(HERE, "runs"), os.path.join(HERE, "policies"))
    body = "\n".join(json.dumps(p) for p in pairs)
    return Response(body, mimetype="application/x-ndjson",
                    headers={"Content-Disposition": "attachment; filename=veritas_dpo.jsonl"})


@app.route("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html")


def _sse(q):
    while True:
        item = q.get()
        if item is None:
            break
        yield f"data: {json.dumps(item)}\n\n"


@app.route("/stream")
def stream():
    mode = request.args.get("mode", "live")
    policy_name = request.args.get("policy", "")
    partner = request.args.get("partner", "") in ("1", "true", "on", "yes")
    surgical = request.args.get("surgical", "") in ("1", "true", "on", "yes")
    q = queue.Queue()
    if mode == "replay":
        threading.Thread(target=_replay, args=(q, policy_name), daemon=True).start()
    else:
        threading.Thread(target=_live, args=(q, policy_name, partner, surgical), daemon=True).start()
    return Response(_sse(q), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _live(q, policy_name, partner=False, surgical=False):
    try:
        path = _policy_path(policy_name)
        if not path:
            q.put({"kind": "error", "payload": {"message": f"policy '{policy_name}' not found"}})
            return
        policy = load_policy(path)
        provider = MetaClient(load_api_key())
        critic_provider = make_partner_provider() if partner else None
        if partner and critic_provider is None:
            q.put({"kind": "error",
                   "payload": {"message": "Partner routing requested but BASETEN_API_KEY is not configured."}})
            return
        routed = f"{critic_provider.label}/{critic_provider.model}" if critic_provider else None
        surgical_repair = surgical or policy.image_repair == "edit"
        run_input = {"brief": policy.brief, "source_truth": policy.source_truth,
                     "target_object": policy.target_object, "scene_prompt": policy.scene_prompt}
        q.put({"kind": "start", "spend": 0.0,
               "payload": {"policy": policy.name, "theme": policy.theme, "partner": routed}})

        def on_event(kind, n, payload):
            ev = {"kind": kind, "n": n, "spend": round(provider.usage.spend_usd, 4)}
            if kind == "generated":
                img = payload.get("image", "")
                ev["payload"] = {"copy": payload.get("copy", ""),
                                 "image_url": ("/" + img) if img else ""}
            else:
                ev["payload"] = payload
            q.put(ev)

        result = asyncio.run(run_engine(policy, run_input, provider,
                                        critic_provider=critic_provider,
                                        surgical_repair=surgical_repair, on_event=on_event))

        os.makedirs(os.path.join(HERE, "runs"), exist_ok=True)
        with open(os.path.join(HERE, "runs", f"engine_{policy.name}_{int(time.time())}.json"), "w") as f:
            json.dump({"policy": policy.name, "passed": result.passed,
                       "stopped_reason": result.stopped_reason, "spend_usd": result.spend_usd,
                       "iterations": result.iterations, "receipt": result.receipt}, f)
    except Exception as e:
        q.put({"kind": "error", "payload": {"message": str(e)}})
    finally:
        q.put(None)


def _replay(q, policy_name):
    files = sorted(glob.glob(os.path.join(HERE, "runs", "engine_*.json")))
    if policy_name:
        matched = [f for f in files if f"engine_{policy_name}_" in os.path.basename(f)]
        files = matched or files
    if not files:
        q.put({"kind": "error", "payload": {"message": "No saved runs to replay. Run a live verification first."}})
        q.put(None)
        return
    data = json.load(open(files[-1]))
    q.put({"kind": "start", "spend": 0.0, "payload": {"policy": data["policy"], "theme": "replay"}})
    for it in data["iterations"]:
        art = it["artifacts"] if isinstance(it["artifacts"], dict) else {}
        img = art.get("image", "")
        q.put({"kind": "generated", "n": it["n"], "spend": it["spend_after"],
               "payload": {"copy": art.get("copy", ""), "image_url": ("/" + img) if img else ""}})
        time.sleep(0.8)
        q.put({"kind": "verified", "n": it["n"], "spend": it["spend_after"],
               "payload": {"verdicts": it["verdicts"], "skipped": it["skipped"]}})
        time.sleep(1.0)
    q.put({"kind": "done", "spend": data["spend_usd"], "payload": {
        "passed": data["passed"], "stopped": data["stopped_reason"],
        "iterations": len(data["iterations"]), "spend": data["spend_usd"],
        "receipt": data["receipt"]}})
    q.put(None)


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Veritas</title>
<style>
  :root{--bg:#0e1013;--card:#171a21;--card2:#1f232c;--line:#2a2f3a;
    --text:#e8eaee;--muted:#9aa3b2;--accent:#2dd4bf;--pass:#34d399;--fail:#f87171;--pend:#6b7280;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);
    font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;line-height:1.5}
  .wrap{max-width:1040px;margin:0 auto;padding:28px 20px 90px}
  h1{margin:0;font-size:26px;font-weight:600}
  .tag{color:var(--muted);margin-top:6px;max-width:760px;font-size:14px}
  .controls{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin:20px 0;display:grid;gap:12px}
  label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
  select{width:100%;background:var(--bg);color:var(--text);border:1px solid var(--line);border-radius:10px;padding:10px 12px;font-size:14px}
  .desc{color:var(--muted);font-size:13px;min-height:18px}
  .row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
  button{border:0;border-radius:10px;padding:10px 18px;font-size:14px;font-weight:600;cursor:pointer}
  .btn-run{background:var(--accent);color:#06221d}
  .btn-replay,.btn-dl{background:var(--card2);color:var(--text);border:1px solid var(--line)}
  button:disabled{opacity:.5;cursor:default}
  .switch{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--muted);cursor:pointer;user-select:none}
  .pill{margin-left:auto;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  .chip{background:var(--card2);border:1px solid var(--line);border-radius:999px;padding:6px 12px;font-size:13px;color:var(--muted)}
  .chip b{color:var(--text)}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;margin:16px 0;opacity:0;transform:translateY(8px);transition:opacity .35s,transform .35s}
  .card.in{opacity:1;transform:none}
  .card-head{display:flex;align-items:center;gap:10px;font-weight:600;margin-bottom:12px}
  .vtag{font-size:12px;font-weight:600;padding:3px 10px;border-radius:999px;border:1px solid var(--line);color:var(--muted)}
  .vtag.pass{color:var(--pass);border-color:#1f6b53;background:#0f2a22}
  .vtag.fail{color:var(--fail);border-color:#7a2f2f;background:#2a1414}
  .opbadge{font-size:12px;color:var(--accent)}
  .body{display:grid;grid-template-columns:260px 1fr;gap:16px}
  @media(max-width:720px){.body{grid-template-columns:1fr}}
  .shot-wrap{position:relative;width:100%;aspect-ratio:1}
  .shot{width:100%;height:100%;object-fit:cover;background:var(--card2);border:1px solid var(--line);border-radius:10px;display:block}
  .overlay{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
  .copy{background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:12px;white-space:pre-wrap;font-size:14px;margin:0 0 12px}
  .check{display:grid;grid-template-columns:14px 1fr auto;gap:10px;align-items:start;padding:9px 0;border-top:1px solid var(--line)}
  .dot{width:11px;height:11px;border-radius:50%;margin-top:4px;background:var(--pend)}
  .dot.pass{background:var(--pass)}.dot.fail{background:var(--fail)}.dot.skip{background:var(--pend)}
  .clabel{font-weight:600;font-size:14px}
  .creason{color:var(--muted);font-size:13px;margin-top:2px}
  .cfix{color:var(--fail);font-size:13px;margin-top:3px}
  .cscore{color:var(--muted);font-size:12px;font-variant-numeric:tabular-nums}
  .banner{display:none;margin:20px 0;padding:16px 20px;border-radius:14px;font-weight:600;align-items:center;gap:14px}
  .banner.pass{display:flex;background:#0f2a22;border:1px solid #1f6b53;color:var(--pass)}
  .banner.fail{display:flex;background:#2a1414;border:1px solid #7a2f2f;color:var(--fail)}
  .banner .btn-dl{margin-left:auto}
</style>
</head>
<body>
<div class="wrap">
  <h1>Veritas</h1>
  <div class="tag">A declarative verification engine for multimodal AI. Pick a Policy Pack and watch the
    tiered DAG verify every artifact against its source of truth, catching and repairing failures until it
    provably passes.</div>

  <div class="controls">
    <div><label>Policy Pack</label>
      <select id="policy" onchange="showDesc()"></select>
      <div class="desc" id="desc"></div></div>
    <div class="row">
      <button class="btn-run" id="runBtn" onclick="start('live')">Run verification</button>
      <button class="btn-replay" id="replayBtn" onclick="start('replay')">Replay last run</button>
      <label class="switch" id="partnerLabel">
        <input type="checkbox" id="partner"> burst critics to Baseten
      </label>
      <label class="switch" title="Repair images by editing the flagged image in place">
        <input type="checkbox" id="surgical"> surgical repair
      </label>
      <div class="pill">
        <span class="chip" id="partner-chip" style="display:none"></span>
        <span class="chip">spend <b id="spend">$0.0000</b></span>
        <span class="chip" id="status">idle</span>
      </div>
    </div>
  </div>

  <div id="banner" class="banner"></div>
  <div id="board"></div>
</div>

<script>
let es=null, POLICIES=[], RECEIPT=null;

async function loadPolicies(){
  try{
    POLICIES=await (await fetch('/policies')).json();
    const sel=document.getElementById('policy');
    sel.innerHTML='';
    for(const p of POLICIES){
      const o=document.createElement('option');
      o.value=p.name; o.textContent=p.name+'  ·  '+p.theme; sel.appendChild(o);
    }
    showDesc();
  }catch(e){ document.getElementById('desc').textContent='Could not load policies.'; }
}
async function loadCapabilities(){
  try{
    const c=await (await fetch('/capabilities')).json();
    const cb=document.getElementById('partner'), lab=document.getElementById('partnerLabel');
    if(!c.partner){ cb.checked=false; cb.disabled=true; lab.style.opacity=.5; lab.title='Set BASETEN_API_KEY to enable'; }
    else { lab.title='Run the text critics on '+(c.partner_model||'the partner'); }
  }catch(e){}
}
function showDesc(){
  const name=document.getElementById('policy').value;
  const p=POLICIES.find(x=>x.name===name);
  document.getElementById('desc').textContent=p?p.description:'';
}
function setStatus(t){document.getElementById('status').textContent=t;}
function setSpend(s){if(s!=null)document.getElementById('spend').textContent='$'+Number(s).toFixed(4);}
function busy(b){document.getElementById('runBtn').disabled=b;document.getElementById('replayBtn').disabled=b;}

function start(mode){
  if(es)es.close();
  document.getElementById('board').innerHTML='';
  document.getElementById('banner').className='banner';
  RECEIPT=null; setSpend(0); busy(true);
  setStatus(mode==='replay'?'replaying…':'running live…');
  const policy=encodeURIComponent(document.getElementById('policy').value);
  const partner=(mode==='live' && document.getElementById('partner').checked) ? '&partner=1' : '';
  const surgical=(mode==='live' && document.getElementById('surgical').checked) ? '&surgical=1' : '';
  es=new EventSource('/stream?mode='+mode+'&policy='+policy+partner+surgical);
  es.onmessage=e=>handle(JSON.parse(e.data));
  es.onerror=()=>{if(es){es.close();es=null;}busy(false);};
}

function card(n){
  let el=document.getElementById('iter-'+n);
  if(el)return el;
  el=document.createElement('div');el.className='card';el.id='iter-'+n;
  el.innerHTML='<div class="card-head">Iteration '+n+
    ' <span class="vtag" id="vtag-'+n+'">verifying…</span>'+
    ' <span class="opbadge" id="op-'+n+'"></span></div>'+
    '<div class="body"><div class="shot-wrap"><img class="shot" id="shot-'+n+'" alt="generated image">'+
    '<svg class="overlay" id="ovl-'+n+'" preserveAspectRatio="none"></svg></div>'+
    '<div><pre class="copy" id="copy-'+n+'" style="display:none"></pre>'+
    '<div class="checks" id="checks-'+n+'"></div></div></div>';
  document.getElementById('board').appendChild(el);
  requestAnimationFrame(()=>el.classList.add('in'));
  return el;
}

function checkRow(check, cls, score, reason, fix){
  const r=document.createElement('div');r.className='check';
  r.innerHTML='<span class="dot '+cls+'"></span>'+
    '<div><div class="clabel">'+check+'</div><div class="creason">'+(reason||'')+'</div>'+
    (fix?'<div class="cfix">fix → '+fix+'</div>':'')+'</div>'+
    '<span class="cscore">'+(score==null?'':Number(score).toFixed(2))+'</span>';
  return r;
}

function drawOverlay(el, verdicts){
  const svg=el.querySelector('.overlay'); let dims=null; const boxes=[];
  for(const v of verdicts){
    const d=v.data;
    if(d&&d.image&&d.detections&&d.detections.length){
      dims=d.image;
      for(const b of d.detections) boxes.push({b, pass:v.passed});
    }
  }
  if(!dims){ svg.innerHTML=''; return; }
  svg.setAttribute('viewBox','0 0 '+dims.w+' '+dims.h);
  const sw=Math.max(3, Math.round(dims.w*0.006));
  let s='';
  for(const o of boxes){
    const b=o.b, col=o.pass?'#34d399':'#f87171';
    s+='<rect x="'+b.x1+'" y="'+b.y1+'" width="'+(b.x2-b.x1)+'" height="'+(b.y2-b.y1)+
       '" fill="none" stroke="'+col+'" stroke-width="'+sw+'"/>';
  }
  svg.innerHTML=s;
}

function downloadReceipt(){
  if(!RECEIPT)return;
  const blob=new Blob([JSON.stringify(RECEIPT,null,2)],{type:'application/json'});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);
  a.download='veritas.lock.json';a.click();
}

function handle(ev){
  setSpend(ev.spend);
  if(ev.kind==='start'){
    const chip=document.getElementById('partner-chip');
    if(ev.payload && ev.payload.partner){ chip.style.display=''; chip.innerHTML='critics → <b>'+ev.payload.partner+'</b>'; }
    else { chip.style.display='none'; }
    return;
  }
  if(ev.kind==='generated'){
    const el=card(ev.n);
    const img=document.getElementById('shot-'+ev.n);
    if(ev.payload.image_url){ img.src=ev.payload.image_url; }
    else { const w=el.querySelector('.shot-wrap'); if(w)w.style.display='none';
           const b=el.querySelector('.body'); if(b)b.style.gridTemplateColumns='1fr'; }
    const copy=document.getElementById('copy-'+ev.n);
    if(ev.payload.copy){copy.style.display='';copy.textContent=ev.payload.copy;}
    const op=document.getElementById('op-'+ev.n);
    if(op && ev.payload.image_op==='edited'){ op.textContent='surgically edited'; }
  }else if(ev.kind==='verified'){
    const el=card(ev.n);
    const cont=el.querySelector('.checks');cont.innerHTML='';
    let allPass=true;
    for(const v of ev.payload.verdicts){
      if(!v.passed)allPass=false;
      cont.appendChild(checkRow(v.check, v.passed?'pass':'fail', v.score, v.reason, v.passed?'':v.fix_hint));
    }
    for(const name of (ev.payload.skipped||[])){
      cont.appendChild(checkRow(name,'skip',null,'skipped — short-circuited by an earlier tier',''));
    }
    drawOverlay(el, ev.payload.verdicts);
    const tag=document.getElementById('vtag-'+ev.n);
    const ok=allPass&&(!ev.payload.skipped||ev.payload.skipped.length===0);
    tag.textContent=ok?'all checks pass':'rejected — fixing';
    tag.className='vtag '+(ok?'pass':'fail');
  }else if(ev.kind==='done'){
    RECEIPT=ev.payload.receipt||null;
    const b=document.getElementById('banner');
    b.className='banner '+(ev.payload.passed?'pass':'fail');
    const econ=RECEIPT?RECEIPT.economics:null;
    const sc=econ?Number(econ.credits_saved_by_short_circuit_usd).toFixed(4):'0';
    const ca=econ?Number(econ.credits_saved_by_cache_usd).toFixed(4):'0';
    const routed=econ&&econ.critics_routed_to;
    const ptxt=routed?' · critics on '+routed+' ($'+Number(econ.partner_spend_usd).toFixed(4)+')':'';
    b.innerHTML='<span>'+(ev.payload.passed?'✓ Verified in ':'✗ Stopped after ')+ev.payload.iterations+
      ' iteration(s) · Meta spend $'+Number(ev.payload.spend).toFixed(4)+
      ' · saved $'+sc+' short-circuit + $'+ca+' cache'+ptxt+'</span>'+
      (RECEIPT?'<button class="btn-dl" onclick="downloadReceipt()">Download veritas.lock.json</button>':'');
    setStatus('done');busy(false);if(es){es.close();es=null;}
  }else if(ev.kind==='error'){
    const b=document.getElementById('banner');b.className='banner fail';
    b.textContent='Error: '+ev.payload.message;
    setStatus('error');busy(false);if(es){es.close();es=null;}
  }
}

loadPolicies();
loadCapabilities();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5050"))
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)

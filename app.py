"""Veritas live UI — watch the campaign loop catch and fix artifacts in real time.

A small Flask app that runs the campaign loop in a background thread and streams
every event (generate -> verify -> fix) to the browser over Server-Sent Events.

    pip install -r requirements.txt
    set -a; source .env; set +a
    python app.py          # then open http://127.0.0.1:5050

Modes:
  live    - runs a real campaign on the Meta Model API (spends credits)
  replay  - replays the most recent saved run from runs/ (no API calls, free)
"""

import glob
import json
import os
import queue
import threading
import time

from flask import Flask, Response, request, send_from_directory

from veritas.config import load_api_key
from veritas.meta_client import MetaClient
from veritas.orchestrator import run_campaign_loop, write_ledger

HERE = os.path.dirname(os.path.abspath(__file__))

SOURCE_TRUTH = (
    "Product: HydroPeak water bottle\n"
    "Material: stainless steel\n"
    "Capacity: 750 ml\n"
    "Keeps drinks cold for 24 hours\n"
    "Dishwasher safe\n"
    "Colors: slate grey, forest green\n"
    "Price: $29\n"
)
TARGET_OBJECT = "water bottle"
BRAND_RULES = (
    "Tone: confident, premium, concise. At most two sentences of body copy. "
    "Banned words: cheap, guarantee, #1, best ever. No unverified superlatives."
)
DEFAULT_BRIEF = (
    "Create a premium, confident ad for the HydroPeak water bottle aimed at "
    "serious outdoor enthusiasts."
)
DEFAULT_SCENE = "an alpine hiking trail at golden hour with dramatic mountains"

app = Flask(__name__)


@app.route("/out/<path:filename>")
def out_file(filename):
    return send_from_directory(os.path.join(HERE, "out"), filename)


@app.route("/")
def index():
    return Response(INDEX_HTML, mimetype="text/html")


def _sse(q: "queue.Queue") -> "object":
    while True:
        item = q.get()
        if item is None:
            break
        yield f"data: {json.dumps(item)}\n\n"


@app.route("/stream")
def stream():
    mode = request.args.get("mode", "live")
    brief = request.args.get("brief", DEFAULT_BRIEF)
    scene = request.args.get("scene", DEFAULT_SCENE)
    q: "queue.Queue" = queue.Queue()
    target = _replay if mode == "replay" else _live
    args = (q,) if mode == "replay" else (q, brief, scene)
    threading.Thread(target=target, args=args, daemon=True).start()
    return Response(
        _sse(q),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _live(q, brief, scene):
    try:
        client = MetaClient(load_api_key())
        q.put({"kind": "start", "n": 0, "spend": 0.0,
               "payload": {"brief": brief, "scene": scene}})

        def on_event(kind, n, payload):
            ev = {"kind": kind, "n": n, "spend": round(client.usage.spend_usd, 4)}
            if kind == "verified":
                ev["payload"] = [v.to_dict() for v in payload]
            elif kind == "generated":
                img = payload.get("image", "")
                ev["payload"] = {"copy": payload.get("copy", ""),
                                 "image_url": ("/" + img) if img else ""}
            else:
                ev["payload"] = payload
            q.put(ev)

        result = run_campaign_loop(
            client, brief, SOURCE_TRUTH, TARGET_OBJECT, BRAND_RULES,
            scene_prompt=scene, on_event=on_event, max_iters=6,
        )
        write_ledger(result)
        q.put({"kind": "done", "n": 0, "spend": result.spend_usd, "payload": {
            "passed": result.passed, "iterations": len(result.iterations),
            "stopped": result.stopped_reason, "final": result.final_artifact}})
    except Exception as e:  # surface to the UI rather than dying silently
        q.put({"kind": "error", "n": 0, "spend": 0.0, "payload": {"message": str(e)}})
    finally:
        q.put(None)


def _replay(q):
    files = sorted(glob.glob(os.path.join(HERE, "runs", "*.json")))
    if not files:
        q.put({"kind": "error", "n": 0, "spend": 0.0,
               "payload": {"message": "No saved runs to replay. Run a live campaign first."}})
        q.put(None)
        return
    data = json.load(open(files[-1]))
    q.put({"kind": "start", "n": 0, "spend": 0.0,
           "payload": {"brief": "Replay of the most recent saved run", "scene": ""}})
    for it in data["iterations"]:
        art = it["artifact"]
        if isinstance(art, dict):
            copy, img = art.get("copy", ""), art.get("image", "")
        else:
            copy, img = str(art), ""
        q.put({"kind": "generated", "n": it["n"], "spend": it["spend_after"],
               "payload": {"copy": copy, "image_url": ("/" + img) if img else ""}})
        time.sleep(0.9)
        q.put({"kind": "verified", "n": it["n"], "spend": it["spend_after"],
               "payload": it["verdicts"]})
        time.sleep(1.1)
    q.put({"kind": "done", "n": 0, "spend": data["spend_usd"], "payload": {
        "passed": data["passed"], "iterations": len(data["iterations"]),
        "stopped": data["stopped_reason"], "final": data["final_artifact"]}})
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
  .wrap{max-width:1040px;margin:0 auto;padding:28px 20px 80px}
  header h1{margin:0;font-size:26px;font-weight:600;letter-spacing:.3px}
  header .tag{color:var(--muted);margin-top:6px;max-width:720px;font-size:14px}
  .controls{background:var(--card);border:1px solid var(--line);border-radius:14px;
    padding:16px;margin:20px 0;display:grid;gap:12px}
  label{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
  textarea,input{width:100%;background:var(--bg);color:var(--text);border:1px solid var(--line);
    border-radius:10px;padding:10px 12px;font-size:14px;font-family:inherit;resize:vertical}
  .row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
  button{border:0;border-radius:10px;padding:10px 18px;font-size:14px;font-weight:600;cursor:pointer}
  .btn-run{background:var(--accent);color:#06221d}
  .btn-replay{background:var(--card2);color:var(--text);border:1px solid var(--line)}
  button:disabled{opacity:.5;cursor:default}
  .pill{margin-left:auto;display:flex;gap:10px;align-items:center}
  .chip{background:var(--card2);border:1px solid var(--line);border-radius:999px;
    padding:6px 12px;font-size:13px;color:var(--muted)}
  .chip b{color:var(--text)}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;
    padding:16px;margin:16px 0;opacity:0;transform:translateY(8px);
    transition:opacity .35s,transform .35s}
  .card.in{opacity:1;transform:none}
  .card-head{display:flex;align-items:center;gap:10px;font-weight:600;margin-bottom:12px}
  .vtag{font-size:12px;font-weight:600;padding:3px 10px;border-radius:999px;border:1px solid var(--line);color:var(--muted)}
  .vtag.pass{color:var(--pass);border-color:#1f6b53;background:#0f2a22}
  .vtag.fail{color:var(--fail);border-color:#7a2f2f;background:#2a1414}
  .body{display:grid;grid-template-columns:260px 1fr;gap:16px}
  @media(max-width:720px){.body{grid-template-columns:1fr}}
  .shot{width:100%;aspect-ratio:1;object-fit:cover;background:var(--card2);
    border:1px solid var(--line);border-radius:10px}
  .copy{background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:12px;
    white-space:pre-wrap;font-size:14px;margin:0 0 12px}
  .check{display:grid;grid-template-columns:14px 1fr auto;gap:10px;align-items:start;
    padding:9px 0;border-top:1px solid var(--line)}
  .dot{width:11px;height:11px;border-radius:50%;margin-top:4px;background:var(--pend)}
  .dot.pass{background:var(--pass)}.dot.fail{background:var(--fail)}
  .dot.pend{animation:pulse 1s infinite}
  @keyframes pulse{50%{opacity:.3}}
  .clabel{font-weight:600;font-size:14px}
  .creason{color:var(--muted);font-size:13px;margin-top:2px}
  .cfix{color:var(--fail);font-size:13px;margin-top:3px}
  .cscore{color:var(--muted);font-size:12px;font-variant-numeric:tabular-nums}
  .banner{display:none;margin:20px 0;padding:16px 20px;border-radius:14px;font-weight:600}
  .banner.pass{display:block;background:#0f2a22;border:1px solid #1f6b53;color:var(--pass)}
  .banner.fail{display:block;background:#2a1414;border:1px solid #7a2f2f;color:var(--fail)}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Veritas</h1>
    <div class="tag">An agent that treats every generative output as a claim to be disproven.
      It generates with Meta's models, then cross-checks each artifact against the source of truth
      in a closed loop until it provably passes.</div>
  </header>

  <div class="controls">
    <div><label>Brief</label>
      <textarea id="brief" rows="2">Create a premium, confident ad for the HydroPeak water bottle aimed at serious outdoor enthusiasts.</textarea></div>
    <div><label>Image scene prompt</label>
      <input id="scene" value="an alpine hiking trail at golden hour with dramatic mountains"></div>
    <div class="row">
      <button class="btn-run" id="runBtn" onclick="start('live')">Run verified campaign</button>
      <button class="btn-replay" id="replayBtn" onclick="start('replay')">Replay last run</button>
      <div class="pill">
        <span class="chip">critics: <b>claim · brand · grounding · consistency</b></span>
        <span class="chip">spend <b id="spend">$0.0000</b></span>
        <span class="chip" id="status">idle</span>
      </div>
    </div>
  </div>

  <div id="banner" class="banner"></div>
  <div id="board"></div>
</div>

<script>
const LABEL={claim_support:"Claim support",brand:"Brand",
  grounding:"Grounding · SAM 3.1",consistency:"Consistency · vision"};
const ORDER=["claim_support","brand","grounding","consistency"];
let es=null;

function setStatus(t){document.getElementById('status').textContent=t;}
function setSpend(s){if(s!=null)document.getElementById('spend').textContent='$'+Number(s).toFixed(4);}
function busy(b){document.getElementById('runBtn').disabled=b;document.getElementById('replayBtn').disabled=b;}

function start(mode){
  if(es)es.close();
  document.getElementById('board').innerHTML='';
  const banner=document.getElementById('banner');banner.className='banner';
  setSpend(0);busy(true);
  setStatus(mode==='replay'?'replaying…':'running live…');
  const brief=encodeURIComponent(document.getElementById('brief').value);
  const scene=encodeURIComponent(document.getElementById('scene').value);
  es=new EventSource('/stream?mode='+mode+'&brief='+brief+'&scene='+scene);
  es.onmessage=e=>handle(JSON.parse(e.data));
  es.onerror=()=>{if(es){es.close();es=null;}busy(false);};
}

function card(n){
  let el=document.getElementById('iter-'+n);
  if(el)return el;
  el=document.createElement('div');el.className='card';el.id='iter-'+n;
  let rows='';
  for(const c of ORDER){
    rows+='<div class="check" data-check="'+c+'">'+
      '<span class="dot pend"></span>'+
      '<div><div class="clabel">'+LABEL[c]+'</div>'+
      '<div class="creason">verifying…</div></div>'+
      '<span class="cscore"></span></div>';
  }
  el.innerHTML='<div class="card-head">Iteration '+n+
    ' <span class="vtag" id="vtag-'+n+'">verifying</span></div>'+
    '<div class="body"><img class="shot" id="shot-'+n+'" alt="generated image">'+
    '<div><pre class="copy" id="copy-'+n+'"></pre><div class="checks">'+rows+'</div></div></div>';
  document.getElementById('board').appendChild(el);
  requestAnimationFrame(()=>el.classList.add('in'));
  return el;
}

function handle(ev){
  setSpend(ev.spend);
  if(ev.kind==='generated'){
    const el=card(ev.n);
    document.getElementById('copy-'+ev.n).textContent=ev.payload.copy||'';
    const img=document.getElementById('shot-'+ev.n);
    if(ev.payload.image_url)img.src=ev.payload.image_url;
  }else if(ev.kind==='verified'){
    const el=card(ev.n);let allPass=true;
    for(const v of ev.payload){
      const row=el.querySelector('.check[data-check="'+v.check+'"]');
      if(!row)continue;
      row.querySelector('.dot').className='dot '+(v.passed?'pass':'fail');
      row.querySelector('.cscore').textContent=Number(v.score).toFixed(2);
      row.querySelector('.creason').textContent=v.reason||'';
      const old=row.querySelector('.cfix');if(old)old.remove();
      if(!v.passed&&v.fix_hint){
        const fix=document.createElement('div');fix.className='cfix';
        fix.textContent='fix → '+v.fix_hint;
        row.children[1].appendChild(fix);
      }
      if(!v.passed)allPass=false;
    }
    const tag=document.getElementById('vtag-'+ev.n);
    tag.textContent=allPass?'all checks pass':'rejected — fixing';
    tag.className='vtag '+(allPass?'pass':'fail');
  }else if(ev.kind==='done'){
    const b=document.getElementById('banner');
    b.className='banner '+(ev.payload.passed?'pass':'fail');
    b.textContent=(ev.payload.passed?'✓ Shipped a verified campaign in ':'✗ Stopped without a verified campaign after ')
      +ev.payload.iterations+' iteration(s) · spend $'+Number(ev.spend).toFixed(4)
      +' · '+ev.payload.stopped;
    setStatus('done');busy(false);if(es){es.close();es=null;}
  }else if(ev.kind==='error'){
    const b=document.getElementById('banner');b.className='banner fail';
    b.textContent='Error: '+ev.payload.message;
    setStatus('error');busy(false);if(es){es.close();es=null;}
  }
}
</script>
</body>
</html>
"""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5050"))
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)

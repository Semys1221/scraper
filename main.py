import os
import sys
import threading
import json
import urllib.parse
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
from engine import auto_run
from config import (
    get_supabase,
    GEMINI_API_KEY,
    update_smartlead_sequences,
    create_smartlead_campaign,
)

PORT = int(os.getenv("PORT", 8001))


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Scraper Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0f172a;color:#e2e8f0;padding:24px;max-width:900px;margin:0 auto}
h1{font-size:24px;font-weight:600;margin-bottom:24px;color:#f8fafc}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:24px}
.card{background:#1e293b;border-radius:12px;padding:20px;border:1px solid #334155}
.card .label{font-size:13px;color:#94a3b8;margin-bottom:4px}
.card .value{font-size:32px;font-weight:700}
.card .value.green{color:#22c55e}.card .value.blue{color:#3b82f6}.card .value.yellow{color:#eab308}.card .value.purple{color:#a855f7}.card .value.orange{color:#f97316}
.niche-table{width:100%;border-collapse:collapse;margin-top:12px}
.niche-table th{text-align:left;padding:8px 12px;font-size:12px;color:#94a3b8;border-bottom:1px solid #334155}
.niche-table td{padding:8px 12px;font-size:14px;border-bottom:1px solid #1e293b}
.bar{height:8px;background:#334155;border-radius:4px;overflow:hidden;min-width:80px}
.bar-fill{height:100%;border-radius:4px;transition:width .5s}
.footer{text-align:center;font-size:12px;color:#64748b;margin-top:24px}
.nav{display:flex;gap:16px;margin-bottom:24px}
.nav a{color:#3b82f6;text-decoration:none;padding:8px 16px;border-radius:8px;border:1px solid #334155;font-size:14px}
.nav a:hover{background:#1e293b}
</style>
</head>
<body>

<div class="nav">
  <a href="/dashboard">Stats</a>
  <a href="/dashboard/templates">Templates</a>
</div>

<h1>Scraper Dashboard</h1>

<div class="grid" id="campaigns">
  <div class="card"><div class="label">Campagnes faites</div><div class="value green" id="done">-</div></div>
  <div class="card"><div class="label">En cours</div><div class="value blue" id="scraping">-</div></div>
  <div class="card"><div class="label">En attente</div><div class="value yellow" id="pending">-</div></div>
</div>

<div class="grid" id="leads">
  <div class="card"><div class="label">Leads bruts</div><div class="value orange" id="raw">-</div></div>
  <div class="card"><div class="label">Nettoyés</div><div class="value purple" id="cleaned">-</div></div>
  <div class="card"><div class="label">Smartlead</div><div class="value green" id="smartlead">-</div></div>
</div>

<div class="card">
  <div style="font-size:13px;color:#94a3b8;margin-bottom:12px">Leads par niche</div>
  <table class="niche-table">
    <thead><tr><th>Niche</th><th>Total</th><th>Progression</th></tr></thead>
    <tbody id="niche-rows"></tbody>
  </table>
</div>

<div class="footer" id="updated">Dernière mise à jour: -</div>

<script>
const MAX = 20000;
async function refresh(){
  try{
    const r = await fetch('/api/stats');
    const d = await r.json();
    document.getElementById('done').textContent = d.campaigns.done;
    document.getElementById('scraping').textContent = d.campaigns.scraping;
    document.getElementById('pending').textContent = d.campaigns.pending;
    document.getElementById('raw').textContent = d.leads.raw;
    document.getElementById('cleaned').textContent = d.leads.cleaned;
    document.getElementById('smartlead').textContent = d.leads.smartlead;
    const tbody = document.getElementById('niche-rows');
    tbody.innerHTML = '';
    for(const n of d.by_niche){
      const pct = Math.min(100, (n.total / MAX * 100));
      const color = n.total >= MAX ? '#22c55e' : '#3b82f6';
      tbody.innerHTML += '<tr><td>' + n.niche + '</td><td>' + n.total + '</td><td><div class="bar"><div class="bar-fill" style="width:' + pct + '%;background:' + color + '"></div></div></td></tr>';
    }
    document.getElementById('updated').textContent = 'Dernière mise à jour: ' + new Date().toLocaleTimeString();
  }catch(e){document.getElementById('updated').textContent = 'Erreur: '+e.message}
}
refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>"""


TEMPLATES_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Templates — Scraper Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0f172a;color:#e2e8f0;padding:24px;max-width:1000px;margin:0 auto}
h1{font-size:24px;font-weight:600;margin-bottom:16px;color:#f8fafc}
.nav{display:flex;gap:16px;margin-bottom:24px}
.nav a{color:#3b82f6;text-decoration:none;padding:8px 16px;border-radius:8px;border:1px solid #334155;font-size:14px}
.nav a:hover{background:#1e293b}
.card{background:#1e293b;border-radius:12px;padding:20px;border:1px solid #334155;margin-bottom:16px}
.card h2{font-size:16px;color:#f8fafc;margin-bottom:12px}
label{display:block;font-size:13px;color:#94a3b8;margin-bottom:4px;margin-top:12px}
input,textarea,select{width:100%;padding:10px 12px;border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;font-size:14px;font-family:inherit}
textarea{min-height:80px;resize:vertical}
.btn{padding:10px 20px;border-radius:8px;border:none;font-size:14px;font-weight:500;cursor:pointer;margin-top:12px}
.btn-primary{background:#3b82f6;color:#fff}
.btn-primary:hover{background:#2563eb}
.btn-green{background:#22c55e;color:#fff}
.btn-green:hover{background:#16a34a}
.btn-gemini{background:#8b5cf6;color:#fff;padding:6px 12px;font-size:12px;margin-left:8px}
.btn-gemini:hover{background:#7c3aed}
.btn-sm{padding:6px 12px;font-size:12px;margin:0}
.flex{display:flex;align-items:center;gap:8px}
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:700px){.grid-2{grid-template-columns:1fr}}
.vars-box{background:#0f172a;border-radius:8px;padding:12px;font-size:13px;color:#94a3b8;margin-top:8px}
.vars-box code{color:#22c55e}
.preview-box{background:#0f172a;border-radius:8px;padding:16px;margin-top:8px;font-size:14px;line-height:1.6;white-space:pre-wrap}
.toast{position:fixed;bottom:24px;right:24px;padding:12px 20px;border-radius:8px;z-index:100;display:none}
.toast.success{background:#22c55e;color:#fff;display:block}
.toast.error{background:#ef4444;color:#fff;display:block}
.status-badge{display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:500}
.status-badge.active{background:#22c55e;color:#fff}
.status-badge.inactive{background:#64748b;color:#fff}
</style>
</head>
<body>

<div class="nav">
  <a href="/dashboard">Stats</a>
  <a href="/dashboard/templates">Templates</a>
</div>

<h1>Templates Email par Niche</h1>

<div id="toast" class="toast"></div>

<div class="grid-2">
  <div class="card">
    <h2>Variables</h2>
    <div id="niche-select-container"></div>

    <div id="vars-form">
      <label>Objectif ({{objective}})</label>
      <div class="flex">
        <input id="input-objective" placeholder="ex: réduire leur imposition">
        <button class="btn btn-gemini btn-gemini-sm" onclick="suggest('objective')">🤖</button>
      </div>

      <label>Délai ({{timeframe}})</label>
      <div class="flex">
        <input id="input-timeframe" placeholder="ex: en 3 mois">
        <button class="btn btn-gemini btn-gemini-sm" onclick="suggest('timeframe')">🤖</button>
      </div>

      <label>Contrainte ({{constraint}})</label>
      <div class="flex">
        <input id="input-constraint" placeholder="ex: sans changer de banque">
        <button class="btn btn-gemini btn-gemini-sm" onclick="suggest('constraint')">🤖</button>
      </div>

      <label>Introduction ({{custom_intro}})</label>
      <div class="flex">
        <input id="input-custom_intro" placeholder="ex: vous conseiller sur votre patrimoine">
        <button class="btn btn-gemini btn-gemini-sm" onclick="suggest('custom_intro')">🤖</button>
      </div>

      <button class="btn btn-primary" onclick="saveVars()">💾 Sauvegarder</button>
      <button class="btn btn-green" onclick="syncSmartlead()">☁️ Sync Smartlead</button>
    </div>

    <div class="vars-box" style="margin-top:16px">
      <strong>Variables disponibles :</strong><br>
      <code>{{first_name}}</code> <code>{{phone}}</code> <code>{{city}}</code><br>
      <code>{{objective}}</code> <code>{{timeframe}}</code> <code>{{constraint}}</code> <code>{{custom_intro}}</code>
    </div>
  </div>

  <div class="card">
    <h2>Aperçu — Email 1 <span id="variant-label" style="font-size:13px;color:#94a3b8"></span></h2>
    <div style="margin-bottom:8px">
      <button class="btn btn-sm btn-gemini" onclick="showPreview(0)">Variante A</button>
      <button class="btn btn-sm btn-gemini" onclick="showPreview(1)">Variante B</button>
      <button class="btn btn-sm btn-gemini" onclick="showPreview(2)">Variante C</button>
    </div>
    <div id="preview" class="preview-box">Sélectionne une niche et une variante</div>
  </div>
</div>

<div class="card">
  <h2>Statut Smartlead</h2>
  <div id="smartlead-status">Chargement...</div>
</div>

<script>
let currentNiche = '';
let sequences = {};
let nicheVars = {};
let variantsData = [];

async function load() {
  const r = await fetch('/api/templates');
  const d = await r.json();
  sequences = d.sequences;
  nicheVars = d.vars;

  const container = document.getElementById('niche-select-container');
  const niches = Object.keys(sequences);
  container.innerHTML = '<label>Niche</label><select id="niche-select" onchange="selectNiche(this.value)">' +
    '<option value="">Sélectionne une niche</option>' +
    niches.map(n => '<option value="' + n + '">' + n + '</option>').join('') +
    '</select>';

  updateSmartleadStatus(d.smartlead);
}

function selectNiche(niche) {
  currentNiche = niche;
  if (!niche) return;
  const v = nicheVars[niche] || {};
  document.getElementById('input-objective').value = v.objective || '';
  document.getElementById('input-timeframe').value = v.timeframe || '';
  document.getElementById('input-constraint').value = v.constraint_ || '';
  document.getElementById('input-custom_intro').value = v.custom_intro || '';
  variantsData = sequences[niche] || [];
  showPreview(0);
}

function fillVars(text) {
  if (!text) return '';
  const v = nicheVars[currentNiche] || {};
  return text
    .replace(/\\{\\{first_name\\}\\}/g, 'Jean')
    .replace(/\\{\\{phone\\}\\}/g, '06 12 34 56 78')
    .replace(/\\{\\{city\\}\\}/g, currentNiche ? (nicheVars[currentNiche]?.city || 'Paris') : 'Paris')
    .replace(/\\{\\{objective\\}\\}/g, v.objective || '[objectif]')
    .replace(/\\{\\{timeframe\\}\\}/g, v.timeframe || '[délai]')
    .replace(/\\{\\{constraint\\}\\}/g, v.constraint_ || '[contrainte]')
    .replace(/\\{\\{custom_intro\\}\\}/g, v.custom_intro || '[intro]');
}

function showPreview(idx) {
  if (!variantsData.length) return;
  const v = variantsData[idx];
  if (!v) return;
  document.getElementById('variant-label').textContent = '— Variante ' + v.name;
  const steps = v.steps || [];
  let html = '';
  for (const s of steps) {
    html += '<strong>Jour ' + s.day + '</strong>';
    if (s.subject) html += '<br><em>Sujet:</em> ' + fillVars(s.subject);
    html += '<br><br>' + fillVars(s.body) + '<br><br>';
  }
  document.getElementById('preview').innerHTML = html || 'Aucune étape';
}

async function saveVars() {
  if (!currentNiche) return toast('Sélectionne une niche', 'error');
  const body = {
    niche: currentNiche,
    objective: document.getElementById('input-objective').value,
    timeframe: document.getElementById('input-timeframe').value,
    constraint_: document.getElementById('input-constraint').value,
    custom_intro: document.getElementById('input-custom_intro').value,
  };
  const r = await fetch('/api/templates', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
  const d = await r.json();
  if (r.ok) { toast('✅ Variables sauvegardées', 'success'); load(); }
  else toast('❌ ' + (d.error || 'Erreur'), 'error');
}

async function syncSmartlead() {
  if (!currentNiche) return toast('Sélectionne une niche', 'error');
  const r = await fetch('/api/templates/sync', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({niche: currentNiche}) });
  const d = await r.json();
  if (r.ok) { toast('✅ Synchro Smartlead réussie (campagne #' + d.campaign_id + ')', 'success'); load(); }
  else toast('❌ ' + (d.error || 'Erreur'), 'error');
}

async function suggest(field) {
  if (!currentNiche) return toast('Sélectionne une niche', 'error');
  const r = await fetch('/api/gemini', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({niche: currentNiche, field: field}) });
  const d = await r.json();
  if (r.ok && d.suggestion) {
    document.getElementById('input-' + field).value = d.suggestion;
    toast('🤖 Suggestion appliquée', 'success');
  } else toast('❌ ' + (d.error || 'Erreur Gemini'), 'error');
}

function updateSmartleadStatus(data) {
  const el = document.getElementById('smartlead-status');
  if (!data || !data.length) { el.innerHTML = 'Aucune campagne Smartlead'; return; }
  el.innerHTML = data.map(s =>
    '<div style="margin-bottom:6px"><span class="status-badge ' + (s.campaign_id ? 'active' : 'inactive') + '">' + s.niche + '</span> ID: ' + (s.campaign_id || '—') + '</div>'
  ).join('');
}

function toast(msg, type) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast ' + type;
  setTimeout(() => el.className = 'toast', 3000);
}

load();
</script>
</body>
</html>"""


def _get_json_body(self):
    length = int(self.headers.get("Content-Length", 0))
    if length == 0:
        return {}
    return json.loads(self.rfile.read(length))


def _render_template(text, vars):
    for key, val in vars.items():
        text = text.replace("{{" + key + "}}", str(val))
    return text


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/dashboard" or self.path == "/":
            self._serve_html(DASHBOARD_HTML)
        elif self.path == "/dashboard/templates":
            self._serve_html(TEMPLATES_HTML)
        elif self.path == "/api/stats":
            self._handle_stats()
        elif self.path == "/api/templates":
            self._handle_get_templates()
        elif self.path == "/book":
            self._handle_tracking("book")
        elif self.path == "/testimonial":
            self._handle_tracking("testimonial")
        elif self.path == "/health":
            self._json({"status": "ok"})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/templates":
            self._handle_save_templates()
        elif self.path == "/api/templates/sync":
            self._handle_sync_smartlead()
        elif self.path == "/api/gemini":
            self._handle_gemini()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_tracking(self, link_type):
        redirect_url = "https://calendly.com/syli-conseils/30min" if link_type == "book" else "https://sylkconseils.com"
        action = "réservation" if link_type == "book" else "témoignage"
        title = "Planifier un RDV" if link_type == "book" else "Témoignage"
        webhook = os.getenv("DISCORD_WEBHOOK_URL", "")

        import datetime
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self._serve_html(f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body{{font-family:sans-serif;background:#0f172a;color:#e2e8f0;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
h1{{font-size:24px;font-weight:400}}
</style>
</head>
<body>
<h1>Redirection...</h1>
<script>
fetch('{webhook}',{{
  method:'POST',
  body:JSON.stringify({{content:'[{action}] Clic tracking — {timestamp}'}}),
  headers:{{'Content-Type':'application/json'}}
}}).catch(function(){{}});
window.location.href='{redirect_url}';
</script>
</body>
</html>""")

    def _serve_html(self, html):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def _json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _handle_stats(self):
        try:
            sb = get_supabase()
            camps = sb.table("campaign_queue").select("status").execute()
            camps_done = sum(1 for c in camps.data if c["status"] == "done")
            camps_scraping = sum(1 for c in camps.data if c["status"] == "scraping")
            camps_pending = sum(1 for c in camps.data if c["status"] == "pending")

            # Count by status (filtered queries stay under 1000-row limit)
            leads_cleaned = len(sb.table("leads").select("id").eq("status", "cleaned").execute().data)
            leads_smartlead = len(sb.table("leads").select("id").eq("status", "imported_smartlead").execute().data)

            # Paginate to get per-niche breakdown (bypass 1000-row limit)
            niche_map = {}
            offset = 0
            while True:
                batch = sb.table("leads").select("niche").range(offset, offset + 999).execute()
                if not batch.data:
                    break
                for l in batch.data:
                    n = l.get("niche", "inconnu")
                    niche_map[n] = niche_map.get(n, 0) + 1
                offset += 1000
            by_niche = [{"niche": k, "total": v} for k, v in sorted(niche_map.items())]

            self._json({
                "campaigns": {"done": camps_done, "scraping": camps_scraping, "pending": camps_pending},
                "leads": {"raw": 0, "cleaned": leads_cleaned, "smartlead": leads_smartlead},
                "by_niche": by_niche,
            })
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _handle_get_templates(self):
        try:
            sb = get_supabase()
            result = sb.table("campaign_queue").select("niche, objective, timeframe, constraint_, custom_intro, smartlead_campaign_id").execute()

            vars_by_niche = {}
            smartlead_status = {}
            for r in result.data:
                n = r["niche"]
                if n not in vars_by_niche:
                    vars_by_niche[n] = {
                        "objective": r.get("objective") or "",
                        "timeframe": r.get("timeframe") or "",
                        "constraint_": r.get("constraint_") or "",
                        "custom_intro": r.get("custom_intro") or "",
                    }
                cid = r.get("smartlead_campaign_id")
                if cid and n not in smartlead_status:
                    smartlead_status[n] = {"niche": n, "campaign_id": cid}

            templates_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "email_templates.json")
            if os.path.exists(templates_path):
                with open(templates_path) as f:
                    sequences = json.load(f)
                    variants = sequences.get("variants", [])
            else:
                variants = []

            sequences_by_niche = {}
            for n in vars_by_niche:
                sequences_by_niche[n] = variants

            self._json({
                "vars": vars_by_niche,
                "sequences": sequences_by_niche,
                "smartlead": list(smartlead_status.values()),
            })
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _handle_save_templates(self):
        try:
            body = _get_json_body(self)
            niche = body.get("niche")
            if not niche:
                return self._json({"error": "niche requis"}, 400)

            sb = get_supabase()
            update = {}
            for field in ["objective", "timeframe", "constraint_", "custom_intro"]:
                if field in body:
                    update[field] = body[field]

            if update:
                sb.table("campaign_queue").update(update).eq("niche", niche).execute()

            self._json({"status": "saved", "niche": niche, "fields": list(update.keys())})
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _handle_sync_smartlead(self):
        try:
            body = _get_json_body(self)
            niche = body.get("niche")
            if not niche:
                return self._json({"error": "niche requis"}, 400)

            sb = get_supabase()
            result = sb.table("campaign_queue").select("smartlead_campaign_id").eq("niche", niche).limit(1).execute()
            if not result.data:
                return self._json({"error": "niche introuvable"}, 404)

            campaign_id = result.data[0].get("smartlead_campaign_id")
            if not campaign_id:
                return self._json({"error": "pas de smartlead_campaign_id pour cette niche. Crée d'abord une campagne via Sync."}, 400)

            templates_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "email_templates.json")
            with open(templates_path) as f:
                templates = json.load(f)
            variants = templates.get("variants", [])

            if not variants:
                return self._json({"error": "aucune variante dans email_templates.json"}, 400)

            # Récupérer les variables de la niche
            niche_vars = sb.table("campaign_queue").select("objective, timeframe, constraint_, custom_intro").eq("niche", niche).limit(1).execute().data
            if niche_vars:
                nv = niche_vars[0]
                rendered_variants = []
                for v in variants:
                    rendered_steps = []
                    for s in v.get("steps", []):
                        step_text = _render_template(s.get("body", ""), {
                            "objective": nv.get("objective", ""),
                            "timeframe": nv.get("timeframe", ""),
                            "constraint": nv.get("constraint_", ""),
                            "custom_intro": nv.get("custom_intro", ""),
                            "niche_target": niche,
                            "city": "",
                            "first_name": "Prénom",
                        })
                        rendered_steps.append({
                            "day": s["day"],
                            "subject": _render_template(s.get("subject", ""), nv) if s.get("subject") else "",
                            "body": step_text,
                        })
                    rendered_variants.append({"name": v["name"], "steps": rendered_steps})
            else:
                rendered_variants = variants

            ok = update_smartlead_sequences(campaign_id, rendered_variants)
            if ok:
                self._json({"status": "synced", "campaign_id": campaign_id})
            else:
                self._json({"error": "échec synchro Smartlead"}, 500)
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _handle_gemini(self):
        try:
            body = _get_json_body(self)
            niche = body.get("niche", "")
            field = body.get("field", "")

            if not GEMINI_API_KEY:
                return self._json({"error": "GEMINI_API_KEY non configurée"}, 500)

            prompts = {
                "objective": f"Génère un objectif professionnel court (5-10 mots) pour des campagnes email destinées à des {niche}. Ex: 'développer leur clientèle'",
                "timeframe": f"Génère un délai court (3-6 mots) pour un objectif de {niche}. Ex: 'en 3 mois'",
                "constraint": f"Génère une contrainte courte (5-10 mots) pour des {niche}. Ex: 'sans investissement publicitaire'",
                "custom_intro": f"Génère une phrase d'introduction courte (5-10 mots) pour contacter des {niche}. Ex: 'vous aider à développer votre activité'",
            }

            prompt = prompts.get(field, f"Génère une suggestion courte pour {field} concernant {niche}")

            resp = requests.post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
                params={"key": GEMINI_API_KEY},
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=15,
            )

            if resp.status_code != 200:
                return self._json({"error": f"Gemini HTTP {resp.status_code}"}, 500)

            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return self._json({"error": "aucune réponse Gemini"}, 500)

            text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
            text = text.split("\n")[0][:60]

            self._json({"suggestion": text})
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def log_message(self, format, *args):
        pass


def _cleaner_keep_alive():
    engine_url = f"https://engine-20m5.onrender.com/"
    cleaner_url = "https://cleaner-4tau.onrender.com/health"
    while True:
        try:
            requests.get(engine_url, timeout=10)
            requests.get(cleaner_url, timeout=10)
        except Exception:
            pass
        time.sleep(600)  # 10 minutes


def start_http():
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[MAIN] Server on port {PORT}")
    server.serve_forever()


if __name__ == "__main__":
    threading.Thread(target=_cleaner_keep_alive, daemon=True).start()
    t = threading.Thread(target=start_http, daemon=True)
    t.start()
    auto_run()

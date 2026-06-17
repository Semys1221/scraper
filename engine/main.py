import os
import sys
import threading
import json
import urllib.parse
import time
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import requests
from engine.scraper import start_scrape, stop_scrape, get_scrape_status, start_auto_discover
from database.config import (
    get_supabase,
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
.spinner{display:inline-block;width:28px;height:28px;border:3px solid #334155;border-top-color:#3b82f6;border-radius:50%;animation:spin .8s linear infinite}
.spinner-sm{width:18px;height:18px;border-width:2px}
@keyframes spin{to{transform:rotate(360deg)}}
</style>
</head>
<body>

<div class="nav">
  <a href="/dashboard">Dashboard</a>
</div>

<h1>Scraper Dashboard</h1>

<div class="grid" id="campaigns">
  <div class="card"><div class="label">Campagnes faites</div><div class="value green" id="done"><div class="spinner spinner-sm"></div></div></div>
  <div class="card"><div class="label">En cours</div><div class="value blue" id="scraping"><div class="spinner spinner-sm"></div></div></div>
  <div class="card"><div class="label">En attente</div><div class="value yellow" id="pending"><div class="spinner spinner-sm"></div></div></div>
</div>

<div class="grid" id="leads">
  <div class="card"><div class="label">Leads bruts</div><div class="value orange" id="raw"><div class="spinner spinner-sm"></div></div></div>
  <div class="card"><div class="label">Nettoyés</div><div class="value purple" id="cleaned"><div class="spinner spinner-sm"></div></div></div>
  <div class="card"><div class="label">Smartlead</div><div class="value green" id="smartlead"><div class="spinner spinner-sm"></div></div></div>
</div>

<div class="card">
  <div style="font-size:13px;color:#94a3b8;margin-bottom:12px">Leads par niche</div>
  <table class="niche-table">
    <thead><tr><th>Niche</th><th>Total</th><th>Progression</th></tr></thead>
    <tbody id="niche-rows"><tr><td colspan="3" style="text-align:center;padding:16px;color:#64748b"><div class="spinner spinner-sm" style="margin:0 auto"></div></td></tr></tbody>
  </table>
</div>

<div class="card">
  <div style="font-size:13px;color:#94a3b8;margin-bottom:12px">Scraping en direct</div>

  <div style="display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap">
    <input id="scrape-niche" placeholder="Niche (ex: avocat)" style="width:180px;padding:8px 12px;border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;font-size:14px">
    <input id="scrape-limit" type="number" value="2000" style="width:100px;padding:8px 12px;border-radius:8px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;font-size:14px">
    <button class="btn btn-green" onclick="startScrape()" style="padding:8px 16px;border-radius:8px;border:none;font-size:14px;font-weight:500;cursor:pointer;background:#22c55e;color:#fff">▶ Lancer</button>
  </div>

  <div id="scrape-jobs"></div>
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

// --- Scraping controls ---
async function refreshScrapeStatus(){
  try{
    const r = await fetch('/api/scrape/status');
    const jobs = await r.json();
    const container = document.getElementById('scrape-jobs');
    const entries = Object.entries(jobs);
    if(!entries.length){
      container.innerHTML = '<div style="color:#64748b;font-size:13px">Aucun scraping en cours</div>';
      return;
    }
    let html = '';
    for(const [niche, job] of entries){
      const pct = job.target > 0 ? Math.min(100, (job.total / job.target * 100)).toFixed(1) : 0;
      const statusColors = {queued:'#eab308', running:'#3b82f6', done:'#22c55e', error:'#ef4444', stopping:'#f97316'};
      const color = statusColors[job.status] || '#64748b';
      const statusLabel = {queued:'En attente', running:'En cours', done:'Terminé', error:'Erreur', stopping:'Arrêt en cours'};
      html += '<div style="background:#0f172a;border-radius:8px;padding:12px;margin-bottom:8px;border:1px solid #334155">';
      html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">';
      html += '<strong style="color:#f8fafc">' + niche + '</strong>';
      html += '<span style="font-size:12px;color:' + color + ';font-weight:500">' + (statusLabel[job.status] || job.status) + '</span>';
      html += '</div>';
      html += '<div style="display:flex;justify-content:space-between;font-size:12px;color:#94a3b8;margin-bottom:4px">';
      html += '<span>' + job.total + ' / ' + job.target + ' leads</span>';
      html += '<span>' + job.cities_done + '/' + job.cities_total + ' villes</span>';
      if(job.current_city) html += '<span>📍 ' + job.current_city + '</span>';
      html += '</div>';
      html += '<div class="bar"><div class="bar-fill" style="width:' + pct + '%;background:' + color + '"></div></div>';
      if(job.status === 'running' || job.status === 'queued'){
        html += '<button onclick="stopScrape(\'' + niche + '\')" style="margin-top:8px;padding:4px 12px;border-radius:6px;border:1px solid #ef4444;background:transparent;color:#ef4444;font-size:12px;cursor:pointer">⏹ Stop</button>';
      }
      if(job.errors && job.errors.length){
        html += '<div style="margin-top:4px;font-size:12px;color:#ef4444">' + job.errors.join(', ') + '</div>';
      }
      html += '</div>';
    }
    container.innerHTML = html;
  }catch(e){}
}
refreshScrapeStatus();
setInterval(refreshScrapeStatus, 2000);

async function startScrape(){
  const niche = document.getElementById('scrape-niche').value.trim().toLowerCase();
  if(!niche) return;
  const limit = parseInt(document.getElementById('scrape-limit').value) || 2000;
  await fetch('/api/scrape/start', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({niche, limit})
  });
  document.getElementById('scrape-niche').value = '';
  refreshScrapeStatus();
}

async function stopScrape(niche){
  await fetch('/api/scrape/stop', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({niche})
  });
  refreshScrapeStatus();
}
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
        elif self.path == "/api/stats":
            self._handle_stats()
        elif self.path == "/api/scrape/status":
            self._handle_scrape_status()
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
        if self.path == "/api/scrape/start":
            self._handle_scrape_start()
        elif self.path == "/api/scrape/stop":
            self._handle_scrape_stop()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_tracking(self, link_type):
        redirect_url = os.getenv("CALENDLY_URL", "https://calendly.com/syli-conseils/30min") if link_type == "book" else os.getenv("TESTIMONIAL_URL", "https://sylkconseils.com")
        action = "réservation" if link_type == "book" else "témoignage"
        title = "Planifier un RDV" if link_type == "book" else "Témoignage"
        webhook = os.getenv("DISCORD_WEBHOOK_URL", "")

        import datetime
        now = datetime.datetime.now()
        date_fr = now.strftime("%d/%m/%Y à %Hh%M").lstrip("0")
        discord_msg = f"Une nouvelle visite le {date_fr} sur la page de {action}"

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
var b = new Blob([JSON.stringify({{content:'{discord_msg}'}})], {{type:'application/json'}});
navigator.sendBeacon('{webhook}', b);
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

            def _count_leads_by_status(status):
                total = 0
                offset = 0
                while True:
                    batch = sb.table("leads").select("id").eq("status", status).range(offset, offset + 999).execute()
                    if not batch.data:
                        break
                    total += len(batch.data)
                    offset += 1000
                return total

            leads_cleaned = _count_leads_by_status("cleaned")
            leads_smartlead = _count_leads_by_status("imported_smartlead")

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

    def _handle_scrape_status(self):
        try:
            self._json(get_scrape_status())
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _handle_scrape_start(self):
        try:
            body = _get_json_body(self)
            niche = body.get("niche", "").strip().lower()
            if not niche:
                return self._json({"error": "niche requis"}, 400)
            limit = body.get("limit", 20000)
            result = start_scrape(niche, limit)
            if "error" in result:
                self._json(result, 409)
            else:
                self._json(result)
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _handle_scrape_stop(self):
        try:
            body = _get_json_body(self)
            niche = body.get("niche", "").strip().lower()
            if not niche:
                return self._json({"error": "niche requis"}, 400)
            self._json(stop_scrape(niche))
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
        time.sleep(600)


def start_http():
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[MAIN] Server on port {PORT}")
    server.serve_forever()


if __name__ == "__main__":
    threading.Thread(target=_cleaner_keep_alive, daemon=True).start()
    start_auto_discover()
    t = threading.Thread(target=start_http, daemon=True)
    t.start()
    # main thread keeps process alive
    while True:
        time.sleep(60)

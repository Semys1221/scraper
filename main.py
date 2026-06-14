import os
import sys
import threading
import json
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine import auto_run
from config import get_supabase

PORT = int(os.getenv("PORT", 8001))


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Scraper Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
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
.status-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.status-dot.green{background:#22c55e}.status-dot.red{background:#ef4444}.status-dot.yellow{background:#eab308}
</style>
</head>
<body>

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


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/dashboard" or self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode())
        elif self.path == "/api/stats":
            try:
                sb = get_supabase()
                camps = sb.table("campaign_queue").select("status", count="exact").execute()
                camps_done = sum(1 for c in camps.data if c["status"] == "done")
                camps_scraping = sum(1 for c in camps.data if c["status"] == "scraping")
                camps_pending = sum(1 for c in camps.data if c["status"] == "pending")

                leads = sb.table("leads").select("status, niche", count="exact").execute()
                leads_raw = sum(1 for l in leads.data if l["status"] == "raw")
                leads_cleaned = sum(1 for l in leads.data if l["status"] == "cleaned")
                leads_smartlead = sum(1 for l in leads.data if l["status"] == "imported_smartlead")

                niche_map = {}
                for l in leads.data:
                    n = l.get("niche", "inconnu")
                    if n not in niche_map:
                        niche_map[n] = 0
                    niche_map[n] += 1
                by_niche = [{"niche": k, "total": v} for k, v in sorted(niche_map.items())]

                data = {
                    "campaigns": {"done": camps_done, "scraping": camps_scraping, "pending": camps_pending},
                    "leads": {"raw": leads_raw, "cleaned": leads_cleaned, "smartlead": leads_smartlead},
                    "by_niche": by_niche,
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(data).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        elif self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass


def start_http():
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[MAIN] Dashboard server on port {PORT}")
    server.serve_forever()


if __name__ == "__main__":
    t = threading.Thread(target=start_http, daemon=True)
    t.start()
    auto_run()

import sys, time
sys.path.insert(0, '/Users/evqn/Business/Github/Outreach_System')
from engine.scraper import start_scrape, _ensure_worker, get_scrape_status

niches = [
    ("agents immobiliers", 10000),
]

for niche, limit in niches:
    r = start_scrape(niche, limit)
    print(f"[{niche}] {r}", flush=True)
_ensure_worker()

while True:
    statuses = get_scrape_status()
    if not statuses:
        print(f"[{time.strftime('%H:%M:%S')}] [IDLE] aucun job", flush=True)
        break
    all_done = True
    for niche, limit in niches:
        s = statuses.get(niche, {})
        print(f"[{time.strftime('%H:%M:%S')}] {niche}: {s.get('status','?'):>8} — {s.get('total',0):>5} leads | {s.get('cities_done',0)}/{s.get('cities_total','?')} villes | {s.get('current_city','')}", flush=True)
        if s.get('status') not in ('done', 'error'):
            all_done = False
    if all_done:
        break
    time.sleep(15)

print("✅ Scrape terminé", flush=True)

import os
import sys
import uuid
import time
import queue
import threading
import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import requests
from database.config import (
    get_supabase,
    OUTSCRAPER_API_KEY,
    OUTSCRAPER_API_BASE,
    send_discord,
)

BATCH_SIZE = 100
LOG_FREQUENCY = 50
MILESTONES = [100, 500, 1000, 2000, 5000]
TARGET_PER_NICHE = 20_000
MAX_PER_CITY = 500
RETRY_DELAY = 10
MAX_CONCURRENT = 3

# --- Job queue system ---
_scrape_queue = queue.Queue()
_scrape_status = {}
_status_lock = threading.Lock()
_worker_thread = None
_worker_running = False


def _update_status(niche: str, **kwargs):
    with _status_lock:
        if niche in _scrape_status:
            _scrape_status[niche].update(kwargs)


def _ensure_worker():
    global _worker_thread, _worker_running
    if _worker_thread and _worker_thread.is_alive():
        return
    _worker_running = True
    _worker_thread = threading.Thread(target=_worker_loop, daemon=True)
    _worker_thread.start()


def _worker_loop():
    global _worker_running
    while _worker_running:
        try:
            niche, limit = _scrape_queue.get(timeout=5)
        except queue.Empty:
            continue

        _update_status(niche, status="running")
        try:
            total = _scrape_niche(niche, limit)
            _update_status(niche, status="done")
            print(f"[QUEUE] ✅ {niche}: {total} leads")
        except Exception as e:
            _update_status(niche, status="error", errors=[str(e)])
            print(f"[QUEUE] ❌ {niche}: {e}")

        _scrape_queue.task_done()
        time.sleep(300)
        with _status_lock:
            if niche in _scrape_status and _scrape_status[niche].get("status") in ("done", "error"):
                del _scrape_status[niche]


def start_scrape(niche: str, limit: int = TARGET_PER_NICHE):
    with _status_lock:
        existing = _scrape_status.get(niche)
        if existing and existing.get("status") in ("running", "queued"):
            return {"error": f"'{niche}' déjà en cours"}
        _scrape_status[niche] = {
            "status": "queued",
            "niche": niche,
            "total": 0,
            "target": limit,
            "current_city": "",
            "cities_done": 0,
            "cities_total": 0,
            "errors": [],
            "started_at": time.time(),
        }
    _scrape_queue.put((niche, limit))
    _ensure_worker()
    return {"status": "queued", "niche": niche, "limit": limit}


def stop_scrape(niche: str):
    with _status_lock:
        if niche in _scrape_status:
            _scrape_status[niche]["status"] = "stopping"
            return {"status": "stopping", "niche": niche}
    return {"error": f"'{niche}' pas en cours"}


def get_scrape_status():
    with _status_lock:
        return {k: dict(v) for k, v in _scrape_status.items()}


def start_auto_discover():
    t = threading.Thread(target=_auto_discover_loop, daemon=True)
    t.start()


def _auto_discover_loop():
    while True:
        try:
            sb = get_supabase()
            result = (
                sb.table("campaign_queue")
                .select("niche")
                .eq("status", "pending")
                .execute()
            )
            if result.data:
                seen = set()
                for r in result.data:
                    n = r["niche"]
                    if n not in seen:
                        seen.add(n)
                        with _status_lock:
                            already = _scrape_status.get(n)
                            if not already or already.get("status") in ("done", "error", None):
                                start_scrape(n)
        except Exception as e:
            print(f"[AUTO] {e}")
        time.sleep(60)


# --- API log buffer ---
_api_log = deque(maxlen=500)
_api_log_lock = threading.Lock()


def _log_api(niche: str, city: str, type_: str, detail: str = ""):
    entry = {
        "ts": time.time(),
        "niche": niche,
        "city": city,
        "type": type_,
        "detail": detail,
    }
    with _api_log_lock:
        _api_log.append(entry)


def get_api_logs(limit: int = 100):
    with _api_log_lock:
        return list(_api_log)[-limit:]


# --- Parsing ---
def _parse_keywords(text: str | None) -> list[str]:
    if not text:
        return []
    return [kw.strip().lower() for kw in text.split(",") if kw.strip()]


def _matches_keywords(company_name: str, email: str, include: list[str], exclude: list[str]) -> bool:
    if not include and not exclude:
        return True
    text = f"{company_name} {email}".lower()
    if include and not any(kw in text for kw in include):
        return False
    if exclude and any(kw in text for kw in exclude):
        return False
    return True


# --- Scraping ---
def _scrape_city(sb, niche, city, queue_id, include_kw, exclude_kw):
    _update_status(niche, current_city=city)
    print(f"[ENGINE] ▶ {niche} / {city}")
    sb.table("campaign_queue").update({"status": "scraping"}).eq("id", queue_id).execute()

    total_inserted = 0
    total_filtered = 0
    skip = 0

    while True:
        if total_inserted >= MAX_PER_CITY:
            print(f"[ENGINE] 🛑 Cap {MAX_PER_CITY} atteint pour {niche}/{city}")
            break
        query = f"{niche} {city}"
        params = {
            "query": query,
            "limit": BATCH_SIZE,
            "skip": skip,
            "language": "fr",
            "enrichment": "contacts_n_leads",
        }

        _log_api(niche, city, "request", f"skip={skip} query={query}")

        try:
            resp = requests.get(
                f"{OUTSCRAPER_API_BASE}/maps/search-v2",
                params=params,
                headers={"X-API-KEY": OUTSCRAPER_API_KEY},
                timeout=60,
            )
        except requests.RequestException as e:
            _log_api(niche, city, "error", f"Réseau: {e}")
            print(f"[ENGINE] ⚠ Réseau: {e}")
            time.sleep(RETRY_DELAY)
            continue

        if resp.status_code == 429:
            _log_api(niche, city, "rate_limit", f"429, pause {RETRY_DELAY}s")
            print(f"[ENGINE] ⏳ Rate limit (429), pause {RETRY_DELAY}s")
            time.sleep(RETRY_DELAY)
            continue

        if resp.status_code == 404:
            _log_api(niche, city, "done", f"404 — ville épuisée")
            break

        if resp.status_code not in (200, 202):
            _log_api(niche, city, "error", f"HTTP {resp.status_code}: {resp.text[:100]}")
            print(f"[ENGINE] ⚠ Erreur {resp.status_code}: {resp.text[:200]}")
            time.sleep(RETRY_DELAY)
            continue

        data = resp.json()

        if data.get("status") == "Pending":
            poll_url = data.get("results_location")
            if not poll_url:
                _log_api(niche, city, "error", "Pending sans results_location")
                print(f"[ENGINE] ⏳ Requête en attente sans results_location, pause 5s")
                time.sleep(5)
                continue
            _log_api(niche, city, "pending", "Polling résultats...")
            print(f"[ENGINE] Requête en attente, polling...")
            for _ in range(60):
                time.sleep(3)
                poll_resp = requests.get(poll_url, timeout=30)
                if poll_resp.status_code != 200:
                    continue
                poll_data = poll_resp.json()
                if poll_data.get("status") in ("Completed", "Success", None):
                    data = poll_data
                    break
            else:
                _log_api(niche, city, "error", "Timeout polling Outscraper")
                print(f"[ENGINE] Timeout en attente des résultats Outscraper")
                continue

        items = data.get("data", [])
        if items and isinstance(items, list) and len(items) > 0 and isinstance(items[0], list):
            items = items[0]
        if not items:
            _log_api(niche, city, "done", f"0 résultats skip={skip}")
            print(f"[ENGINE] 0 résultats à skip {skip}, ville épuisée")
            break

        inserted = 0
        batch_filtered = 0
        for entry in items:
            place_id = str(entry.get("place_id", entry.get("id", str(uuid.uuid4()))))
            email = (entry.get("email") or entry.get("email_1") or "").lower().strip()
            if not email:
                batch_filtered += 1
                continue
            company_name = entry.get("name") or entry.get("company_name", "") or ""
            if not _matches_keywords(company_name, email, include_kw, exclude_kw):
                total_filtered += 1
                batch_filtered += 1
                continue
            if not entry.get("phone"):
                total_filtered += 1
                batch_filtered += 1
                continue

            lead = {
                "place_id": place_id,
                "campaign_queue_id": queue_id,
                "email": email,
                "company_name": company_name,
                "phone": entry.get("phone", ""),
                "location": entry.get("full_address") or entry.get("location", ""),
                "niche": niche,
                "city": city,
                "status": "raw",
                "metadata": {},
            }
            try:
                sb.table("leads").upsert(lead, on_conflict="place_id").execute()
                inserted += 1
            except Exception as e:
                err = str(e).lower()
                if "duplicate" not in err and "23505" not in err:
                    _log_api(niche, city, "error", f"Upsert {email}: {e}")
                    print(f"[ENGINE] ⚠ Erreur upsert {email}: {e}")

        total_inserted += inserted
        new_total = total_inserted

        _log_api(niche, city, "response", f"+{inserted} leads (filtrés={batch_filtered})")

        if inserted > 0:
            prev = new_total - inserted
            prev_mod = (prev // LOG_FREQUENCY) * LOG_FREQUENCY
            new_mod = (new_total // LOG_FREQUENCY) * LOG_FREQUENCY
            if new_mod > prev_mod:
                print(f"[ENGINE] 📊 {niche}/{city}: {new_total} leads ({total_filtered} filtrés)")

        for m in MILESTONES:
            if prev < m <= new_total:
                send_discord(f"[MILESTONE] **{niche}/{city}** : {m} leads !")

        print(f"[ENGINE]   batch +{inserted} → {total_inserted} leads ({niche}/{city})")

        if len(items) < BATCH_SIZE:
            break
        skip += BATCH_SIZE

    sb.table("campaign_queue").update({"status": "done"}).eq("id", queue_id).execute()
    _log_api(niche, city, "done", f"{total_inserted} leads, {total_filtered} filtrés")
    print(f"[ENGINE] ✅ {niche} / {city} terminée ({total_inserted} leads, {total_filtered} filtrés)")
    return total_inserted


def _scrape_niche(niche: str, target: int = TARGET_PER_NICHE):
    sb = get_supabase()

    cities = (
        sb.table("campaign_queue")
        .select("*")
        .eq("niche", niche)
        .eq("status", "pending")
        .order("city")
        .execute()
    )

    if not cities.data:
        print(f"[ENGINE] ⏭ Aucune campagne pending pour '{niche}'")
        return 0

    include_kw = _parse_keywords(cities.data[0].get("include_keywords"))
    exclude_kw = _parse_keywords(cities.data[0].get("exclude_keywords"))

    if include_kw or exclude_kw:
        print(f"[ENGINE] Filtres {niche}: include={include_kw}, exclude={exclude_kw}")

    _update_status(niche, cities_total=len(cities.data))

    total = 0
    nb_cities = len(cities.data)
    print(f"[ENGINE] 🏁 {niche}: {nb_cities} villes à traiter, target {target} leads")

    for idx, camp in enumerate(cities.data, 1):
        if total >= target:
            print(f"[ENGINE] 🎯 Objectif {target} atteint pour '{niche}' après {idx-1}/{nb_cities} villes")
            break

        with _status_lock:
            if _scrape_status.get(niche, {}).get("status") == "stopping":
                print(f"[ENGINE] 🛑 '{niche}' arrêté par l'utilisateur")
                break

        inserted = _scrape_city(sb, niche, camp["city"], camp["id"], include_kw, exclude_kw)
        total += inserted
        _update_status(niche, total=total, cities_done=idx)
        print(f"[ENGINE] 📈 {niche}: {total}/{target} leads ({idx}/{nb_cities} villes)")

    if total > 0:
        send_discord(f"[TERMINÉ] **{niche}** : {total} leads scrapés")
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--niche", help="Scraper une niche spécifique")
    parser.add_argument("--limit", type=int, default=TARGET_PER_NICHE)
    args = parser.parse_args()

    if args.niche:
        start_scrape(args.niche, args.limit)
        _ensure_worker()
        while True:
            s = get_scrape_status().get(args.niche, {})
            print(f"  {s.get('status','?')}: {s.get('total',0)}/{s.get('target','?')} leads")
            if s.get("status") in ("done", "error"):
                break
            time.sleep(5)
    else:
        parser.print_help()

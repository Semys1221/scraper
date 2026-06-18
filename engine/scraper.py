import os, sys, uuid, time, queue, threading, argparse
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from outscraper import OutscraperClient
from database.config import get_supabase, OUTSCRAPER_API_KEY, send_discord

LOG_FREQUENCY = 50
MILESTONES = [100, 500, 1000, 2000, 5000]
TARGET_PER_NICHE = 20_000
RETRY_DELAY = 10

_client = OutscraperClient(api_key=OUTSCRAPER_API_KEY)

# --- Job queue ---
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
            print(f"[QUEUE] \u2705 {niche}: {total} leads")
        except Exception as e:
            _update_status(niche, status="error", errors=[str(e)])
            print(f"[QUEUE] \u274c {niche}: {e}")
        _scrape_queue.task_done()
        time.sleep(300)
        with _status_lock:
            if niche in _scrape_status and _scrape_status[niche].get("status") in ("done", "error"):
                del _scrape_status[niche]


def start_scrape(niche: str, limit: int = TARGET_PER_NICHE):
    with _status_lock:
        existing = _scrape_status.get(niche)
        if existing and existing.get("status") in ("running", "queued"):
            return {"error": f"'{niche}' d\u00e9j\u00e0 en cours"}
        _scrape_status[niche] = {
            "status": "queued", "niche": niche, "total": 0, "target": limit,
            "current_city": "", "cities_done": 0, "cities_total": 0, "errors": [], "started_at": time.time(),
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
    threading.Thread(target=_auto_discover_loop, daemon=True).start()


def _auto_discover_loop():
    while True:
        try:
            sb = get_supabase()
            result = sb.table("campaign_queue").select("niche").eq("status", "pending").execute()
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


# --- API log ---
_api_log = deque(maxlen=500)
_api_log_lock = threading.Lock()


def _log_api(niche: str, city: str, type_: str, detail: str = ""):
    with _api_log_lock:
        _api_log.append({"ts": time.time(), "niche": niche, "city": city, "type": type_, "detail": detail})


def get_api_logs(limit: int = 100):
    with _api_log_lock:
        return list(_api_log)[-limit:]


# --- Helpers ---
def _parse_keywords(text: str | None) -> list[str]:
    return [kw.strip().lower() for kw in text.split(",") if kw.strip()] if text else []


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
    print(f"[ENGINE] \u25b6 {niche} / {city}")
    sb.table("campaign_queue").update({"status": "scraping"}).eq("id", queue_id).execute()

    try:
        results = _client.google_maps_search(
            f"{niche} {city}",
            limit=500,
            language="fr",
            enrichment="contacts_n_leads",
        )
    except Exception as e:
        print(f"[ENGINE] \u26a0 SDK error {niche}/{city}: {e}")
        sb.table("campaign_queue").update({"status": "done"}).eq("id", queue_id).execute()
        return 0

    items = results[0] if results else []
    if not items:
        _log_api(niche, city, "done", "0 r\u00e9sultats")
        sb.table("campaign_queue").update({"status": "done"}).eq("id", queue_id).execute()
        return 0

    _log_api(niche, city, "response", f"{len(items)} r\u00e9sultats bruts")
    inserted = 0
    total_filtered = 0
    for entry in items:
        place_id = str(entry.get("place_id", entry.get("id", str(uuid.uuid4()))))
        email = (entry.get("email") or entry.get("email_1") or "").lower().strip()
        if not email:
            continue
        company_name = entry.get("name") or entry.get("company_name", "") or ""
        if not _matches_keywords(company_name, email, include_kw, exclude_kw):
            total_filtered += 1
            continue
        first_name = ""
        local = email.split("@")[0]
        for sep in [".", "-", "_"]:
            if sep in local:
                first_name = local.split(sep)[0].strip().capitalize()
                break
        lead = {
            "place_id": place_id, "campaign_queue_id": queue_id, "email": email,
            "company_name": company_name, "phone": entry.get("phone", ""),
            "location": entry.get("full_address") or entry.get("location", ""),
            "niche": niche, "city": city,
            "status": "cleaned", "valid": True, "first_name": first_name, "domain": email.split("@")[1] if "@" in email else "",
            "metadata": {},
        }
        try:
            sb.table("leads").upsert(lead, on_conflict="place_id").execute()
            inserted += 1
        except Exception as e:
            err = str(e).lower()
            if "duplicate" not in err and "23505" not in err:
                print(f"[ENGINE] \u26a0 Upsert {email}: {e}")

    print(f"[ENGINE]   +{inserted} leads ({niche}/{city}) filtr\u00e9s={total_filtered}")
    for m in MILESTONES:
        if m <= inserted:
            send_discord(f"[MILESTONE] **{niche}/{city}** : {m} leads !")

    sb.table("campaign_queue").update({"status": "done"}).eq("id", queue_id).execute()
    return inserted


def _scrape_niche(niche: str, target: int = TARGET_PER_NICHE):
    sb = get_supabase()
    cities = sb.table("campaign_queue").select("*").eq("niche", niche).eq("status", "pending").order("city").execute()
    if not cities.data:
        print(f"[ENGINE] \u23ed Aucune campagne pending pour '{niche}'")
        return 0

    include_kw = _parse_keywords(cities.data[0].get("include_keywords"))
    exclude_kw = _parse_keywords(cities.data[0].get("exclude_keywords"))
    if include_kw or exclude_kw:
        print(f"[ENGINE] Filtres {niche}: include={include_kw}, exclude={exclude_kw}")

    _update_status(niche, cities_total=len(cities.data))
    total, nb_cities = 0, len(cities.data)
    print(f"[ENGINE] \U0001f3c1 {niche}: {nb_cities} villes, target {target} leads")

    for idx, camp in enumerate(cities.data, 1):
        if total >= target:
            print(f"[ENGINE] \U0001f3af Objectif {target} atteint apr\u00e8s {idx-1}/{nb_cities} villes")
            break
        with _status_lock:
            if _scrape_status.get(niche, {}).get("status") == "stopping":
                print(f"[ENGINE] \U0001f6d1 '{niche}' arr\u00eat\u00e9")
                break
        inserted = _scrape_city(sb, niche, camp["city"], camp["id"], include_kw, exclude_kw)
        total += inserted
        _update_status(niche, total=total, cities_done=idx)
        print(f"[ENGINE] \U0001f4c8 {niche}: {total}/{target} leads ({idx}/{nb_cities} villes)")

    if total > 0:
        send_discord(f"[TERMIN\u00c9] **{niche}** : {total} leads scrap\u00e9s")
    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--niche")
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

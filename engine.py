import os
import sys
import uuid
import time
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
from config import (
    get_supabase,
    OUTSCRAPER_API_KEY,
    OUTSCRAPER_API_BASE,
    send_discord,
) 

BATCH_SIZE = 100
TARGET_PER_NICHE = 20_000
TARGET_CYCLE = 2000
TARGET_MAX = 6000
RETRY_DELAY = 10
MAX_CONCURRENT = 3
POLL_INTERVAL = 60

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





def _scrape_city(sb, niche, city, queue_id, include_kw, exclude_kw):
    print(f"[ENGINE] Scraping {niche} / {city}")
    sb.table("campaign_queue").update({"status": "scraping"}).eq("id", queue_id).execute()

    total_inserted = 0
    total_filtered = 0
    skip = 0

    while True:
        params = {
            "query": f"{niche} {city}",
            "limit": BATCH_SIZE,
            "skip": skip,
            "language": "fr",
            "enrichment": "contacts_n_leads",
        }

        try:
            resp = requests.get(
                f"{OUTSCRAPER_API_BASE}/maps/search-v2",
                params=params,
                headers={"X-API-KEY": OUTSCRAPER_API_KEY},
                timeout=60,
            )
        except requests.RequestException as e:
            print(f"[ENGINE] Erreur réseau: {e}")
            time.sleep(RETRY_DELAY)
            continue

        if resp.status_code == 429:
            print(f"[ENGINE] Rate limit (429), pause {RETRY_DELAY}s")
            time.sleep(RETRY_DELAY)
            continue

        if resp.status_code == 404:
            break

        if resp.status_code not in (200, 202):
            print(f"[ENGINE] Erreur {resp.status_code}: {resp.text[:200]}")
            time.sleep(RETRY_DELAY)
            continue

        data = resp.json()

        if data.get("status") == "Pending":
            poll_url = data.get("results_location")
            if not poll_url:
                print(f"[ENGINE] Requête en attente sans results_location, pause 5s")
                time.sleep(5)
                continue
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
                print(f"[ENGINE] Timeout en attente des résultats Outscraper")
                continue

        items = data.get("data", [])
        if items and isinstance(items, list) and len(items) > 0 and isinstance(items[0], list):
            items = items[0]
        if not items:
            print(f"[ENGINE] 0 résultats à skip {skip}, ville épuisée")
            break

        inserted = 0
        for entry in items:
            place_id = str(entry.get("place_id", entry.get("id", str(uuid.uuid4()))))
            email = (entry.get("email") or entry.get("email_1") or "").lower().strip()
            if not email:
                continue
            company_name = entry.get("name") or entry.get("company_name", "") or ""
            if not _matches_keywords(company_name, email, include_kw, exclude_kw):
                total_filtered += 1
                continue
            if not entry.get("phone"):
                total_filtered += 1
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
                    print(f"[ENGINE] Erreur upsert {email}: {e}")

        total_inserted += inserted
        print(f"[ENGINE] +{inserted} leads (total: {total_inserted}) à skip {skip}")

        if len(items) < BATCH_SIZE:
            break
        skip += BATCH_SIZE

    sb.table("campaign_queue").update({"status": "done"}).eq("id", queue_id).execute()
    print(f"[ENGINE] {niche} / {city} terminée ({total_inserted} leads, {total_filtered} filtrés)")
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
        print(f"[ENGINE] Aucune campagne pending pour '{niche}'")
        return 0

    include_kw = _parse_keywords(cities.data[0].get("include_keywords"))
    exclude_kw = _parse_keywords(cities.data[0].get("exclude_keywords"))

    if include_kw or exclude_kw:
        print(f"[ENGINE] Filtres {niche}: include={include_kw}, exclude={exclude_kw}")

    total = 0
    for camp in cities.data:
        if total >= target:
            print(f"[ENGINE] Objectif {target} atteint pour '{niche}'")
            break
        inserted = _scrape_city(sb, niche, camp["city"], camp["id"], include_kw, exclude_kw)
        total += inserted
        print(f"[ENGINE] Total {niche}: {total}/{target}")

    if total > 0:
        send_discord(f"[TERMINÉ] **{niche}** : {total} leads scrapés")
    return total


def _get_smartlead_count(sb, niche: str) -> int:
    result = (
        sb.table("leads")
        .select("id")
        .eq("niche", niche)
        .eq("status", "imported_smartlead")
        .execute()
    )
    return len(result.data)


def auto_run():
    print(f"[ENGINE] Mode auto — {MAX_CONCURRENT} niches concurrentes | cycle={TARGET_CYCLE} max={TARGET_MAX}")

    while True:
        sb = get_supabase()

        sb.table("campaign_queue").update({"status": "pending"}).eq("status", "scraping").execute()

        result = (
            sb.table("campaign_queue")
            .select("niche, priority")
            .eq("status", "pending")
            .execute()
        )

        if not result.data:
            print(f"[ENGINE] Aucune niche pending. Nouvelle vérification dans {POLL_INTERVAL}s")
            time.sleep(POLL_INTERVAL)
            continue

        # Build unique niches with their priority
        niche_priorities = {}
        for r in result.data:
            n = r["niche"]
            if n not in niche_priorities:
                niche_priorities[n] = r.get("priority", 99)

        # Sort by priority (lowest first), then alpha
        all_niches = sorted(niche_priorities.keys(), key=lambda n: (niche_priorities.get(n, 99), n))

        # Separate priority niches (1-3) from the rest
        priority_niches = [n for n in all_niches if niche_priorities.get(n, 99) <= 3]
        other_niches = [n for n in all_niches if niche_priorities.get(n, 99) > 3]

        # For priority niches: check Smartlead counts and cap per cycle
        ready = []
        for n in priority_niches:
            current = _get_smartlead_count(sb, n)
            if current >= TARGET_MAX:
                print(f"[ENGINE] 🎯 {n}: {current}/{TARGET_MAX} — objectif atteint, ignoré")
                continue
            per_run = min(TARGET_CYCLE, TARGET_MAX - current)
            ready.append((n, per_run, current))

        # Fill remaining slots with other niches (no cap)
        slots_left = MAX_CONCURRENT - len(ready)
        for n in other_niches[:slots_left]:
            ready.append((n, TARGET_PER_NICHE, 0))

        if not ready:
            print(f"[ENGINE] ✅ Tous les objectifs atteints. Nouvelle vérification dans {POLL_INTERVAL}s")
            time.sleep(POLL_INTERVAL)
            continue

        print(f"[ENGINE] Niches à traiter: {[(n, t) for n, t, _ in ready]}")

        with ThreadPoolExecutor(max_workers=len(ready)) as executor:
            futures = {executor.submit(_scrape_niche, n, t): (n, c) for n, t, c in ready}
            for future in as_completed(futures):
                n, current = futures[future]
                try:
                    total = future.result()
                    new_total = current + total
                    print(f"[ENGINE] ✅ {n}: {current} → {new_total}/{TARGET_MAX}")
                except Exception as e:
                    print(f"[ENGINE] ❌ {n} en erreur: {e}")

        print(f"[ENGINE] Cycle terminé. Prochaine vérification dans {POLL_INTERVAL}s")
        time.sleep(POLL_INTERVAL)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--niche", help="Scraper une niche spécifique (mode manuel)")
    parser.add_argument("--auto", action="store_true", help="Mode auto: scrappe toutes les niches 3 par 3")
    args = parser.parse_args()

    if args.niche:
        _scrape_niche(args.niche)
    elif args.auto:
        auto_run()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

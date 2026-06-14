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

BATCH_SIZE = 500
TARGET_PER_NICHE = 20_000
RETRY_DELAY = 10
MAX_CONCURRENT = 3
POLL_INTERVAL = 60


def _parse_keywords(text: str | None) -> list[str]:
    if not text:
        return []
    return [kw.strip().lower() for kw in text.split(",") if kw.strip()]


def _matches_keywords(
    company_name: str,
    email: str,
    include: list[str],
    exclude: list[str],
) -> bool:
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
    offset = 0

    while True:
        params = {
            "query": f"{niche} {city}",
            "limit": BATCH_SIZE,
            "offset": offset,
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
        items = data.get("data", [])
        if not items:
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

            lead = {
                "place_id": place_id,
                "campaign_queue_id": queue_id,
                "email": email,
                "company_name": company_name,
                "phone": entry.get("phone", ""),
                "location": entry.get("full_address") or entry.get("location", ""),
                "niche": niche,
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
        print(f"[ENGINE] +{inserted} leads (total: {total_inserted}) à offset {offset}")

        if len(items) < BATCH_SIZE:
            break
        offset += BATCH_SIZE

    sb.table("campaign_queue").update({"status": "done"}).eq("id", queue_id).execute()
    print(f"[ENGINE] {niche} / {city} terminée ({total_inserted} leads, {total_filtered} filtrés)")
    return total_inserted


def _scrape_niche(niche: str):
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
        if total >= TARGET_PER_NICHE:
            print(f"[ENGINE] Objectif {TARGET_PER_NICHE} atteint pour '{niche}'")
            break
        inserted = _scrape_city(sb, niche, camp["city"], camp["id"], include_kw, exclude_kw)
        total += inserted
        print(f"[ENGINE] Total {niche}: {total}/{TARGET_PER_NICHE}")

    if total > 0:
        send_discord(f"[TERMINÉ] **{niche}** : {total} leads scrapés")
    return total


def auto_run():
    print(f"[ENGINE] Mode auto — {MAX_CONCURRENT} niches concurrentes")

    while True:
        sb = get_supabase()
        result = (
            sb.table("campaign_queue")
            .select("niche")
            .eq("status", "pending")
            .not_.is_("niche", "null")
            .execute()
        )

        niches = sorted(set(r["niche"] for r in result.data)) if result.data else []

        if not niches:
            print(f"[ENGINE] Aucune niche pending. Nouvelle vérification dans {POLL_INTERVAL}s")
            time.sleep(POLL_INTERVAL)
            continue

        print(f"[ENGINE] Niches à traiter: {niches}")
        active = []

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as executor:
            futures = {executor.submit(_scrape_niche, n): n for n in niches}
            for future in as_completed(futures):
                n = futures[future]
                try:
                    total = future.result()
                    active.append(n)
                    print(f"[ENGINE] ✅ {n} terminée: {total} leads")
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

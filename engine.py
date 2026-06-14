import os
import sys
import uuid
import time
import argparse

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

    if include:
        if not any(kw in text for kw in include):
            return False

    if exclude:
        if any(kw in text for kw in exclude):
            return False

    return True


def _scrape_city(
    sb,
    niche: str,
    city: str,
    queue_id: str,
    include_kw: list[str],
    exclude_kw: list[str],
) -> int:
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
            print(f"[ENGINE] 404 pour {niche} {city}, ville épuisée")
            break

        if resp.status_code not in (200, 202):
            print(f"[ENGINE] Erreur {resp.status_code}: {resp.text[:200]}")
            time.sleep(RETRY_DELAY)
            continue

        data = resp.json()
        items = data.get("data", [])
        if not items:
            print(f"[ENGINE] 0 résultats à offset {offset}, ville épuisée")
            break

        inserted = 0
        filtered = 0

        for entry in items:
            place_id = str(entry.get("place_id", entry.get("id", str(uuid.uuid4()))))
            email = (entry.get("email") or entry.get("email_1") or "").lower().strip()
            if not email:
                continue

            company_name = entry.get("name") or entry.get("company_name", "") or ""

            if not _matches_keywords(company_name, email, include_kw, exclude_kw):
                filtered += 1
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
        total_filtered += filtered
        print(f"[ENGINE] +{inserted} leads (+{filtered} filtrés, total city: {total_inserted}) à offset {offset}")

        if len(items) < BATCH_SIZE:
            print(f"[ENGINE] Moins de {BATCH_SIZE} résultats, ville épuisée")
            break

        offset += BATCH_SIZE

    if total_filtered > 0:
        print(f"[ENGINE] {total_filtered} leads filtrés par mots-clés sur {niche} / {city}")

    sb.table("campaign_queue").update({"status": "done"}).eq("id", queue_id).execute()
    print(f"[ENGINE] Ville terminée: {niche} / {city} ({total_inserted} leads)")
    return total_inserted


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--niche", required=True, help="Niche à scraper")
    args = parser.parse_args()
    niche = args.niche

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
        return

    include_kw = _parse_keywords(cities.data[0].get("include_keywords"))
    exclude_kw = _parse_keywords(cities.data[0].get("exclude_keywords"))

    if include_kw or exclude_kw:
        print(f"[ENGINE] Filtres: include={include_kw}, exclude={exclude_kw}")

    total_niche = 0

    for camp in cities.data:
        if total_niche >= TARGET_PER_NICHE:
            print(f"[ENGINE] Objectif {TARGET_PER_NICHE} atteint pour '{niche}'")
            break

        inserted = _scrape_city(sb, niche, camp["city"], camp["id"], include_kw, exclude_kw)
        total_niche += inserted
        print(f"[ENGINE] Total {niche}: {total_niche}/{TARGET_PER_NICHE}")

    send_discord(
        f"[TERMINÉ] **{niche}** : {total_niche} leads scrapés sur {len(cities.data)} villes"
    )
    print(f"[ENGINE] FINI — {niche}: {total_niche} leads")


if __name__ == "__main__":
    main()

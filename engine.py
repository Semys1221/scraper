import os
import sys
import uuid
import time
import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
from config import (
    get_supabase,
    OUTSCRAPER_API_KEY,
    OUTSCRAPER_API_BASE,
    send_discord,
    create_smartlead_campaign,
    push_to_smartlead,
)

BATCH_SIZE = 500
TARGET_PER_NICHE = 20_000
RETRY_DELAY = 10
MAX_CONCURRENT = 3
POLL_INTERVAL = 60

GENERIC_PREFIXES = {
    "contact", "info", "hello", "bonjour", "team", "mail",
    "admin", "support", "sales", "help", "noreply", "no-reply",
    "marketing", "press", "blog", "jobs", "recruitment",
}


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


def _extract_first_name(email: str) -> str:
    local = email.split("@")[0]
    for sep in [".", "-", "_"]:
        if sep in local:
            candidate = local.split(sep)[0].strip().capitalize()
            if candidate and len(candidate) > 1 and candidate.lower() not in GENERIC_PREFIXES:
                return candidate
    return ""


def _is_generic(email: str) -> bool:
    local = email.split("@")[0].lower().strip()
    return local in GENERIC_PREFIXES or not local


def _clean_and_push(sb, queue_id: str, smartlead_campaign_id: int | None):
    """Clean raw leads for the given city, push to Smartlead, update status."""
    raw = (
        sb.table("leads")
        .select("place_id, email, phone, first_name")
        .eq("campaign_queue_id", queue_id)
        .eq("status", "raw")
        .execute()
    )

    if not raw.data:
        return

    cleaned = []
    for lead in raw.data:
        email = lead["email"]
        if _is_generic(email):
            continue

        first_name = _extract_first_name(email)
        domain = email.split("@")[1] if "@" in email else ""

        sb.table("leads").update({
            "first_name": first_name,
            "domain": domain,
            "status": "cleaned",
            "valid": True,
        }).eq("place_id", lead["place_id"]).execute()

        cleaned.append(lead)

    if not cleaned:
        return

    if smartlead_campaign_id:
        success, fail = push_to_smartlead(smartlead_campaign_id, cleaned)
        if success > 0:
            emails = [l["email"] for l in cleaned[:success]]
            for i in range(0, len(emails), 100):
                batch = emails[i:i + 100]
                sb.table("leads").update({"status": "imported_smartlead"}).in_("email", batch).execute()
            print(f"[ENGINE] {success} leads poussés Smartlead")
        if fail > 0:
            print(f"[ENGINE] {fail} échecs Smartlead")


def _scrape_city(sb, niche, city, queue_id, include_kw, exclude_kw, smartlead_campaign_id):
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
            print(f"[ENGINE] 0 résultats à offset {offset}, ville épuisée")
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

    # Après le scraping, nettoyer et pusher vers Smartlead
    _clean_and_push(sb, queue_id, smartlead_campaign_id)

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

    # S'assurer que la campagne Smartlead existe
    smartlead_campaign_id = cities.data[0].get("smartlead_campaign_id")
    if not smartlead_campaign_id:
        templates_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "email_templates.json")
        if os.path.exists(templates_path):
            with open(templates_path) as f:
                templates = json.load(f)
            variants = templates.get("variants", [])
            campaign_name = f"{niche} — Phase {cities.data[0].get('batch', 1)}"
            print(f"[ENGINE] Création campagne Smartlead: {campaign_name}")
            cid = create_smartlead_campaign(campaign_name, variants)
            if cid:
                smartlead_campaign_id = cid
                sb.table("campaign_queue").update({"smartlead_campaign_id": cid}).eq("niche", niche).execute()
                print(f"[ENGINE] Smartlead campaign ID: {cid}")
            else:
                print(f"[ENGINE] ❌ Échec création campagne Smartlead pour {niche}")

    total = 0
    for camp in cities.data:
        if total >= TARGET_PER_NICHE:
            print(f"[ENGINE] Objectif {TARGET_PER_NICHE} atteint pour '{niche}'")
            break
        inserted = _scrape_city(sb, niche, camp["city"], camp["id"], include_kw, exclude_kw, smartlead_campaign_id)
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
            .execute()
        )

        niches = sorted(set(r["niche"] for r in result.data)) if result.data else []

        if not niches:
            print(f"[ENGINE] Aucune niche pending. Nouvelle vérification dans {POLL_INTERVAL}s")
            time.sleep(POLL_INTERVAL)
            continue

        print(f"[ENGINE] Niches à traiter: {niches}")

        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as executor:
            futures = {executor.submit(_scrape_niche, n): n for n in niches}
            for future in as_completed(futures):
                n = futures[future]
                try:
                    total = future.result()
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

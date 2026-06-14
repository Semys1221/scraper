import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
from config import (
    get_supabase,
    OUTSCRAPER_API_KEY,
    OUTSCRAPER_API_BASE,
    create_smartlead_campaign,
    send_discord,
)

CLEANER_WEBHOOK_BASE = os.getenv("CLEANER_WEBHOOK_BASE", "http://localhost:8001")

TEMPLATES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "email_templates.json")


def _load_templates() -> dict | None:
    if not os.path.exists(TEMPLATES_PATH):
        print("[ENGINE] email_templates.json introuvable")
        return None
    with open(TEMPLATES_PATH) as f:
        return json.load(f)


def _render_template(text: str, vars: dict) -> str:
    for key, val in vars.items():
        text = text.replace("{{" + key + "}}", str(val))
    return text


def main():
    sb = get_supabase()

    result = (
        sb.table("campaign_queue")
        .select("*")
        .eq("status", "pending")
        .limit(1)
        .execute()
    )

    if not result.data:
        print("[ENGINE] Aucune campagne pending trouvée.")
        return

    campaign = result.data[0]
    queue_id = campaign["id"]
    niche = campaign["niche"]
    city = campaign["city"]

    print(f"[ENGINE] Campagne trouvée : {niche} / {city} (id={queue_id})")

    # 1. Créer la campagne Smartlead (3 variantes A/B/C)
    templates = _load_templates()
    smartlead_campaign_id = None

    if templates and templates.get("variants"):
        template_vars = {
            "niche_target": campaign.get("niche_target") or niche,
            "city": city,
            "objective": campaign.get("objective", ""),
            "timeframe": campaign.get("timeframe", ""),
            "constraint": campaign.get("constraint_", ""),
            "first_name": "Prénom",
            "custom_intro": "vous contacter",
        }

        campaign_name = _render_template(
            templates.get("campaign_name", "{{niche_target}} — {{city}}"),
            template_vars,
        )

        variants = []
        for variant in templates["variants"]:
            rendered_steps = []
            for step in variant["steps"]:
                rendered_steps.append({
                    "day": step["day"],
                    "subject": _render_template(step.get("subject", ""), template_vars),
                    "body": _render_template(step["body"], template_vars),
                })
            variants.append({
                "name": variant["name"],
                "steps": rendered_steps,
            })

        smartlead_campaign_id = create_smartlead_campaign(campaign_name, variants)
        if smartlead_campaign_id:
            print(f"[ENGINE] Campagne Smartlead créée (id={smartlead_campaign_id}) avec {len(variants)} variantes")
            sb.table("campaign_queue").update({
                "smartlead_campaign_id": smartlead_campaign_id,
            }).eq("id", queue_id).execute()
        else:
            print("[ENGINE] Échec création campagne Smartlead")
            send_discord(f"[ERREUR] Échec création Smartlead pour {niche}/{city}")

    # 2. Lancer le scraping Outscraper
    webhook_url = f"{CLEANER_WEBHOOK_BASE}/webhook/outscraper?queue_id={queue_id}"
    params = {
        "query": f"{niche} {city}",
        "limit": 100,
        "language": "fr",
        "enrichment": "contacts_n_leads",
        "webhook": webhook_url,
    }

    resp = requests.get(
        f"{OUTSCRAPER_API_BASE}/maps/search-v2",
        params=params,
        headers={"X-API-KEY": OUTSCRAPER_API_KEY},
        timeout=30,
    )

    if resp.status_code == 429:
        print("[ENGINE] Rate limited (429). Réessaie plus tard.")
        return

    if resp.status_code not in (200, 202):
        print(f"[ENGINE] Erreur Outscraper {resp.status_code}: {resp.text[:200]}")
        send_discord(f"[ERREUR] Échec lancement scraping {niche}/{city} (HTTP {resp.status_code})")
        return

    # 3. Passer la campagne en scraping
    sb.table("campaign_queue").update({"status": "scraping"}).eq("id", queue_id).execute()

    print(f"[ENGINE] Scraping lancé pour {niche} / {city}")
    smartlead_msg = f" (Smartlead ID: {smartlead_campaign_id})" if smartlead_campaign_id else ""
    send_discord(f"[DÉBUT] Scraping lancé pour **{niche}** à **{city}**{smartlead_msg}")


if __name__ == "__main__":
    main()

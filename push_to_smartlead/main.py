import os
import sys
import time
import logging

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from database.config import get_supabase, push_to_smartlead, send_discord

logging.basicConfig(level=logging.INFO, format="%(asctime)s [PUSH] %(message)s")
log = logging.getLogger(__name__)

BATCH_SIZE = 100
POLL_INTERVAL = 30


def push_cleaned_leads():
    sb = get_supabase()

    raw = (
        sb.table("leads")
        .select("id, place_id, email, phone, first_name, campaign_queue_id, niche")
        .eq("status", "cleaned")
        .eq("valid", True)
        .limit(BATCH_SIZE)
        .execute()
    )

    if not raw.data:
        return 0

    leads = []
    for lead in raw.data:
        entry = {
            "email": lead["email"],
            "first_name": lead.get("first_name", ""),
            "phone": lead.get("phone", ""),
            "custom_fields": {
                "lead_id": lead.get("id", ""),
                "lead_niche": lead.get("niche", ""),
            },
        }
        leads.append(entry)

    smartlead_id = None
    if leads[0].get("campaign_queue_id"):
        camp = (
            sb.table("campaign_queue")
            .select("smartlead_campaign_id")
            .eq("id", leads[0]["campaign_queue_id"])
            .single()
            .execute()
            .data
        )
        if camp:
            smartlead_id = camp.get("smartlead_campaign_id")

    if not smartlead_id:
        log.warning("Aucun smartlead_campaign_id trouvé pour ce batch")
        for lead in raw.data:
            sb.table("leads").update({"status": "excluded"}).eq("place_id", lead["place_id"]).execute()
        return 0

    success, fail = push_to_smartlead(smartlead_id, leads)

    if success > 0:
        emails = [l["email"] for l in leads[:success]]
        for i in range(0, len(emails), 100):
            batch = emails[i:i + 100]
            try:
                sb.table("leads").update({"status": "imported_smartlead"}).in_("email", batch).execute()
            except Exception as e:
                log.error("Erreur update imported_smartlead: %s", e)
        log.info("%s leads poussés Smartlead (campagne %s)", success, smartlead_id)

    if fail > 0:
        log.warning("%s échecs Smartlead", fail)

    return success


def main():
    log.info("Push Smartlead démarré")

    while True:
        try:
            pushed = push_cleaned_leads()
            if pushed == 0:
                time.sleep(POLL_INTERVAL)
        except Exception as e:
            log.error("Erreur dans le cycle: %s", e)
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()

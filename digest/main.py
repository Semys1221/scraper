import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from database.config import get_supabase, send_discord


def _since() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()


def main():
    sb = get_supabase()
    since = _since()
    date_str = datetime.now(timezone.utc).strftime("%d/%m/%Y")

    raw_count = (
        sb.table("leads")
        .select("*", count="exact", head=True)
        .gte("created_at", since)
        .execute()
    ).count

    cleaned_count = (
        sb.table("leads")
        .select("*", count="exact", head=True)
        .gte("created_at", since)
        .eq("status", "cleaned")
        .execute()
    ).count

    imported_count = (
        sb.table("leads")
        .select("*", count="exact", head=True)
        .gte("created_at", since)
        .eq("status", "imported_smartlead")
        .execute()
    ).count

    pending_count = (
        sb.table("campaign_queue")
        .select("*", count="exact", head=True)
        .eq("status", "pending")
        .execute()
    ).count

    new_campaigns = (
        sb.table("campaign_queue")
        .select("*", count="exact", head=True)
        .gte("created_at", since)
        .execute()
    ).count

    killed_count = (
        sb.table("campaign_queue")
        .select("*", count="exact", head=True)
        .eq("status", "killed")
        .execute()
    ).count

    active_count = (
        sb.table("campaign_queue")
        .select("*", count="exact", head=True)
        .eq("status", "active")
        .execute()
    ).count

    total_leads = (
        sb.table("leads")
        .select("*", count="exact", head=True)
        .execute()
    ).count

    message = (
        f"📊 **Rapport Matinal — {date_str}**\n\n"
        f"**Leads (24h)**\n"
        f"┣ Bruts reçus : `{raw_count}`\n"
        f"┣ Nettoyés : `{cleaned_count}`\n"
        f"┗ Importés Smartlead : `{imported_count}`\n\n"
        f"**Campagnes**\n"
        f"┣ Créées (24h) : `{new_campaigns}`\n"
        f"┣ En attente : `{pending_count}`\n"
        f"┣ Actives : `{active_count}`\n"
        f"┗ Tuées : `{killed_count}`\n\n"
        f"**Stock**\n"
        f"┗ Total leads en base : `{total_leads}`"
    )

    print(message)
    send_discord(message)


if __name__ == "__main__":
    main()

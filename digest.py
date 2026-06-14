import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import get_supabase, send_discord


def _since() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()


def main():
    sb = get_supabase()
    since = _since()
    date_str = datetime.now(timezone.utc).strftime("%d/%m/%Y")

    # 1. Leads bruts reçus (raw)
    raw_count = (
        sb.table("leads")
        .select("*", count="exact", head=True)
        .gte("created_at", since)
        .execute()
    ).count

    # 2. Leads nettoyés (cleaned dans les dernières 24h)
    cleaned_count = (
        sb.table("leads")
        .select("*", count="exact", head=True)
        .gte("created_at", since)
        .eq("status", "cleaned")
        .execute()
    ).count

    # 3. Leads importés Smartlead
    imported_count = (
        sb.table("leads")
        .select("*", count="exact", head=True)
        .gte("created_at", since)
        .eq("status", "imported_smartlead")
        .execute()
    ).count

    # 4. Campagnes créées en attente (pending)
    pending_count = (
        sb.table("campaign_queue")
        .select("*", count="exact", head=True)
        .eq("status", "pending")
        .execute()
    ).count

    # 5. Campagnes créées récemment (last 24h)
    new_campaigns = (
        sb.table("campaign_queue")
        .select("*", count="exact", head=True)
        .gte("created_at", since)
        .execute()
    ).count

    # 6. Campagnes tuées par judge
    killed_count = (
        sb.table("campaign_queue")
        .select("*", count="exact", head=True)
        .eq("status", "killed")
        .execute()
    ).count

    # 7. Campagnes actives en cours
    active_count = (
        sb.table("campaign_queue")
        .select("*", count="exact", head=True)
        .eq("status", "active")
        .execute()
    ).count

    # 8. Total leads en base
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

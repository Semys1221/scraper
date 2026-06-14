import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    get_supabase,
    send_discord,
    get_smartlead_analytics,
    pause_smartlead_campaign,
)

TRUE_REPLY_THRESHOLD = 2.0
MIN_VOLUME = 100


def main():
    sb = get_supabase()

    result = (
        sb.table("campaign_queue")
        .select("*")
        .eq("status", "active")
        .execute()
    )

    if not result.data:
        print("[JUGE] Aucune campagne active à auditer.")
        return

    campaigns = result.data
    print(f"[JUGE] Audit de {len(campaigns)} campagne(s) active(s)...")

    killed = 0

    for campaign in campaigns:
        queue_id = campaign["id"]
        niche = campaign["niche"]
        city = campaign["city"]
        smartlead_id = campaign.get("smartlead_campaign_id")

        if not smartlead_id:
            print(f"[JUGE] Campagne {niche}/{city} : pas de smartlead_campaign_id, ignorée")
            continue

        analytics = get_smartlead_analytics(smartlead_id)
        if not analytics:
            print(f"[JUGE] Campagne {niche}/{city} : analytics vides, ignorée")
            continue

        total_sent = int(analytics.get("total_sent", 0) or 0)
        total_replies = int(analytics.get("total_replies", 0) or 0)
        auto_replies = int(analytics.get("auto_replies", 0) or 0)

        true_replies = total_replies - auto_replies
        true_reply_rate = (true_replies / total_sent * 100) if total_sent > 0 else 0.0

        print(
            f"[JUGE] {niche}/{city} : {total_sent} envoyés, "
            f"{true_replies} vraies réponses ({true_reply_rate:.2f}%)"
        )

        if total_sent >= MIN_VOLUME and true_reply_rate < TRUE_REPLY_THRESHOLD:
            print(f"[JUGE] → TUÉE ({true_reply_rate:.2f}% < {TRUE_REPLY_THRESHOLD}%)")

            pause_smartlead_campaign(smartlead_id)

            sb.table("campaign_queue").update({
                "status": "killed",
                "true_reply_rate": round(true_reply_rate, 2),
            }).eq("id", queue_id).execute()

            killed += 1

            send_discord(
                f"[JUDGE] Campagne **{niche}** à **{city}** tuée "
                f"(True Reply Rate: {true_reply_rate:.2f}%, volume: {total_sent})"
            )
        else:
            reason = "volume insuffisant" if total_sent < MIN_VOLUME else "taux OK"
            print(f"[JUGE] → OK ({reason})")

    if killed > 0:
        send_discord(
            f"[JUDGE] Audit terminé : **{killed}** campagne(s) tuée(s) sur {len(campaigns)} auditées"
        )
    print(f"[JUGE] Audit terminé. {killed}/{len(campaigns)} tuée(s).")


if __name__ == "__main__":
    main()

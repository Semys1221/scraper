import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, Request, HTTPException

from config import get_supabase, send_discord, push_to_smartlead

GENERIC_PREFIXES = {
    "contact", "info", "hello", "bonjour", "team", "mail",
    "admin", "support", "sales", "help", "noreply", "no-reply",
    "marketing", "press", "blog", "jobs", "recruitment",
}

app = FastAPI(title="Outreach Cleaner API", version="2.0.0")


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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/webhook/outscraper")
def webhook_outscraper(request: Request):
    queue_id = request.query_params.get("queue_id")
    if not queue_id:
        raise HTTPException(status_code=400, detail="queue_id requis")

    sb = get_supabase()

    try:
        body = request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="JSON invalide")

    campaign = (
        sb.table("campaign_queue")
        .select("*")
        .eq("id", queue_id)
        .single()
        .execute()
        .data
    )
    if not campaign:
        raise HTTPException(status_code=404, detail="Campagne introuvable")

    raw_data = body.get("data", [])
    if not raw_data:
        raw_data = body if isinstance(body, list) else (
            body.get("results") or body.get("places") or []
        )

    if not raw_data:
        send_discord(f"[ERREUR] Webhook reçu pour {queue_id} mais aucune donnée")
        return {"status": "skipped", "reason": "no_data", "leads": 0}

    # Étape 1 : insérer tous les leads en brut (raw)
    inserted = 0
    excluded = 0
    raw_leads = []

    for entry in raw_data:
        place_id = str(entry.get("place_id", entry.get("id", str(uuid.uuid4()))))
        email = (entry.get("email") or entry.get("email_1") or "").lower().strip()
        if not email:
            continue

        raw_leads.append({
            "place_id": place_id,
            "campaign_queue_id": queue_id,
            "email": email,
            "company_name": entry.get("name") or entry.get("company_name", ""),
            "phone": entry.get("phone", ""),
            "location": entry.get("full_address") or entry.get("location", ""),
            "niche": entry.get("niche", ""),
            "status": "raw",
            "metadata": {},
        })

    for lead in raw_leads:
        try:
            sb.table("leads").upsert(lead, on_conflict="place_id").execute()
            inserted += 1
        except Exception as e:
            err = str(e).lower()
            if "duplicate" in err or "23505" in err:
                excluded += 1
            else:
                print(f"[CLEANER] Erreur upsert {lead['email']}: {e}")

    # Étape 2 : nettoyage → statut "cleaned"
    cleaned_emails = []
    for lead in raw_leads:
        email = lead["email"]
        if _is_generic(email):
            continue

        first_name = _extract_first_name(email)
        domain = email.split("@")[1] if "@" in email else ""

        try:
            sb.table("leads").update({
                "first_name": first_name,
                "domain": domain,
                "status": "cleaned",
                "valid": True,
            }).eq("place_id", lead["place_id"]).execute()
            cleaned_emails.append(email)
        except Exception as e:
            print(f"[CLEANER] Erreur update clean {email}: {e}")

    smartlead_id = campaign.get("smartlead_campaign_id")
    imported = 0
    failed = 0

    if smartlead_id and cleaned_emails:
        cleaned_leads = [l for l in raw_leads if l["email"] in cleaned_emails]
        success, fail = push_to_smartlead(smartlead_id, cleaned_leads)
        imported = success
        failed = fail

        if success > 0:
            for i in range(0, len(cleaned_emails), 100):
                batch = cleaned_emails[i:i + 100]
                try:
                    sb.table("leads").update({"status": "imported_smartlead"}).in_("email", batch).execute()
                except Exception as e:
                    print(f"[CLEANER] Erreur update status: {e}")

    new_status = "active" if imported > 0 else "paused"
    sb.table("campaign_queue").update({"status": new_status}).eq("id", queue_id).execute()

    if imported > 0:
        send_discord(
            f"[SUCCÈS] Campagne **{queue_id[:8]}** : {inserted} leads bruts, "
            f"{len(cleaned_emails)} nettoyés, {imported} poussés Smartlead"
        )
    else:
        send_discord(
            f"[INFO] Campagne **{queue_id[:8]}** : {inserted} leads bruts, "
            f"{len(cleaned_emails)} nettoyés, 0 poussés Smartlead"
        )

    return {
        "status": "ok",
        "leads_received": len(raw_data),
        "leads_inserted_raw": inserted,
        "excluded_doublons": excluded,
        "leads_cleaned": len(cleaned_emails),
        "imported_smartlead": imported,
        "failed_smartlead": failed,
        "campaign_status": new_status,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("cleaner_api:app", host="0.0.0.0", port=8001)

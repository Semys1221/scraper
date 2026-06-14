import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
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


def _clean_leads(raw_data: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(raw_data)
    if df.empty:
        return df

    email_col = next((c for c in ["email", "email_1"] if c in df.columns), None)
    if not email_col:
        return pd.DataFrame()

    df["email"] = df[email_col].astype(str).str.lower().str.strip()
    df = df[df["email"].notna() & (df["email"] != "")]
    df = df[~df["email"].apply(_is_generic)]

    if "place_id" in df.columns:
        df = df.drop_duplicates(subset=["place_id"], keep="first")
    else:
        df = df.drop_duplicates(subset=["email"], keep="first")

    df["first_name"] = df["email"].apply(_extract_first_name)

    df["custom_intro"] = df.apply(
        lambda row: (
            f"vous appeler au {row['phone']}"
            if pd.notna(row.get("phone")) and str(row.get("phone", "")).strip()
            else "vous joindre directement"
        ),
        axis=1,
    )

    return df


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

    df = _clean_leads(raw_data)
    if df.empty:
        send_discord(f"[ERREUR] Webhook reçu pour {queue_id} mais 0 leads après nettoyage")
        return {"status": "skipped", "reason": "all_filtered", "leads": 0}

    campaign_vars = {
        "niche_target": campaign.get("niche_target") or campaign.get("niche", ""),
        "objective": campaign.get("objective", ""),
        "timeframe": campaign.get("timeframe", ""),
        "constraint": campaign.get("constraint_", ""),
    }

    cleaned = []
    for _, row in df.iterrows():
        place_id = str(row.get("place_id", row.get("id", str(uuid.uuid4()))))
        email = row["email"]

        cleaned.append({
            "place_id": place_id,
            "campaign_queue_id": queue_id,
            "email": email,
            "first_name": row.get("first_name", ""),
            "company_name": row.get("name") or row.get("company_name", ""),
            "domain": email.split("@")[1] if "@" in email else "",
            "phone": row.get("phone", ""),
            "location": row.get("full_address") or row.get("location", ""),
            "niche": row.get("niche", ""),
            "status": "cleaned",
            "metadata": {},
            "custom_fields": {
                "custom_intro": row.get("custom_intro", "vous joindre directement"),
                "niche_target": campaign_vars["niche_target"],
                "objective": campaign_vars["objective"],
                "timeframe": campaign_vars["timeframe"],
                "constraint": campaign_vars["constraint"],
            },
        })

    inserted = 0
    excluded = 0
    for lead in cleaned:
        try:
            sb.table("leads").upsert(lead, on_conflict="place_id").execute()
            inserted += 1
        except Exception as e:
            err = str(e).lower()
            if "duplicate" in err or "23505" in err:
                excluded += 1
            else:
                print(f"[CLEANER] Erreur upsert {lead['email']}: {e}")

    smartlead_id = campaign.get("smartlead_campaign_id")
    imported = 0
    failed = 0

    if smartlead_id:
        success, fail = push_to_smartlead(smartlead_id, cleaned)
        imported = success
        failed = fail

        if success > 0:
            emails = [l["email"] for l in cleaned[:success]]
            for i in range(0, len(emails), 100):
                batch = emails[i:i + 100]
                try:
                    sb.table("leads").update({"status": "imported_smartlead"}).in_("email", batch).execute()
                except Exception as e:
                    print(f"[CLEANER] Erreur update status: {e}")

    new_status = "active" if imported > 0 else "paused"
    sb.table("campaign_queue").update({"status": new_status}).eq("id", queue_id).execute()

    if imported > 0:
        send_discord(
            f"[SUCCÈS] Campagne **{queue_id[:8]}** : {inserted} leads nettoyés, "
            f"{imported} poussés Smartlead (target: {campaign_vars['niche_target']})"
        )
    else:
        send_discord(
            f"[ERREUR] Campagne **{queue_id[:8]}** : {inserted} leads nettoyés "
            f"mais 0 poussés Smartlead"
        )

    return {
        "status": "ok",
        "leads_received": len(raw_data),
        "leads_after_cleaning": len(cleaned),
        "inserted": inserted,
        "excluded_doublons": excluded,
        "imported_smartlead": imported,
        "failed_smartlead": failed,
        "campaign_status": new_status,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("cleaner_api:app", host="0.0.0.0", port=8001)

import os
import json
import datetime
import unicodedata
import re

from supabase import create_client


def _normalize_name(name: str) -> str:
    nfkd = unicodedata.normalize("NFKD", name)
    no_accents = nfkd.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", no_accents).strip().lower()

_SUPABASE = None


def _load_env():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())


_load_env()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
OUTSCRAPER_API_KEY = os.getenv("OUTSCRAPER_API_KEY", "")
SMARTLEAD_API_KEY = os.getenv("SMARTLEAD_API_KEY", "")
SMARTLEAD_API_BASE = "https://server.smartlead.ai/api/v1"
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
OUTSCRAPER_API_BASE = "https://api.outscraper.com"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")


def get_supabase():
    global _SUPABASE
    if _SUPABASE is None:
        _SUPABASE = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    return _SUPABASE


import requests


def send_discord(message: str):
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": message}, timeout=10)
    except Exception:
        pass


def create_smartlead_campaign(name: str, variants: list[dict]) -> int | None:
    if not SMARTLEAD_API_KEY or not variants:
        return None

    resp = requests.post(
        f"{SMARTLEAD_API_BASE}/campaigns/create",
        params={"api_key": SMARTLEAD_API_KEY},
        json={"name": name},
        timeout=15,
    )

    if resp.status_code != 200:
        return None

    campaign_id = resp.json().get("id")
    if not campaign_id:
        return None

    sequences = []
    for v in variants:
        sequences.append({
            "name": f"Variante {v.get('name', '')}",
            "steps": [
                {
                    "day": s["day"],
                    "subject": s.get("subject", ""),
                    "body": s["body"],
                }
                for s in v["steps"]
            ],
        })

    requests.post(
        f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/sequences",
        params={"api_key": SMARTLEAD_API_KEY},
        json={"sequences": sequences},
        timeout=15,
    )

    return campaign_id


def push_to_smartlead(campaign_id: int, leads: list[dict]) -> tuple[int, int]:
    if not SMARTLEAD_API_KEY or not leads:
        return 0, 0

    lead_list = []
    for l in leads:
        entry = {
            "email": l["email"],
            "first_name": l.get("first_name", ""),
            "last_name": l.get("last_name", ""),
            "phone_number": l.get("phone", ""),
        }
        custom = l.get("custom_fields")
        if custom:
            entry["custom_fields"] = custom
        lead_list.append(entry)

    resp = requests.post(
        f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/leads",
        params={"api_key": SMARTLEAD_API_KEY},
        json={"lead_list": lead_list},
        timeout=30,
    )

    if resp.status_code == 200:
        data = resp.json()
        return data.get("success_count", len(leads)), data.get("fail_count", 0)
    return 0, len(leads)


def get_smartlead_analytics(campaign_id: int) -> dict:
    if not SMARTLEAD_API_KEY:
        return {}

    resp = requests.get(
        f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/analytics",
        params={"api_key": SMARTLEAD_API_KEY},
        timeout=15,
    )

    if resp.status_code == 200:
        return resp.json()
    return {}


def update_smartlead_sequences(campaign_id: int, variants: list[dict]) -> bool:
    if not SMARTLEAD_API_KEY:
        return False
    sequences = [
        {
            "name": f"Variante {v.get('name', '')}",
            "steps": [
                {"day": s["day"], "subject": s.get("subject", ""), "body": s["body"]}
                for s in v["steps"]
            ],
        }
        for v in variants
    ]
    resp = requests.post(
        f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/sequences",
        params={"api_key": SMARTLEAD_API_KEY},
        json={"sequences": sequences},
        timeout=15,
    )
    return resp.status_code == 200


def list_smartlead_campaigns() -> list:
    if not SMARTLEAD_API_KEY:
        return []
    resp = requests.get(
        f"{SMARTLEAD_API_BASE}/campaigns/",
        params={"api_key": SMARTLEAD_API_KEY},
        timeout=15,
    )
    if resp.status_code == 200:
        data = resp.json()
        return data if isinstance(data, list) else []
    return []


def get_smartlead_campaign_by_name(name: str) -> int | None:
    target = _normalize_name(name)
    for c in list_smartlead_campaigns():
        if _normalize_name(c.get("name", "")) == target:
            return c.get("id")
    return None


def get_smartlead_sequences(campaign_id: int) -> list:
    if not SMARTLEAD_API_KEY:
        return []
    resp = requests.get(
        f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/sequences",
        params={"api_key": SMARTLEAD_API_KEY},
        timeout=15,
    )
    if resp.status_code == 200:
        data = resp.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("sequences", data.get("data", []))
    return []


def get_smartlead_email_accounts(campaign_id: int) -> list[int]:
    if not SMARTLEAD_API_KEY:
        return []
    resp = requests.get(
        f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/email-accounts",
        params={"api_key": SMARTLEAD_API_KEY},
        timeout=15,
    )
    if resp.status_code == 200:
        data = resp.json()
        if isinstance(data, list):
            return [a.get("id") for a in data if a.get("id")]
        if isinstance(data, dict):
            return [a.get("id") for a in data.get("data", data.get("email_accounts", [])) if a.get("id")]
    return []


def duplicate_smartlead_campaign(source_id: int, new_name: str) -> int | None:
    if not SMARTLEAD_API_KEY:
        return None
    resp = requests.post(
        f"{SMARTLEAD_API_BASE}/campaigns/create",
        params={"api_key": SMARTLEAD_API_KEY},
        json={"name": new_name},
        timeout=15,
    )
    if resp.status_code != 200:
        return None
    new_id = resp.json().get("id")
    if not new_id:
        return None
    sequences = get_smartlead_sequences(source_id)
    if sequences:
        requests.post(
            f"{SMARTLEAD_API_BASE}/campaigns/{new_id}/sequences",
            params={"api_key": SMARTLEAD_API_KEY},
            json={"sequences": sequences},
            timeout=15,
        )
    email_ids = get_smartlead_email_accounts(source_id)
    if email_ids:
        requests.post(
            f"{SMARTLEAD_API_BASE}/campaigns/{new_id}/email-accounts",
            params={"api_key": SMARTLEAD_API_KEY},
            json={"email_account_ids": email_ids},
            timeout=15,
        )
    return new_id


def get_or_create_smartlead_campaign(niche: str) -> int | None:
    existing = get_smartlead_campaign_by_name(niche)
    if existing:
        return existing
    model_id = get_smartlead_campaign_by_name("model campaign") or get_smartlead_campaign_by_name("Campaign Model")
    if not model_id:
        return None
    return duplicate_smartlead_campaign(model_id, niche)


def save_campaign_analytics(campaign_id: int, data: dict) -> bool:
    if not SMARTLEAD_API_KEY:
        return False
    try:
        sb = get_supabase()
        today = str(datetime.date.today())
        payload = {
            "smartlead_campaign_id": campaign_id,
            "campaign_name": data.get("campaign_name", ""),
            "snapshot_date": today,
            "total_sent": data.get("total_sent", 0),
            "total_opened": data.get("total_opened", 0),
            "total_clicked": data.get("total_clicked", 0),
            "total_replied": data.get("total_replied", 0) or data.get("total_replies", 0),
            "open_rate": data.get("open_rate", 0),
            "click_rate": data.get("click_rate", 0),
            "reply_rate": data.get("reply_rate", 0),
            "bounce_rate": data.get("bounce_rate", 0),
            "unsubscribe_rate": data.get("unsubscribe_rate", 0),
            "raw": data,
        }
        sb.table("campaign_analytics").upsert(payload, on_conflict="smartlead_campaign_id,snapshot_date").execute()
        return True
    except Exception:
        return False


def pause_smartlead_campaign(campaign_id: int) -> bool:
    if not SMARTLEAD_API_KEY:
        return False

    resp = requests.put(
        f"{SMARTLEAD_API_BASE}/campaigns/{campaign_id}/status",
        params={"api_key": SMARTLEAD_API_KEY},
        json={"status": "pause"},
        timeout=15,
    )

    return resp.status_code == 200

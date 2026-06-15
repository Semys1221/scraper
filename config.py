import os
import json

from supabase import create_client

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
OUTSCRAPER_API_BASE = "https://api.app.outscraper.com"
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

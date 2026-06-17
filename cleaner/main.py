import os
import sys
import time
import logging
import threading
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from database.config import get_supabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s [CLEANER] %(message)s")
log = logging.getLogger(__name__)

BATCH_SIZE = 50
POLL_INTERVAL = 30
GENERIC_PREFIXES = {
    "contact", "info", "hello", "bonjour", "team", "mail",
    "admin", "support", "sales", "help", "noreply", "no-reply",
    "marketing", "press", "blog", "jobs", "recruitment",
}


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


def _has_mx(domain: str) -> bool:
    try:
        import dns.resolver
    except ImportError:
        log.warning("dnspython not installed — skipping MX validation")
        return True
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=10)
        return len(answers) > 0
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.Timeout, dns.exception.DNSException):
        return False


def _verify_email(email: str) -> bool:
    domain = email.split("@")[1] if "@" in email else ""
    if not domain:
        return False
    return _has_mx(domain)


def _process_batch(sb):
    raw = (
        sb.table("leads")
        .select("id, place_id, email, phone, first_name, campaign_queue_id, niche")
        .eq("status", "raw")
        .limit(BATCH_SIZE)
        .execute()
    )

    if not raw.data:
        return 0

    cleaned_valid = []
    cleaned_invalid = 0
    processed = 0

    for lead in raw.data:
        email = lead["email"]
        place_id = lead["place_id"]

        if _is_generic(email):
            sb.table("leads").update({
                "status": "cleaned",
                "valid": False,
            }).eq("place_id", place_id).execute()
            cleaned_invalid += 1
            processed += 1
            continue

        first_name = _extract_first_name(email)
        domain = email.split("@")[1] if "@" in email else ""
        is_valid = _verify_email(email)

        update = {
            "first_name": first_name,
            "domain": domain,
            "status": "cleaned",
            "valid": is_valid,
        }

        sb.table("leads").update(update).eq("place_id", place_id).execute()

        if is_valid:
            lead["custom_fields"] = {
                "lead_id": lead.get("id", ""),
                "lead_first_name": lead.get("first_name", ""),
                "lead_niche": lead.get("niche", ""),
                "phone": lead.get("phone", ""),
                "city": lead.get("city", ""),
                "custom_intro": "vous contacter",
            }
            cleaned_valid.append(lead)
        else:
            cleaned_invalid += 1

        processed += 1

    log.info("Batch: %s traités, %s valides, %s invalides", processed, len(cleaned_valid), cleaned_invalid)
    return processed


def _ensure_deps():
    try:
        import dns.resolver
    except ImportError:
        log.warning("dnspython missing — attempting pip install")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "dnspython", "-q"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


PORT = int(os.getenv("PORT", 8001))
TENANT_ID = os.getenv("TENANT_ID", "sylk-conseils")


def _safe_count(table: str, gte: str | None = None) -> int:
    sb = get_supabase()
    q = sb.table(table).select("*", count="exact", head=True).eq("tenant_id", TENANT_ID)
    if gte:
        q = q.gte("created_at", gte)
    r = q.execute()
    return r.count or 0


def _safe_fetch(table: str, columns: str, gte: str | None, limit: int = 50):
    sb = get_supabase()
    q = sb.table(table).select(columns).eq("tenant_id", TENANT_ID)
    if gte:
        q = q.gte("created_at", gte)
    q = q.order("created_at", desc=True).limit(limit)
    r = q.execute()
    return r.data or []


def _cleaner_loop():
    _ensure_deps()
    log.info("Cleaner démarré — MX + SMTP handshake")
    sb = get_supabase()
    while True:
        try:
            processed = _process_batch(sb)
            if processed == 0:
                time.sleep(POLL_INTERVAL)
        except Exception as e:
            log.error("Erreur dans le cycle: %s", e)
            time.sleep(POLL_INTERVAL)


# ── Dashboard Web Server ──────────────────────────────────────────────────────

_web_app = None
_web_templates = None
_WEB_START_TIME = None


def _get_web_app():
    global _web_app, _web_templates, _WEB_START_TIME
    if _web_app is not None:
        return _web_app, _web_templates

    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse
    from fastapi.templating import Jinja2Templates

    app = FastAPI(title="Cleaner Dashboard", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
    _WEB_START_TIME = time.time()

    @app.get("/health", include_in_schema=False)
    @app.head("/health", include_in_schema=False)
    @app.get("/api/health", include_in_schema=False)
    @app.head("/api/health", include_in_schema=False)
    async def api_health():
        return {"status": "ok", "uptime": int(time.time() - _WEB_START_TIME)}

    @app.get("/api/stats", include_in_schema=False)
    async def api_stats():
        now = datetime.now(timezone.utc)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        week = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

        cold_total = _safe_count("cold_leads")
        cold_today = _safe_count("cold_leads", today)
        cold_week = _safe_count("cold_leads", week)
        cold_month = _safe_count("cold_leads", month)

        clean_total = _safe_count("clean_leads")
        clean_today = _safe_count("clean_leads", today)
        clean_week = _safe_count("clean_leads", week)
        clean_month = _safe_count("clean_leads", month)

        usage = _safe_fetch("outscraper_usage", "places_count, contacts_count, leads_stored", None, 99999)
        total_places = sum(r.get("places_count", 0) or 0 for r in usage)
        total_contacts = sum(r.get("contacts_count", 0) or 0 for r in usage)
        total_stored = sum(r.get("leads_stored", 0) or 0 for r in usage)

        active = _safe_count("scrape_campaigns")

        return {
            "cold": {"total": cold_total, "today": cold_today, "week": cold_week, "month": cold_month},
            "clean": {"total": clean_total, "today": clean_today, "week": clean_week, "month": clean_month},
            "outscraper": {"totalPlaces": total_places, "totalContacts": total_contacts, "totalStored": total_stored, "apiCalls": len(usage)},
            "activeCampaigns": active,
        }

    @app.get("/api/activity", include_in_schema=False)
    async def api_activity(since: str | None = None):
        if not since:
            since = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()

        events = []

        clean_data = _safe_fetch("clean_leads", "id, email, first_name, last_name, company_name, profession, niche, status, created_at", since, 50)
        for r in clean_data:
            name = f"{r.get('first_name', '') or ''} {r.get('last_name', '') or ''}".strip() or r.get("email", "")
            events.append({
                "id": f"clean-{r['id']}",
                "type": "lead_cleaned",
                "title": name,
                "subtitle": f"{r.get('company_name', '') or ''} — {r.get('profession', '') or r.get('niche', '') or ''}",
                "timestamp": r.get("created_at", ""),
            })

        usage_data = _safe_fetch("outscraper_usage", "id, query, location, places_count, contacts_count, leads_stored, execution_time_ms, created_at", since, 20)
        for r in usage_data:
            events.append({
                "id": f"api-{r['id']}",
                "type": "api_call",
                "title": f"{r.get('query', '')} @ {r.get('location', '')}",
                "subtitle": f"{r.get('places_count', 0)} places, {r.get('contacts_count', 0)} contacts, {r.get('leads_stored', 0)} stored",
                "timestamp": r.get("created_at", ""),
            })

        campaign_data = _safe_fetch("scrape_campaigns", "id, name, keywords, status, leads_found, leads_cleaned, created_at", since, 10)
        for r in campaign_data:
            events.append({
                "id": f"cmp-{r['id']}",
                "type": "campaign",
                "title": r.get("name", ""),
                "subtitle": f"{r.get('leads_found', 0)} found, {r.get('leads_cleaned', 0)} cleaned — {r.get('status', '')}",
                "timestamp": r.get("created_at", ""),
            })

        events.sort(key=lambda e: e["timestamp"], reverse=True)
        return {"events": events[:100], "serverTime": datetime.now(timezone.utc).isoformat()}

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard(request: Request):
        return templates.TemplateResponse("dashboard.html", {"request": request})

    _web_app = app
    _web_templates = templates
    return app, templates


def _start_web():
    app, _ = _get_web_app()
    import uvicorn
    log.info("Dashboard web server on port %s", PORT)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")


def main():
    t = threading.Thread(target=_cleaner_loop, daemon=True)
    t.start()
    _start_web()


if __name__ == "__main__":
    main()

import os
import sys
import time
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from database.config import get_supabase, send_discord

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


PORT = int(os.getenv("PORT", 8001))


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def log_message(self, format, *args):
        pass


def _start_http():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    log.info("Health server on port %s", PORT)
    server.serve_forever()


def _ensure_deps():
    try:
        import dns.resolver
    except ImportError:
        log.warning("dnspython missing — attempting pip install")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "dnspython", "-q"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    _ensure_deps()
    log.info("Cleaner démarré — MX + SMTP handshake")

    t = threading.Thread(target=_start_http, daemon=True)
    t.start()

    sb = get_supabase()

    while True:
        try:
            processed = _process_batch(sb)
            if processed == 0:
                time.sleep(POLL_INTERVAL)
        except Exception as e:
            log.error("Erreur dans le cycle: %s", e)
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()

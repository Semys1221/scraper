import os
import sys
import time
import smtplib
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dns.resolver
from config import get_supabase, push_to_smartlead, send_discord

logging.basicConfig(level=logging.INFO, format="%(asctime)s [CLEANER] %(message)s")
log = logging.getLogger(__name__)

BATCH_SIZE = 50
POLL_INTERVAL = 30
MAIL_FROM = "hello@montismedia.com"
SMTP_TIMEOUT = 10
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


def _check_mx(domain: str) -> list[str] | None:
    try:
        answers = dns.resolver.resolve(domain, "MX", lifetime=SMTP_TIMEOUT)
        mx_records = sorted(answers, key=lambda r: r.preference)
        return [str(r.exchange) for r in mx_records]
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.Timeout, dns.exception.DNSException):
        return None


def _smtp_verify(mx_host: str, email: str) -> bool:
    try:
        with smtplib.SMTP(mx_host, timeout=SMTP_TIMEOUT) as smtp:
            smtp.set_debuglevel(0)
            smtp.ehlo_or_helo_if_needed()
            smtp.mail(MAIL_FROM)
            code, _ = smtp.rcpt(email)
            return code == 250
    except (smtplib.SMTPException, OSError, ConnectionRefusedError, TimeoutError):
        return False


def _verify_email(email: str) -> bool:
    domain = email.split("@")[1] if "@" in email else ""
    if not domain:
        return False

    mx_list = _check_mx(domain)
    if not mx_list:
        return False

    for mx_host in mx_list[:3]:
        if _smtp_verify(mx_host, email):
            return True

    return False


def _process_batch(sb):
    raw = (
        sb.table("leads")
        .select("id, place_id, email, phone, first_name, campaign_queue_id")
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
                "phone": lead.get("phone", ""),
                "custom_intro": "vous contacter",
            }
            cleaned_valid.append(lead)
        else:
            cleaned_invalid += 1

        processed += 1

    if cleaned_valid:
        smartlead_id = None
        if cleaned_valid[0].get("campaign_queue_id"):
            camp = (
                sb.table("campaign_queue")
                .select("smartlead_campaign_id")
                .eq("id", cleaned_valid[0]["campaign_queue_id"])
                .single()
                .execute()
                .data
            )
            if camp:
                smartlead_id = camp.get("smartlead_campaign_id")

        if smartlead_id:
            success, fail = push_to_smartlead(smartlead_id, cleaned_valid)
            if success > 0:
                emails = [l["email"] for l in cleaned_valid[:success]]
                for i in range(0, len(emails), 100):
                    batch = emails[i:i + 100]
                    try:
                        sb.table("leads").update({"status": "imported_smartlead"}).in_("email", batch).execute()
                    except Exception as e:
                        log.error("Erreur update imported_smartlead: %s", e)
                log.info("%s leads poussés Smartlead", success)
            if fail > 0:
                log.warning("%s échecs Smartlead", fail)

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


def main():
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

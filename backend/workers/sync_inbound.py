"""sync_inbound.py — Gmail Pardot Form Handler emails -> Postgres.

Cron: 05:00 UTC daily.

Query:   from:info@pardot.com subject:"Pardot Form Handler"
Subject: Pardot Form Handler: <description> - <email>   (split on LAST ' - ')
Rules:
  - Only process messages whose From contains info@pardot.com (skip fwd/reply).
  - Segment defaults to 'Genuine' for unknown senders — never silently drop.
  - Internal domains -> segment 'Internal'.
  - Idempotent on gmail_message_id.
"""
import base64
import json
import os
import re
import sys
import pathlib
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from google.oauth2.credentials import Credentials   # noqa: E402
from googleapiclient.discovery import build          # noqa: E402

from db.connection import get_cursor, mark_sync      # noqa: E402

INTERNAL_DOMAINS = {"tkxel.com", "tkxel.io", "corp.tkxel.com", "tkxel.us"}
INBOUND_WINDOW_DAYS = int(os.environ.get("INBOUND_WINDOW_DAYS", "180"))
GMAIL_QUERY = 'from:info@pardot.com subject:"Pardot Form Handler"'


def gmail_service():
    raw = os.environ.get("GMAIL_CREDENTIALS_JSON")
    if not raw:
        raise RuntimeError("GMAIL_CREDENTIALS_JSON is not set")
    info = json.loads(raw)
    creds = Credentials(
        token=info.get("access_token"),
        refresh_token=info["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=info["client_id"],
        client_secret=info["client_secret"],
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _header(headers, name):
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return None


def parse_subject(subject: str):
    """'Pardot Form Handler: <desc> - <email>' -> (description, email). Split on LAST ' - '."""
    body = re.sub(r"^Pardot Form Handler:\s*", "", subject, flags=re.IGNORECASE).strip()
    # Split on the last ' - ' (descriptions can contain dashes).
    if " - " in body:
        desc, email = body.rsplit(" - ", 1)
    else:
        desc, email = body, ""
    email = email.strip().lower()
    # Validate the tail actually looks like an email; if not, no email parsed.
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return body.strip(), None
    return desc.strip(), email


def segment_for(email: str | None) -> tuple[str, str]:
    """Return (segment, domain)."""
    if not email or "@" not in email:
        return "Genuine", ""
    domain = email.split("@", 1)[1].lower()
    if domain in INTERNAL_DOMAINS:
        return "Internal", domain
    return "Genuine", domain


def run():
    svc = gmail_service()
    after = (datetime.now(timezone.utc) - timedelta(days=INBOUND_WINDOW_DAYS)).strftime("%Y/%m/%d")
    query = f"{GMAIL_QUERY} after:{after}"

    msg_ids = []
    page_token = None
    while True:
        resp = svc.users().messages().list(
            userId="me", q=query, pageToken=page_token, maxResults=500
        ).execute()
        msg_ids.extend(m["id"] for m in resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    written = 0
    for mid in msg_ids:
        msg = svc.users().messages().get(
            userId="me", id=mid, format="metadata",
            metadataHeaders=["Subject", "From", "Date"],
        ).execute()
        headers = msg.get("payload", {}).get("headers", [])
        frm = (_header(headers, "From") or "").lower()
        if "info@pardot.com" not in frm:
            continue  # skip forwards/replies
        subject = _header(headers, "Subject") or ""
        desc, email = parse_subject(subject)
        if not email:
            # No parseable email — still record so it isn't silently dropped.
            email = f"unknown+{mid}@no-email.local"
            segment, domain = "Genuine", ""
        else:
            segment, domain = segment_for(email)

        date_hdr = _header(headers, "Date")
        try:
            received = parsedate_to_datetime(date_hdr) if date_hdr else None
        except Exception:
            received = None
        if received is None:
            received = datetime.fromtimestamp(int(msg["internalDate"]) / 1000, tz=timezone.utc)

        with get_cursor(dict_rows=False) as cur:
            cur.execute(
                """INSERT INTO inbound_leads
                   (gmail_message_id, email, description, segment, domain, received_at, raw_subject)
                   VALUES (%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (gmail_message_id) DO UPDATE SET
                     email=EXCLUDED.email, description=EXCLUDED.description,
                     segment=EXCLUDED.segment, domain=EXCLUDED.domain,
                     received_at=EXCLUDED.received_at, raw_subject=EXCLUDED.raw_subject""",
                (mid, email, desc, segment, domain, received, subject),
            )
        written += 1
    return written


def main():
    try:
        mark_sync("inbound", "running")
        n = run()
        mark_sync("inbound", "ok", rows=n, message="sync_inbound complete")
        print(f"sync_inbound: processed {n} messages")
    except Exception as e:
        mark_sync("inbound", "error", message=str(e)[:500])
        print(f"sync_inbound FAILED: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()

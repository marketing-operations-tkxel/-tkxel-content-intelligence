"""sync_mql.py — Google Sheet SDR/MQL tracker -> Postgres.

Cron: 06:00 UTC daily (after inbound, so new leads get matched).

  - Sheet ID from MQL_SHEET_ID. First tab (auto-detected).
  - Header row NOT assumed to be row 1: scan first 6 rows for a row containing
    a cell that looks like 'email'.
  - Re-reads + re-matches on every run (idempotent upsert on email).
  - matched_lead = email exists in inbound_leads.
"""
import json
import os
import re
import sys
import pathlib
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from google.oauth2 import service_account            # noqa: E402
from googleapiclient.discovery import build          # noqa: E402

from db.connection import get_cursor, mark_sync      # noqa: E402

SHEET_ID = os.environ.get("MQL_SHEET_ID", "")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def sheets_service():
    raw = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_CREDENTIALS_JSON is not set")
    info = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def first_tab_title(svc) -> str:
    meta = svc.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
    return meta["sheets"][0]["properties"]["title"]


def find_header(rows):
    """Scan first 6 rows for one containing a cell that looks like 'email'.
    Returns (header_index, header_cells) or (None, None)."""
    for i, row in enumerate(rows[:6]):
        for cell in row:
            if cell and "email" in str(cell).strip().lower():
                return i, [str(c).strip() for c in row]
    return None, None


def col_index(header, *candidates):
    low = [h.lower() for h in header]
    for cand in candidates:
        for i, h in enumerate(low):
            if cand in h:
                return i
    return None


def run():
    if not SHEET_ID:
        raise RuntimeError("MQL_SHEET_ID is not set")
    svc = sheets_service()
    tab = first_tab_title(svc)
    resp = svc.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=f"'{tab}'"
    ).execute()
    rows = resp.get("values", [])
    if not rows:
        return 0

    hidx, header = find_header(rows)
    if header is None:
        raise RuntimeError("No header row containing 'email' found in first 6 rows")

    i_email = col_index(header, "email")
    i_name = col_index(header, "name", "full name", "contact")
    i_company = col_index(header, "company", "account", "organization")
    i_status = col_index(header, "status", "stage", "disposition")
    i_owner = col_index(header, "owner", "sdr", "rep", "assigned")

    data_rows = rows[hidx + 1:]
    written = 0
    for row in data_rows:
        def cell(idx):
            return row[idx].strip() if idx is not None and idx < len(row) and row[idx] else None

        # The sheet's "email" column may hold messy text (e.g. a pasted Pardot
        # subject "... contact us - person@co.com"), not a clean address.
        # Extract the actual email so it matches the clean inbound_leads emails.
        raw_email = cell(i_email)
        if not raw_email:
            continue
        found = EMAIL_RE.findall(raw_email)
        if not found:
            continue
        email = found[-1].lower()

        with get_cursor(dict_rows=False) as cur:
            cur.execute("SELECT 1 FROM inbound_leads WHERE email = %s LIMIT 1", (email,))
            matched = cur.fetchone() is not None
            raw = {header[k]: (row[k] if k < len(row) else None) for k in range(len(header))}
            cur.execute(
                """INSERT INTO mql_records
                   (email, name, company, status, owner, matched_lead, created_at, raw)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (email) DO UPDATE SET
                     name=EXCLUDED.name, company=EXCLUDED.company,
                     status=EXCLUDED.status, owner=EXCLUDED.owner,
                     matched_lead=EXCLUDED.matched_lead, raw=EXCLUDED.raw""",
                (email, cell(i_name), cell(i_company), cell(i_status), cell(i_owner),
                 matched, datetime.now(timezone.utc), json.dumps(raw)),
            )
        written += 1
    return written


def main():
    try:
        mark_sync("mql", "running")
        n = run()
        mark_sync("mql", "ok", rows=n, message="sync_mql complete")
        print(f"sync_mql: wrote {n} MQL records")
    except Exception as e:
        mark_sync("mql", "error", message=str(e)[:500])
        print(f"sync_mql FAILED: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()

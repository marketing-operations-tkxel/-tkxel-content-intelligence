"""Shared BigQuery client built from GOOGLE_CREDENTIALS_JSON."""
import json
import os

from google.cloud import bigquery
from google.oauth2 import service_account

PROJECT = "mkt-data-wh"
GA4_DATASET = "analytics_407787656"
GSC_DATASET = "searchconsole_data"
GSC_SITE = "https://tkxel.com/"
WINDOW_START = "2026-01-01"   # hard floor


def get_client() -> bigquery.Client:
    raw = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not raw:
        raise RuntimeError("GOOGLE_CREDENTIALS_JSON is not set")
    info = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/bigquery"]
    )
    return bigquery.Client(project=PROJECT, credentials=creds)

"""One-time local helper to mint a Gmail OAuth2 refresh token.

1. GCP Console → APIs & Services → Credentials → OAuth 2.0 Client (Desktop app).
   Download it as oauth_client.json into this folder.
2. pip install google-auth-oauthlib
3. python gmail_auth.py
4. Paste the printed JSON as GMAIL_CREDENTIALS_JSON in Railway.
"""
import json
import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def main():
    client_file = sys.argv[1] if len(sys.argv) > 1 else "oauth_client.json"
    flow = InstalledAppFlow.from_client_secrets_file(client_file, SCOPES)
    # Opens the default browser; sign in as the inbox that receives Pardot emails.
    creds = flow.run_local_server(port=0, prompt="consent")
    token = {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
    }
    # Write a one-line version to Downloads to paste into Railway — never printed.
    out = os.path.expanduser("~/Downloads/GMAIL_CREDENTIALS_JSON-oneline.txt")
    with open(out, "w") as f:
        f.write(json.dumps(token, separators=(",", ":")))
    print(f"OK: token written to {out} (refresh_token present: {bool(creds.refresh_token)})")


if __name__ == "__main__":
    main()

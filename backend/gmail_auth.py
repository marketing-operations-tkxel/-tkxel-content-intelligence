"""One-time local helper to mint a Gmail OAuth2 refresh token.

1. GCP Console → APIs & Services → Credentials → OAuth 2.0 Client (Desktop app).
   Download it as oauth_client.json into this folder.
2. pip install google-auth-oauthlib
3. python gmail_auth.py
4. Paste the printed JSON as GMAIL_CREDENTIALS_JSON in Railway.
"""
import json

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def main():
    flow = InstalledAppFlow.from_client_secrets_file("oauth_client.json", SCOPES)
    creds = flow.run_local_server(port=0)
    token = {
        "access_token": creds.token,
        "refresh_token": creds.refresh_token,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
    }
    print(json.dumps(token, indent=2))


if __name__ == "__main__":
    main()

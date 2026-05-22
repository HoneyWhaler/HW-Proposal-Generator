"""
Run this script locally (once) to authorise the app with Google and generate token.pickle.

Usage:
    cd hw-proposal-generator
    source venv/bin/activate
    python scripts/generate_token.py

A browser window will open. Sign in with the Google account that owns the Drive folder.
Once authorised, token.pickle is saved in the project root.

After this, run scripts/encode_token.py to get the base64 string for Railway.
"""

import pickle
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive"]
CREDENTIALS_FILE = Path("oauth_credentials.json")
TOKEN_FILE = Path("token.pickle")

if not CREDENTIALS_FILE.exists():
    print("ERROR: oauth_credentials.json not found in the project root.")
    print("Download it from Google Cloud Console → APIs & Services → Credentials")
    print("Create OAuth client ID → Desktop app → Download JSON → rename to oauth_credentials.json")
    exit(1)

print("Opening browser for Google authorisation...")
flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
creds = flow.run_local_server(port=0)

with open(TOKEN_FILE, "wb") as f:
    pickle.dump(creds, f)

print(f"\n✓ token.pickle saved to {TOKEN_FILE.resolve()}")
print("\nNext step: run  python scripts/encode_token.py  to get the Railway env var value.")

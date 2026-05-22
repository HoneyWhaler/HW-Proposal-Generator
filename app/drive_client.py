"""
Google Drive integration using OAuth2 (uploads as your Google account).

WHY OAUTH2 INSTEAD OF A SERVICE ACCOUNT:
Service accounts have no storage quota of their own, so uploads to shared
folders fail with a 403 even when the folder is correctly shared.
OAuth2 uploads as your real Google account — no quota issues.

FIRST-TIME LOCAL SETUP:
1. In Google Cloud Console → APIs & Services → Credentials
2. Create Credentials → OAuth client ID → Desktop app → Download JSON
3. Rename the file to oauth_credentials.json and place it in the project root
4. Run `python scripts/generate_token.py` — a browser window opens for you to authorise
5. A token.pickle file is saved locally

RAILWAY / SERVER SETUP (no browser available):
1. Complete local setup above first so token.pickle exists
2. Run: python scripts/encode_token.py
   This prints a base64 string — copy it
3. In Railway → Variables, add: GOOGLE_TOKEN_PICKLE_B64 = <paste the string>
4. On startup the app decodes the env var and writes token.pickle automatically
5. Tokens auto-refresh, so you only need to do this once (unless you revoke access)

Both oauth_credentials.json and token.pickle are in .gitignore.
"""

import os
import base64
import pickle
from pathlib import Path
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive"]
TOKEN_FILE = Path("token.pickle")
CREDENTIALS_FILE = Path("oauth_credentials.json")


def _bootstrap_token_from_env():
    """
    On Railway (or any server), token.pickle can't be generated interactively.
    If GOOGLE_TOKEN_PICKLE_B64 is set, decode it and write token.pickle so the
    rest of the auth flow works as normal. Only runs if token.pickle doesn't exist.
    """
    b64 = os.environ.get("GOOGLE_TOKEN_PICKLE_B64", "").strip()
    if b64 and not TOKEN_FILE.exists():
        with open(TOKEN_FILE, "wb") as f:
            f.write(base64.b64decode(b64))


def _get_service():
    # Decode token from env var if running on Railway and no local token exists
    _bootstrap_token_from_env()

    creds = None

    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            # Silently refresh — this works on Railway with no browser
            creds.refresh(Request())
            with open(TOKEN_FILE, "wb") as f:
                pickle.dump(creds, f)
        else:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    "oauth_credentials.json not found in the project root. "
                    "Download it from Google Cloud Console → Credentials → OAuth client ID.\n"
                    "On Railway: set GOOGLE_TOKEN_PICKLE_B64 (run scripts/encode_token.py locally to get it)."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)
            with open(TOKEN_FILE, "wb") as f:
                pickle.dump(creds, f)

    return build("drive", "v3", credentials=creds)


def _find_or_create_folder(service, name: str, parent_id: str) -> str:
    """Returns the folder ID for `name` under `parent_id`, creating it if needed."""
    query = (
        f"name = '{name}' "
        f"and '{parent_id}' in parents "
        f"and mimeType = 'application/vnd.google-apps.folder' "
        f"and trashed = false"
    )
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])

    if files:
        return files[0]["id"]

    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def upload_proposal(file_path: Path, prospect_name: str) -> str:
    """
    Finds or creates a subfolder for the prospect inside the root Drive folder,
    uploads the PPTX, and returns a viewable web link.
    """
    service = _get_service()
    root_folder_id = os.environ["GOOGLE_DRIVE_ROOT_FOLDER_ID"]

    folder_id = _find_or_create_folder(service, prospect_name, root_folder_id)

    file_metadata = {
        "name": file_path.name,
        "parents": [folder_id],
    }
    media = MediaFileUpload(
        str(file_path),
        mimetype="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        resumable=True,
    )
    uploaded = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, webViewLink",
    ).execute()

    return uploaded.get("webViewLink", "")

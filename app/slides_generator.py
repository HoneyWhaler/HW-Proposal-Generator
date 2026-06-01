"""
Google Slides proposal generator.

Replaces app/pptx_generator.py.

HOW IT WORKS:
1. Copies the master Slides template (GOOGLE_SLIDES_TEMPLATE_ID) into the
   prospect's subfolder in Drive.
2. Builds a flat token → value map from the proposal + brief data.
3. Sends one batchUpdate to the Slides API to replace all {{TOKEN}} placeholders.
4. Returns the editable webViewLink.

TEMPLATE TOKENS:
All tokens in the Slides template must use double curly braces: {{TOKEN_NAME}}
See build_context() below for the full list.

ENV VARS REQUIRED:
  GOOGLE_SLIDES_TEMPLATE_ID   — ID from the template Slides URL
  GOOGLE_DRIVE_ROOT_FOLDER_ID — parent folder where prospect subfolders are created
"""

import os
import pickle
import base64
from datetime import datetime
from pathlib import Path

from googleapiclient.discovery import build
from google.auth.transport.requests import Request

TOKEN_FILE = Path("token.pickle")


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _bootstrap_token_from_env():
    """Decode GOOGLE_TOKEN_PICKLE_B64 env var into token.pickle if not present."""
    b64 = os.environ.get("GOOGLE_TOKEN_PICKLE_B64", "").strip()
    if b64 and not TOKEN_FILE.exists():
        TOKEN_FILE.write_bytes(base64.b64decode(b64))


def _get_creds():
    _bootstrap_token_from_env()
    if not TOKEN_FILE.exists():
        raise FileNotFoundError(
            "token.pickle not found. Run scripts/generate_token.py to authorise."
        )
    with open(TOKEN_FILE, "rb") as f:
        creds = pickle.load(f)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)
    return creds


def _drive():
    return build("drive", "v3", credentials=_get_creds())


def _slides():
    return build("slides", "v1", credentials=_get_creds())


# ---------------------------------------------------------------------------
# Drive folder helpers
# ---------------------------------------------------------------------------

def _find_or_create_folder(service, name: str, parent_id: str) -> str:
    """Return folder ID for `name` under `parent_id`, creating it if needed."""
    # Escape single quotes in folder name for the query
    safe_name = name.replace("'", "\\'")
    query = (
        f"name = '{safe_name}' "
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


# ---------------------------------------------------------------------------
# Token map
# ---------------------------------------------------------------------------

def build_context(proposal: dict, brief: dict) -> dict:
    """
    Maps proposal JSON + brief fields to a flat {TOKEN: value} dict.
    Every key here must have a matching {{TOKEN}} in the Slides template.
    """
    ctx = {}

    # Cover / meta
    ctx["PROSPECT_NAME"]         = brief.get("prospect_name", "")
    ctx["CONTACT_NAME"]          = brief.get("contact_name", "")
    ctx["ACCOUNT_MANAGER"]       = brief.get("account_manager", "")
    ctx["ACCOUNT_MANAGER_EMAIL"] = brief.get("account_manager_email", "")
    ctx["START_DATE"]            = proposal.get("start_date", "TBC")
    ctx["BRAND_SUMMARY"]         = proposal.get("brand_summary", "")

    # Realities — 3 items
    for i, r in enumerate(proposal.get("realities", []), 1):
        ctx[f"REALITY_{i}_TITLE"] = r.get("title", "")
        ctx[f"REALITY_{i}_TEXT"]  = r.get("text", "")

    # Plan — 5 phases, up to 4 bullets each
    for i, p in enumerate(proposal.get("plan", []), 1):
        ctx[f"PLAN_{i}_TITLE"] = p.get("title", "")
        items = p.get("items", [])
        for j, item in enumerate(items, 1):
            ctx[f"PLAN_{i}_ITEM_{j}"] = item
        # Empty remaining slots so orphan tokens don't show in the deck
        for j in range(len(items) + 1, 5):
            ctx[f"PLAN_{i}_ITEM_{j}"] = ""

    # Cost
    cost = proposal.get("cost", {})
    ctx["COST_LINE_1_NAME"]  = cost.get("line_1_name", "")
    ctx["COST_LINE_1_DESC"]  = cost.get("line_1_desc", "")
    ctx["COST_LINE_1_PRICE"] = cost.get("line_1_price", "")
    ctx["COST_TOTAL"]        = cost.get("total", "")

    # Deliverables — 4 columns, up to 6 bullets each
    for i, d in enumerate(proposal.get("deliverables", []), 1):
        ctx[f"DELIV_{i}_TITLE"] = d.get("title", "")
        items = d.get("items", [])
        for j, item in enumerate(items, 1):
            ctx[f"DELIV_{i}_ITEM_{j}"] = item
        for j in range(len(items) + 1, 7):
            ctx[f"DELIV_{i}_ITEM_{j}"] = ""

    # Timeline & exclusions
    ctx["TIMELINE"]     = proposal.get("timeline", "")
    ctx["OUT_OF_SCOPE"] = proposal.get("out_of_scope", "")

    # To get started — 6 items
    for i, s in enumerate(proposal.get("to_get_started", []), 1):
        ctx[f"START_{i}_TITLE"] = s.get("title", "")
        ctx[f"START_{i}_TEXT"]  = s.get("text", "")

    return ctx


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_slides(proposal: dict, brief: dict) -> str:
    """
    Copies the Slides template, fills in all tokens, saves to the prospect's
    Drive folder, and returns the editable Google Slides URL.
    """
    drive_svc  = _drive()
    slides_svc = _slides()

    template_id    = os.environ["GOOGLE_SLIDES_TEMPLATE_ID"]
    root_folder_id = os.environ["GOOGLE_DRIVE_ROOT_FOLDER_ID"]
    prospect_name  = brief.get("prospect_name", "Unknown Prospect")

    # 1 — Find or create prospect subfolder
    folder_id = _find_or_create_folder(drive_svc, prospect_name, root_folder_id)

    # 2 — Copy template into that folder
    date_str  = datetime.now().strftime("%Y-%m-%d")
    filename  = f"HW Proposal — {prospect_name} — {date_str}"

    copied = drive_svc.files().copy(
        fileId=template_id,
        body={
            "name":    filename,
            "parents": [folder_id],
        },
    ).execute()

    presentation_id = copied["id"]

    # 3 — Replace all {{TOKEN}} placeholders in one batchUpdate call
    context = build_context(proposal, brief)
    requests = [
        {
            "replaceAllText": {
                "containsText": {"text": f"{{{{{token}}}}}"},
                "replaceText":  str(value) if value is not None else "",
            }
        }
        for token, value in context.items()
    ]

    slides_svc.presentations().batchUpdate(
        presentationId=presentation_id,
        body={"requests": requests},
    ).execute()

    # 4 — Return the editable link
    meta = drive_svc.files().get(
        fileId=presentation_id,
        fields="webViewLink",
    ).execute()

    return meta.get(
        "webViewLink",
        f"https://docs.google.com/presentation/d/{presentation_id}/edit",
    )

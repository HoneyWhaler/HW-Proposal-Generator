"""
Google Slides proposal generator — dynamic slide assembly.

FLOW:
1. Copy the master Slides template into the prospect's Drive folder
2. Parse each slide's SLIDE_TYPE from its speaker notes
3. Delete slides not relevant to this proposal (conditional service slides,
   excess SOW slides)
4. Replace all {{TOKEN}} placeholders globally (proposal content)
5. Replace {{SLIDE_LABEL}} and {{PAGE_NUMBER}} per-slide (unique per slide)
6. Return the editable Google Slides URL

SLIDE TYPES (from speaker notes — "SLIDE_TYPE: <type>"):
  always included:
    cover, proposal_at_a_glance, brand_summary, three_realities, the_plan,
    what_it_costs, your_investment, what_you_get, deliverables_list, sow_1,
    how_we_work, next_steps, about_hw, sign_off
  conditional:
    why_shopify  — included when Shopify services are selected
    why_seo      — included when SEO is selected
    why_google_ads — included when Google Ads / paid search is selected
    sow_2        — included when scope_of_work has 2+ entries
    sow_3        — included when scope_of_work has 3 entries

ENV VARS REQUIRED:
  GOOGLE_SLIDES_TEMPLATE_ID   — ID from the template Slides URL
  GOOGLE_DRIVE_ROOT_FOLDER_ID — root folder where prospect subfolders live
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
# Slide label map — fixed category label per slide type
# ---------------------------------------------------------------------------

SLIDE_LABELS = {
    "cover":                "",
    "proposal_at_a_glance": "ENGAGEMENT",
    "brand_summary":        "WHERE YOU ARE NOW",
    "three_realities":      "WHERE YOU ARE NOW",
    "the_plan":             "THE PLAN",
    "why_shopify":          "WHY SHOPIFY",
    "why_seo":              "WHY SEO",
    "why_google_ads":       "WHY GOOGLE ADS",
    "what_it_costs":        "INVESTMENT",
    "your_investment":      "INVESTMENT",
    "what_you_get":         "DELIVERABLES",
    "deliverables_list":    "DELIVERABLES",
    "sow_1":                "SCOPE OF WORK",
    "sow_2":                "SCOPE OF WORK",
    "sow_3":                "SCOPE OF WORK",
    "how_we_work":          "HOW WE WORK",
    "next_steps":           "NEXT STEPS",
    "about_hw":             "ABOUT HONEY WHALE",
    "sign_off":             "",
}


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _bootstrap_token_from_env():
    """Write token.pickle from env var on Railway where no local file exists."""
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
# Drive helpers
# ---------------------------------------------------------------------------

def _find_or_create_folder(service, name: str, parent_id: str) -> str:
    safe_name = name.replace("'", "\\'")
    query = (
        f"name = '{safe_name}' "
        f"and '{parent_id}' in parents "
        f"and mimeType = 'application/vnd.google-apps.folder' "
        f"and trashed = false"
    )
    results = service.files().list(q=query, fields="files(id)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]
    folder = service.files().create(
        body={
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        },
        fields="id",
    ).execute()
    return folder["id"]


# ---------------------------------------------------------------------------
# Speaker notes parsing
# ---------------------------------------------------------------------------

def _get_slide_notes(slide: dict) -> str:
    """Extract speaker notes text from a slide object in the Slides API response."""
    try:
        notes_page = slide.get("slideProperties", {}).get("notesPage", {})
        for element in notes_page.get("pageElements", []):
            text_obj = element.get("shape", {}).get("text", {})
            text = "".join(
                te.get("textRun", {}).get("content", "")
                for te in text_obj.get("textElements", [])
            ).strip()
            # The speaker notes element is the one that contains our tags
            if "SLIDE_TYPE:" in text:
                return text
    except Exception:
        pass
    return ""


def _parse_note_field(notes: str, field: str) -> str:
    """Parse a single 'FIELD: value' line from notes text."""
    for line in notes.splitlines():
        if line.strip().upper().startswith(f"{field.upper()}:"):
            return line.split(":", 1)[1].strip()
    return ""


# ---------------------------------------------------------------------------
# Service detection & slide deletion
# ---------------------------------------------------------------------------

def _services_include(services: list, *keywords) -> bool:
    """True if any keyword appears in the joined services list."""
    joined = " ".join(services).lower()
    return any(kw.lower() in joined for kw in keywords)


def _get_slides_to_delete(slide_info: list, brief: dict, proposal: dict) -> list:
    """
    Returns slide object IDs that should be removed for this proposal.
    Conditional slides are deleted when the relevant service isn't selected.
    Excess SOW slides are deleted when scope_of_work has fewer than 3 entries.
    """
    services  = brief.get("services", [])
    sow_count = len(proposal.get("scope_of_work", []))

    # Maps slide type → True if it should be deleted
    delete_rules = {
        "why_shopify":    not _services_include(services, "shopify", "theme", "migration", "store build", "replatform"),
        "why_seo":        not _services_include(services, "seo", "search engine"),
        "why_google_ads": not _services_include(services, "google ads", "paid search", "ppc", "performance max"),
        "sow_2":          sow_count < 2,
        "sow_3":          sow_count < 3,
    }

    return [
        slide["id"]
        for slide in slide_info
        if delete_rules.get(slide["type"], False)
    ]


# ---------------------------------------------------------------------------
# Token map
# ---------------------------------------------------------------------------

def _bullet_list(items: list) -> str:
    return "\n".join(f"- {item}" for item in items if item)


def build_context(proposal: dict, brief: dict) -> dict:
    """
    Flat {TOKEN: value} map for all global replacements.
    SLIDE_LABEL and PAGE_NUMBER are NOT in here — they're applied per-slide.
    """
    ctx = {}

    # Cover / meta
    ctx["PROSPECT_NAME"]         = proposal.get("prospect_name", brief.get("prospect_name", ""))
    ctx["CONTACT_NAME"]          = brief.get("contact_name", "")
    ctx["ACCOUNT_MANAGER"]       = brief.get("account_manager", "")
    ctx["ACCOUNT_MANAGER_EMAIL"] = brief.get("account_manager_email", "")
    ctx["START_DATE"]            = proposal.get("start_date", "TBC")
    ctx["CURRENT_MONTH"]         = datetime.now().strftime("%B %Y").upper()
    ctx["BRAND_SUMMARY"]         = proposal.get("brand_summary", "")

    # Realities — 3 items
    for i, r in enumerate(proposal.get("realities", [{}, {}, {}])[:3], 1):
        ctx[f"REALITY_{i}_TITLE"] = r.get("title", "")
        ctx[f"REALITY_{i}_TEXT"]  = r.get("text", "")

    # Plan — 5 phases, bullets joined into one string per phase
    for i, p in enumerate(proposal.get("plan", [{}, {}, {}, {}, {}])[:5], 1):
        ctx[f"PLAN_{i}_TITLE"] = p.get("title", "")
        ctx[f"PLAN_{i}_ITEMS"] = _bullet_list(p.get("items", []))

    # Investment
    cost = proposal.get("cost", {})
    ctx["COST_LINE_1_NAME"]  = cost.get("line_1_name", "")
    ctx["COST_LINE_1_DESC"]  = cost.get("line_1_desc", "")
    ctx["COST_LINE_1_PRICE"] = cost.get("line_1_price", "")
    ctx["TOTAL_INVESTMENT"]  = cost.get("total", "")

    # Deliverables — 4 columns, bullets joined per column
    for i, d in enumerate(proposal.get("deliverables", [{}, {}, {}, {}])[:4], 1):
        ctx[f"DELIVERABLES_{i}_TITLE"] = d.get("title", "")
        ctx[f"DELIVERABLES_{i}_ITEMS"] = _bullet_list(d.get("items", []))

    # Timeline & exclusions
    ctx["TIMELINE"]     = proposal.get("timeline", "")
    ctx["OUT_OF_SCOPE"] = proposal.get("out_of_scope", "")

    # Next steps — 6 items
    for i, s in enumerate(proposal.get("to_get_started", [])[:6], 1):
        ctx[f"START_ITEM_{i}_TITLE"] = s.get("title", "")
        ctx[f"START_ITEM_{i}_TEXT"]  = s.get("text", "")

    # Why Shopify (conditional) — slide headings are hardcoded in template, items only
    why_shopify = proposal.get("why_shopify", {})
    items = why_shopify.get("items", [])
    for i, item in enumerate(items[:4], 1):
        ctx[f"WHY_SHOPIFY_ITEM_{i}"] = item
    for i in range(len(items) + 1, 5):
        ctx[f"WHY_SHOPIFY_ITEM_{i}"] = ""

    # Why SEO (conditional) — slide headings are hardcoded in template, items only
    why_seo = proposal.get("why_seo", {})
    items = why_seo.get("items", [])
    for i, item in enumerate(items[:4], 1):
        ctx[f"WHY_SEO_ITEM_{i}"] = item
    for i in range(len(items) + 1, 5):
        ctx[f"WHY_SEO_ITEM_{i}"] = ""
    hw_items = why_seo.get("hw_items", [])
    for i, item in enumerate(hw_items[:4], 1):
        ctx[f"WHY_HW_SEO_ITEM_{i}"] = item
    for i in range(len(hw_items) + 1, 5):
        ctx[f"WHY_HW_SEO_ITEM_{i}"] = ""

    # Why Google Ads (conditional) — slide headings are hardcoded in template, items only
    why_ads = proposal.get("why_google_ads", {})
    items = why_ads.get("items", [])
    for i, item in enumerate(items[:4], 1):
        ctx[f"WHY_GOOGLE_ADS_ITEM_{i}"] = item
    for i in range(len(items) + 1, 5):
        ctx[f"WHY_GOOGLE_ADS_ITEM_{i}"] = ""
    hw_items = why_ads.get("hw_items", [])
    for i, item in enumerate(hw_items[:4], 1):
        ctx[f"WHY_HW_GOOGLE_ADS_ITEM_{i}"] = item
    for i in range(len(hw_items) + 1, 5):
        ctx[f"WHY_HW_GOOGLE_ADS_ITEM_{i}"] = ""

    # Scope of Work — up to 3 services, individual item tokens
    for sow_idx, sow in enumerate(proposal.get("scope_of_work", [])[:3], 1):
        ctx[f"SOW_{sow_idx}_TITLE"]       = sow.get("title", "")
        ctx[f"SOW_{sow_idx}_DESCRIPTION"] = sow.get("description", "")
        items = sow.get("items", [])
        for i, item in enumerate(items[:6], 1):
            ctx[f"SOW_{sow_idx}_ITEM_{i}"] = item
        # Empty remaining item slots so orphan tokens don't render
        for i in range(len(items) + 1, 7):
            ctx[f"SOW_{sow_idx}_ITEM_{i}"] = ""

    return ctx


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def generate_slides(proposal: dict, brief: dict) -> str:
    """
    Copies the Slides template, assembles a custom deck for this proposal,
    fills all tokens, and returns the editable Google Slides URL.
    """
    drive_svc  = _drive()
    slides_svc = _slides()

    template_id    = os.environ["GOOGLE_SLIDES_TEMPLATE_ID"]
    root_folder_id = os.environ["GOOGLE_DRIVE_ROOT_FOLDER_ID"]
    prospect_name  = brief.get("prospect_name", "Unknown Prospect")

    # 1 — Copy template into prospect's Drive folder
    folder_id = _find_or_create_folder(drive_svc, prospect_name, root_folder_id)
    date_str  = datetime.now().strftime("%Y-%m-%d")
    filename  = f"HW Proposal — {prospect_name} — {date_str}"

    copied = drive_svc.files().copy(
        fileId=template_id,
        body={"name": filename, "parents": [folder_id]},
    ).execute()
    presentation_id = copied["id"]

    # 2 — Fetch presentation and parse slide metadata from speaker notes
    presentation = slides_svc.presentations().get(
        presentationId=presentation_id
    ).execute()

    slide_info = []
    for slide in presentation["slides"]:
        notes      = _get_slide_notes(slide)
        slide_type = _parse_note_field(notes, "SLIDE_TYPE")
        slide_info.append({
            "id":    slide["objectId"],
            "type":  slide_type,
            "label": SLIDE_LABELS.get(slide_type, ""),
        })

    # 3 — Delete slides not needed for this proposal
    ids_to_delete = _get_slides_to_delete(slide_info, brief, proposal)
    if ids_to_delete:
        slides_svc.presentations().batchUpdate(
            presentationId=presentation_id,
            body={
                "requests": [
                    {"deleteObject": {"objectId": sid}} for sid in ids_to_delete
                ]
            },
        ).execute()
        # Keep local info in sync
        slide_info = [s for s in slide_info if s["id"] not in ids_to_delete]

    # 4 — Build all replacement requests
    requests = []

    # 4a — Global tokens (same value across all slides)
    for token, value in build_context(proposal, brief).items():
        requests.append({
            "replaceAllText": {
                "containsText": {"text": f"{{{{{token}}}}}"},
                "replaceText":  str(value) if value is not None else "",
            }
        })

    # 4b — Per-slide SLIDE_LABEL and PAGE_NUMBER
    for page_num, slide in enumerate(slide_info, 1):
        for token, value in [
            ("{{SLIDE_LABEL}}", slide["label"]),
            ("{{PAGE_NUMBER}}", str(page_num)),
        ]:
            requests.append({
                "replaceAllText": {
                    "containsText":  {"text": token},
                    "replaceText":   value,
                    "pageObjectIds": [slide["id"]],
                }
            })

    # 5 — Execute everything in one batchUpdate
    slides_svc.presentations().batchUpdate(
        presentationId=presentation_id,
        body={"requests": requests},
    ).execute()

    # 6 — Return editable link
    meta = drive_svc.files().get(
        fileId=presentation_id,
        fields="webViewLink",
    ).execute()

    return meta.get(
        "webViewLink",
        f"https://docs.google.com/presentation/d/{presentation_id}/edit",
    )

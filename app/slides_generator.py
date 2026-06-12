"""
Google Slides proposal generator — dynamic slide assembly.

FLOW:
1. Copy the master Slides template into the prospect's Drive folder
2. Parse each slide's SLIDE_TYPE from its speaker notes
3. Delete service slides not relevant to this proposal
4. Replace all {{TOKEN}} placeholders globally (proposal content)
5. Replace {{SLIDE_LABEL}} and {{PAGE_NUMBER}} per-slide (unique per slide)
6. Return the editable Google Slides URL

SLIDE TYPES (add to speaker notes in the Google Slides template):
  Always included:
    cover, overview, where_now, realities, the_plan, investment,
    proof, about_hw, how_we_work, sign_off

  Conditional — WHY slides (deleted when service not selected):
    why_shopify     → Shopify Theme Build, Custom Build, WooCommerce Migration, Custom Project
    why_google_ads  → Google Ads, Meta Ads, Search Dominance
    why_seo         → E-commerce SEO, Service-Based SEO, Local SEO, AEO/GEO, Technical SEO Sprint

  Conditional — SOW slides (deleted when service not selected):
    sow_seo_aeo_audit, sow_ecommerce_seo, sow_service_based_seo, sow_local_seo,
    sow_aeo_geo, sow_google_ads, sow_meta_ads, sow_ppc_landing_pages,
    sow_search_dominance, sow_shopify_theme_build, sow_shopify_custom_build,
    sow_woocommerce_migration, sow_custom_shopify, sow_post_launch_support,
    sow_dev_blocs, sow_page_speed, sow_cro_audit, sow_colp,
    sow_server_side_tracking, sow_technical_seo_sprint

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
    "cover":                    "",
    "overview":                 "OVERVIEW",
    "where_now":                "WHERE YOU ARE NOW",
    "realities":                "WHERE YOU ARE NOW",
    "the_plan":                 "THE PLAN",
    "why_shopify":              "WHY",
    "why_google_ads":           "WHY",
    "why_seo":                  "WHY",
    "sow_seo_aeo_audit":        "SCOPE OF WORK",
    "sow_ecommerce_seo":        "SCOPE OF WORK",
    "sow_service_based_seo":    "SCOPE OF WORK",
    "sow_local_seo":            "SCOPE OF WORK",
    "sow_aeo_geo":              "SCOPE OF WORK",
    "sow_google_ads":           "SCOPE OF WORK",
    "sow_meta_ads":             "SCOPE OF WORK",
    "sow_ppc_landing_pages":    "SCOPE OF WORK",
    "sow_search_dominance":     "SCOPE OF WORK",
    "sow_shopify_theme_build":  "SCOPE OF WORK",
    "sow_shopify_custom_build": "SCOPE OF WORK",
    "sow_woocommerce_migration":"SCOPE OF WORK",
    "sow_custom_shopify":       "SCOPE OF WORK",
    "sow_post_launch_support":  "SCOPE OF WORK",
    "sow_dev_blocs":            "SCOPE OF WORK",
    "sow_page_speed":           "SCOPE OF WORK",
    "sow_cro_audit":            "SCOPE OF WORK",
    "sow_colp":                 "SCOPE OF WORK",
    "sow_server_side_tracking": "SCOPE OF WORK",
    "sow_technical_seo_sprint": "SCOPE OF WORK",
    "investment":               "SUMMARY",
    "proof":                    "PROOF",
    "about_hw":                 "ABOUT",
    "how_we_work":              "TERMS",
    "sign_off":                 "ACCEPTANCE",
}


# ---------------------------------------------------------------------------
# Service slide keywords — a slide is DELETED if none of its keywords
# appear in the selected services list.
# ---------------------------------------------------------------------------

SERVICE_SLIDE_KEYWORDS = {
    "why_shopify": [
        "shopify theme build", "shopify custom build",
        "woocommerce migration", "custom shopify",
    ],
    "why_google_ads": [
        "google ads", "meta ads", "search dominance",
    ],
    "why_seo": [
        "e-commerce seo", "service-based seo", "local seo",
        "aeo", "geo", "technical seo sprint",
    ],
    "sow_seo_aeo_audit":        ["seo/aeo audit", "seo audit"],
    "sow_ecommerce_seo":        ["e-commerce seo"],
    "sow_service_based_seo":    ["service-based seo", "service based seo"],
    "sow_local_seo":            ["local seo"],
    "sow_aeo_geo":              ["aeo / geo", "aeo/geo", "aeo", "geo"],
    "sow_google_ads":           ["google ads"],
    "sow_meta_ads":             ["meta ads"],
    "sow_ppc_landing_pages":    ["ppc landing page"],
    "sow_search_dominance":     ["search dominance"],
    "sow_shopify_theme_build":  ["shopify theme build"],
    "sow_shopify_custom_build": ["shopify custom build"],
    "sow_woocommerce_migration":["woocommerce migration"],
    "sow_custom_shopify":       ["custom shopify project"],
    "sow_post_launch_support":  ["post-launch support", "post launch support"],
    "sow_dev_blocs":            ["dev bloc"],
    "sow_page_speed":           ["page speed"],
    "sow_cro_audit":            ["cro audit"],
    "sow_colp":                 ["colp", "conversion-optimised landing page"],
    "sow_server_side_tracking": ["server-side tracking", "server side tracking"],
    "sow_technical_seo_sprint": ["technical seo sprint"],
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

def _get_slides_to_delete(slide_info: list, brief: dict, proposal: dict) -> list:
    """
    Returns slide object IDs that should be removed for this proposal.
    Any slide whose SLIDE_TYPE is in SERVICE_SLIDE_KEYWORDS is deleted
    unless at least one of its keywords appears in the selected services.
    """
    joined_services = " ".join(brief.get("services", [])).lower()

    return [
        slide["id"]
        for slide in slide_info
        if slide["type"] in SERVICE_SLIDE_KEYWORDS
        and not any(
            kw.lower() in joined_services
            for kw in SERVICE_SLIDE_KEYWORDS[slide["type"]]
        )
    ]


# ---------------------------------------------------------------------------
# Token map
# ---------------------------------------------------------------------------

def _bullet_list(items: list) -> str:
    return "\n".join(f"- {item}" for item in items if item)


def build_context(proposal: dict, brief: dict) -> dict:
    """
    Flat {TOKEN: value} map for all global replacements.
    SLIDE_LABEL and PAGE_NUMBER are applied per-slide separately.
    """
    ctx = {}

    # Cover / meta
    ctx["PROSPECT_NAME"]          = proposal.get("prospect_name", brief.get("prospect_name", ""))
    ctx["CONTACT_NAME"]           = brief.get("contact_name", "")
    ctx["ACCOUNT_MANAGER"]        = brief.get("account_manager", "")
    ctx["ACCOUNT_MANAGER_EMAIL"]  = brief.get("account_manager_email", "")
    ctx["START_DATE"]             = proposal.get("start_date", "TBC")
    ctx["MONTH"]                  = datetime.now().strftime("%B").upper()
    ctx["ENGAGEMENT_SUMMARY"]     = proposal.get("engagement_summary", "")

    # Where You Are Now
    ctx["WHERE_NOW_TITLE"]        = proposal.get("where_now_title", "")
    ctx["BRAND_SUMMARY"]          = proposal.get("brand_summary", "")
    ctx["KEY_STAT"]               = proposal.get("key_stat", "")
    ctx["KEY_STAT_LABEL"]         = proposal.get("key_stat_label", "")
    # Placeholder for a product/store image — filled manually by account manager
    ctx["PRODUCT_OR_STORE_IMAGE"] = ""

    # Realities — always 3
    for i, r in enumerate(proposal.get("realities", [{}, {}, {}])[:3], 1):
        ctx[f"REALITY_{i}_TITLE"] = r.get("title", "")
        ctx[f"REALITY_{i}_BODY"]  = r.get("body", "")

    # Plan — always 5 phases
    for i, p in enumerate(proposal.get("plan", [{}, {}, {}, {}, {}])[:5], 1):
        ctx[f"PHASE_{i}_TITLE"] = p.get("title", "")
        ctx[f"PHASE_{i}_TIME"]  = p.get("time", "")
        ctx[f"PHASE_{i}_ITEMS"] = _bullet_list(p.get("items", []))

    # Investment — up to 2 monthly retainers, up to 3 one-offs
    cost = proposal.get("cost", {})

    monthly = cost.get("monthly", [])
    for i, m in enumerate(monthly[:2], 1):
        ctx[f"MONTHLY_{i}_NAME"]  = m.get("name", "")
        ctx[f"MONTHLY_{i}_PRICE"] = m.get("price", "")
    for i in range(len(monthly) + 1, 3):
        ctx[f"MONTHLY_{i}_NAME"]  = ""
        ctx[f"MONTHLY_{i}_PRICE"] = ""
    ctx["MONTHLY_TOTAL"] = cost.get("monthly_total", "")

    oneoff = cost.get("oneoff", [])
    for i, o in enumerate(oneoff[:3], 1):
        ctx[f"ONEOFF_{i}_NAME"]  = o.get("name", "")
        ctx[f"ONEOFF_{i}_PRICE"] = o.get("price", "")
    for i in range(len(oneoff) + 1, 4):
        ctx[f"ONEOFF_{i}_NAME"]  = ""
        ctx[f"ONEOFF_{i}_PRICE"] = ""
    ctx["ONEOFF_TOTAL"] = cost.get("oneoff_total", "")

    # Timeline
    ctx["TIMELINE"] = proposal.get("timeline", "")

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

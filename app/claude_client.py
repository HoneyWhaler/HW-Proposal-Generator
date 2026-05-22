"""
Handles all communication with the Anthropic Claude API.

TWO-STEP PIPELINE:
  Step 1 — diagnose():
    Fetches the prospect's website and reasons through their situation.
    Produces a structured diagnosis: gaps, opportunities, recommended services.

  Step 2 — generate_proposal_content():
    Takes the brief + diagnosis and writes the full proposal JSON.
    The diagnosis grounds the copy in real observations rather than generics.

To update HW context: edit context/services.md and context/rate_card.md.
"""

import os
import json
from pathlib import Path
import httpx
import anthropic

CONTEXT_DIR = Path(__file__).parent.parent / "context"


def _load_context_file(filename: str) -> str:
    path = CONTEXT_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"[{filename} not found — add it to the context/ folder]"


SERVICES_CONTEXT = _load_context_file("services.md")
RATE_CARD_CONTEXT = _load_context_file("rate_card.md")

# ---------------------------------------------------------------------------
# STEP 1 — DIAGNOSIS
# ---------------------------------------------------------------------------

DIAGNOSIS_SYSTEM_PROMPT = """
You are a senior strategist at Honey Whale (Pty) Ltd, a Shopify-focused growth agency in South Africa.

Your job is to analyse a prospect before a proposal is written.
You will be given:
- A prospect brief (company name, industry, services requested, sales notes)
- The raw HTML/text content of their website (if available)

Produce a structured diagnosis in JSON. Be specific and honest — vague observations are useless.
Reference actual things you see on the website where possible (page structure, missing schema, thin content, slow UX signals, etc.).

Return only this JSON structure. No markdown. No explanation outside the JSON.

{
  "prospect_summary": "2-3 sentences on who they are, what they sell, and their market position.",
  "current_situation": [
    "Specific observation about their current state — platform, site quality, content, SEO, ads, etc.",
    "Another observation.",
    "Another observation."
  ],
  "key_gaps": [
    "Specific gap or problem that Honey Whale can address.",
    "Another gap.",
    "Another gap."
  ],
  "opportunities": [
    "Specific growth opportunity relevant to the services requested.",
    "Another opportunity."
  ],
  "recommended_services": [
    {
      "service": "Exact service name from the HW rate card",
      "rationale": "1-2 sentences on why this service fits this specific prospect."
    }
  ],
  "tone_notes": "How should the proposal copy feel for this prospect? e.g. direct and no-nonsense, aspirational, reassuring, etc.",
  "risks_or_flags": "Anything the account manager should know — budget signals, competing platforms, unrealistic expectations, etc. Leave empty string if none."
}
""".strip()


def _fetch_website(url: str) -> str:
    """
    Fetches the prospect's website HTML and returns a truncated plain-text version.
    Returns an empty string silently if the fetch fails — diagnosis continues without it.
    """
    if not url:
        return ""
    try:
        # Normalise URL
        if not url.startswith("http"):
            url = "https://" + url
        headers = {"User-Agent": "Mozilla/5.0 (compatible; HWProposalBot/1.0)"}
        resp = httpx.get(url, headers=headers, timeout=15, follow_redirects=True)
        text = resp.text

        # Strip tags crudely — good enough for analysis
        import re
        text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL)
        text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

        # Truncate to ~6,000 chars to stay within context limits
        return text[:6000]
    except Exception:
        return ""


def diagnose(brief: dict) -> dict:
    """
    Step 1: Fetches the prospect's website and produces a structured diagnosis.
    Returns a diagnosis dict.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    website_content = _fetch_website(brief.get("website_url", ""))

    website_section = (
        f"\n\nWEBSITE CONTENT (truncated):\n{website_content}"
        if website_content
        else "\n\nWEBSITE: Could not be fetched or URL not provided."
    )

    user_message = f"""
Analyse this prospect:

Company: {brief.get("prospect_name")}
Website: {brief.get("website_url", "Not provided")}
Industry: {brief.get("industry", "Not specified")}
Services requested: {", ".join(brief.get("services", []))}

Sales notes:
{brief.get("sales_notes", "No notes provided")}
{website_section}
""".strip()

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2048,
        system=DIAGNOSIS_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(l for l in lines if not l.strip().startswith("```")).strip()

    return json.loads(raw)


# ---------------------------------------------------------------------------
# STEP 2 — PROPOSAL GENERATION
# ---------------------------------------------------------------------------

PROPOSAL_SYSTEM_PROMPT = f"""
You are a senior proposal writer for Honey Whale (Pty) Ltd, a Shopify-focused growth agency in South Africa.

You will be given:
- A prospect brief
- A pre-written diagnosis of the prospect's situation (gaps, opportunities, recommended services)

Use the diagnosis to ground every section of the proposal in specific, real observations.
Write for slides — confident, specific, human. No corporate jargon.

STRICT RULES:
- Only reference services and pricing from the official Honey Whale service list and rate card below.
- Do not invent services, packages, or pricing.
- All pricing in ZAR. Format as "R85,000" or "R9,500/month".
- The plan always has exactly 5 phases.
- Realities always has exactly 3 items.
- Deliverables always has exactly 4 columns.
- To get started always has exactly 6 items.

LAYOUT CONSTRAINTS (slide text boxes — content must fit):
- plan[].title: max 3 words. e.g. "Foundation", "Store Build", "SEO & Content".
- plan[].items: max 4 bullets per phase. Each item max 40 characters.
- deliverables[].title: max 3 words.
- deliverables[].items: max 6 bullets per column. Each item max 50 characters.
- realities[].title: max 3 words.
- to_get_started[].title: max 3 words.
- to_get_started[].text: max 120 characters.
- brand_summary: max 3 sentences.
- timeline: max 2 sentences.
- out_of_scope: comma-separated list, max 80 characters total.

---
HONEY WHALE SERVICES:
{SERVICES_CONTEXT}

---
HONEY WHALE RATE CARD:
{RATE_CARD_CONTEXT}
---

Return only valid JSON matching this schema exactly. No markdown.

{{
  "prospect_name": "string",
  "start_date": "string — e.g. 'JULY 2026' or 'TBC'",
  "brand_summary": "string — max 3 sentences. Specific to this prospect.",

  "realities": [
    {{"title": "string — max 3 words", "text": "string — 2-4 sentences"}},
    {{"title": "string", "text": "string"}},
    {{"title": "string", "text": "string"}}
  ],

  "plan": [
    {{"title": "string — max 3 words", "items": ["string", "string"]}},
    {{"title": "string", "items": ["string", "string"]}},
    {{"title": "string", "items": ["string", "string"]}},
    {{"title": "string", "items": ["string", "string"]}},
    {{"title": "string", "items": ["string", "string"]}}
  ],

  "cost": {{
    "line_1_name": "string",
    "line_1_desc": "string — short comma-separated summary",
    "line_1_price": "string — e.g. 'R57,000' or 'R12,500/month'",
    "total": "string"
  }},

  "deliverables": [
    {{"title": "string — max 3 words", "items": ["string", "string"]}},
    {{"title": "string", "items": ["string", "string"]}},
    {{"title": "string", "items": ["string", "string"]}},
    {{"title": "string", "items": ["string", "string"]}}
  ],

  "timeline": "string — max 2 sentences",
  "out_of_scope": "string — comma-separated, max 80 chars",

  "to_get_started": [
    {{"title": "string — max 3 words", "text": "string — max 120 chars"}},
    {{"title": "string", "text": "string"}},
    {{"title": "string", "text": "string"}},
    {{"title": "string", "text": "string"}},
    {{"title": "string", "text": "string"}},
    {{"title": "string", "text": "string"}}
  ]
}}
""".strip()


def generate_proposal_content(brief: dict, diagnosis: dict) -> dict:
    """
    Step 2: Takes the brief + diagnosis and returns the full proposal JSON.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    user_message = f"""
Generate a proposal for this prospect.

BRIEF:
Company: {brief.get("prospect_name")}
Website: {brief.get("website_url", "Not provided")}
Industry: {brief.get("industry", "Not specified")}
Services: {", ".join(brief.get("services", []))}
Contact: {brief.get("contact_name")}
Account manager: {brief.get("account_manager")}
Sales notes: {brief.get("sales_notes", "None")}

DIAGNOSIS (use this to write specific, grounded copy):
Summary: {diagnosis.get("prospect_summary", "")}
Current situation: {json.dumps(diagnosis.get("current_situation", []))}
Key gaps: {json.dumps(diagnosis.get("key_gaps", []))}
Opportunities: {json.dumps(diagnosis.get("opportunities", []))}
Recommended services: {json.dumps(diagnosis.get("recommended_services", []))}
Tone: {diagnosis.get("tone_notes", "")}
""".strip()

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        system=PROPOSAL_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(l for l in lines if not l.strip().startswith("```")).strip()

    if not raw:
        raise ValueError(
            f"Claude returned empty response. "
            f"Stop reason: {message.stop_reason}. Full: {message.content}"
        )

    return json.loads(raw)

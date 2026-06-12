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
        resp = httpx.get(url, headers=headers, timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=True)
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
    # Sonnet is fast enough for research/diagnosis; timeout prevents silent hangs
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], timeout=90.0)

    website_content = _fetch_website(brief.get("website_url", ""))

    website_section = (
        f"\n\nWEBSITE CONTENT (truncated):\n{website_content}"
        if website_content
        else "\n\nWEBSITE: Could not be fetched or URL not provided."
    )

    doc_section = (
        f"\n\nUPLOADED BRIEF / RFP DOCUMENT (use as additional context):\n{brief.get('doc_context', '')}"
        if brief.get("doc_context")
        else ""
    )

    user_message = f"""
Analyse this prospect:

Company: {brief.get("prospect_name")}
Website: {brief.get("website_url", "Not provided")}
Industry: {brief.get("industry", "Not specified")}
Services requested: {", ".join(brief.get("services", []))}

Sales notes:
{brief.get("sales_notes", "No notes provided")}
{website_section}{doc_section}
""".strip()

    message = client.messages.create(
        model="claude-sonnet-4-6",
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
- A prospect brief (company, industry, services requested, sales notes, and optionally an uploaded document)
- A pre-written diagnosis of the prospect's situation

Use the diagnosis to ground every section in specific, real observations.
Write for slides — confident, specific, human. No corporate jargon.

STRICT RULES:
- Only reference services and pricing from the official Honey Whale service list and rate card below.
- Do not invent services, packages, or pricing.
- All pricing in ZAR. Format as "R8,500" or "R12,500/mo".
- plan always has exactly 5 phases.
- realities always has exactly 3 items.
- cost.monthly: up to 2 recurring line items. Use empty strings if fewer than 2.
- cost.oneoff: up to 3 one-off line items. Use empty strings if fewer than 3.
- If there are no monthly retainers, set monthly_total to "".
- If there are no one-off payments, set oneoff_total to "".

LAYOUT CONSTRAINTS (text must fit slide boxes):
- engagement_summary: max 2 sentences.
- where_now_title: max 5 words, e.g. "A strong brand with no SEO".
- brand_summary: max 3 sentences. Specific to this prospect.
- key_stat: one bold metric that captures the gap or opportunity. Max 6 characters, e.g. "0%", "R0", "2.1%".
- key_stat_label: max 8 words, e.g. "revenue from organic search today".
- realities[].title: max 3 words.
- realities[].body: 2-4 sentences.
- plan[].title: max 3 words.
- plan[].time: max 10 characters, e.g. "Week 1–2", "Month 1".
- plan[].items: max 4 bullets. Each item max 40 characters.
- timeline: max 2 sentences.

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
  "engagement_summary": "string — max 2 sentences summarising what is being proposed",
  "where_now_title": "string — max 5 words capturing the prospect's current situation",
  "brand_summary": "string — max 3 sentences, specific to this prospect",
  "key_stat": "string — one striking metric that captures the gap or opportunity",
  "key_stat_label": "string — max 8 words explaining what the stat means",

  "realities": [
    {{"title": "string — max 3 words", "body": "string — 2-4 sentences"}},
    {{"title": "string", "body": "string"}},
    {{"title": "string", "body": "string"}}
  ],

  "plan": [
    {{"title": "string — max 3 words", "time": "string — e.g. 'Week 1–2'", "items": ["string — max 40 chars", "string"]}},
    {{"title": "string", "time": "string", "items": ["string", "string"]}},
    {{"title": "string", "time": "string", "items": ["string", "string"]}},
    {{"title": "string", "time": "string", "items": ["string", "string"]}},
    {{"title": "string", "time": "string", "items": ["string", "string"]}}
  ],

  "cost": {{
    "monthly": [
      {{"name": "string — recurring service name", "price": "string — e.g. 'R12,500/mo'"}},
      {{"name": "string or empty", "price": "string or empty"}}
    ],
    "monthly_total": "string — e.g. 'R23,500/mo', or empty string if no retainers",
    "oneoff": [
      {{"name": "string — one-off service name", "price": "string — e.g. 'R8,500'"}},
      {{"name": "string or empty", "price": "string or empty"}},
      {{"name": "string or empty", "price": "string or empty"}}
    ],
    "oneoff_total": "string — e.g. 'R22,000', or empty string if no one-offs"
  }},

  "timeline": "string — max 2 sentences"
}}
""".strip()


def generate_proposal_content(brief: dict, diagnosis: dict) -> dict:
    """
    Step 2: Takes the brief + diagnosis and returns the full proposal JSON.
    """
    # Opus for proposal writing; timeout prevents silent hangs on Railway
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], timeout=180.0)

    doc_section = (
        f"\n\nUPLOADED BRIEF / RFP DOCUMENT (treat as primary source of requirements):\n{brief.get('doc_context', '')}"
        if brief.get("doc_context")
        else ""
    )

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
{doc_section}

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
        max_tokens=8192,
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

"""
Handles all communication with the Anthropic Claude API.
Loads HW context files at import time and builds the system prompt.

The JSON schema Claude returns maps 1:1 to the placeholder map in pptx_generator.py.
If you add a new placeholder to the deck, add the corresponding key here.
"""

import os
import json
from pathlib import Path
import anthropic

# Load context files once at startup
CONTEXT_DIR = Path(__file__).parent.parent / "context"


def _load_context_file(filename: str) -> str:
    path = CONTEXT_DIR / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"[{filename} not found — add it to the context/ folder]"


SERVICES_CONTEXT = _load_context_file("services.md")
RATE_CARD_CONTEXT = _load_context_file("rate_card.md")

SYSTEM_PROMPT = f"""
You are a senior proposal writer for Honey Whale (Pty) Ltd, a Shopify-focused growth agency in South Africa.

Your job is to generate structured proposal content based on a prospect brief.
The output populates a branded PPTX template — write for slides, not essays.
Copy should be confident, specific, and human. No corporate jargon.

STRICT RULES:
- Only reference services and pricing from the official Honey Whale service list and rate card below.
- Do not invent services, packages, or pricing. If something isn't in the rate card, don't include it.
- All pricing is in ZAR. Format as "R85,000" or "R9,500/month".
- The plan always has exactly 5 phases (consolidate if fewer services are needed).
- Realities always has exactly 3 items.
- Deliverables always has exactly 4 columns.
- To get started always has exactly 6 items.

LAYOUT CONSTRAINTS (these are slide text boxes — content must fit):
- plan[].title: max 3 words. e.g. "Foundation", "Store Build", "SEO & Content". Never a full sentence.
- plan[].items: max 4 bullet points per phase. Each item max 40 characters.
- deliverables[].title: max 3 words. e.g. "Store & Theme", "SEO & Content".
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

Return a single valid JSON object matching this schema exactly.
No markdown. No explanation. Only the JSON.

{{
  "prospect_name": "string — company name for the cover slide",
  "start_date": "string — estimated project start, e.g. 'JUNE 2026' or 'TBC'",
  "brand_summary": "string — 2-3 sentences describing where the prospect is now: their brand, market position, and the core opportunity or gap. Written as a diagnosis, not a pitch.",

  "realities": [
    {{"title": "string — short label, e.g. 'The Brand'", "text": "string — 2-4 sentences expanding on this reality"}},
    {{"title": "string", "text": "string"}},
    {{"title": "string", "text": "string"}}
  ],

  "plan": [
    {{"title": "string — phase name, e.g. 'Foundation'", "items": ["string", "string"]}},
    {{"title": "string", "items": ["string", "string"]}},
    {{"title": "string", "items": ["string", "string"]}},
    {{"title": "string", "items": ["string", "string"]}},
    {{"title": "string", "items": ["string", "string"]}}
  ],

  "cost": {{
    "line_1_name": "string — consolidated service name, e.g. 'Custom Shopify Store Build'",
    "line_1_desc": "string — short comma-separated summary of what's included",
    "line_1_price": "string — e.g. 'R85,000' or 'R9,500/month'",
    "total": "string — e.g. 'R85,000' or 'R9,500/month + R15,000 once-off'"
  }},

  "deliverables": [
    {{"title": "string — column heading, e.g. 'Store & Theme'", "items": ["string", "string"]}},
    {{"title": "string", "items": ["string", "string"]}},
    {{"title": "string", "items": ["string", "string"]}},
    {{"title": "string", "items": ["string", "string"]}}
  ],

  "timeline": "string — e.g. '6–8 weeks from project kick-off to go-live.'",
  "out_of_scope": "string — comma-separated list of what is explicitly excluded",

  "to_get_started": [
    {{"title": "string — short label, e.g. 'Brand Assets'", "text": "string — 1-2 sentences on what's needed"}},
    {{"title": "string", "text": "string"}},
    {{"title": "string", "text": "string"}},
    {{"title": "string", "text": "string"}},
    {{"title": "string", "text": "string"}},
    {{"title": "string", "text": "string"}}
  ]
}}
""".strip()


def generate_proposal_content(brief: dict) -> dict:
    """
    Takes a prospect brief dict and returns structured proposal content as a dict.
    Raises on API or JSON parse error.
    """
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    user_message = f"""
Generate a proposal for the following prospect:

Company: {brief.get("prospect_name")}
Website: {brief.get("website_url", "Not provided")}
Industry: {brief.get("industry", "Not specified")}
Services: {", ".join(brief.get("services", []))}
Contact name: {brief.get("contact_name")}
Account manager: {brief.get("account_manager")}
Account manager email: {brief.get("account_manager_email", "")}

Sales notes / context:
{brief.get("sales_notes", "No notes provided")}
""".strip()

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = message.content[0].text.strip()

    # Strip markdown code fences if Claude wrapped the JSON despite instructions
    if raw.startswith("```"):
        lines = raw.splitlines()
        # Drop the opening fence (```json or ```) and closing fence (```)
        raw = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        ).strip()

    if not raw:
        raise ValueError(
            f"Claude returned an empty response. "
            f"Stop reason: {message.stop_reason}. "
            f"Full response: {message.content}"
        )

    return json.loads(raw)

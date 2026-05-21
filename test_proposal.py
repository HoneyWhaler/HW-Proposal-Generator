"""
Phase 4 test script — run this before touching the web app.

Stage 1: PPTX generation with dummy data (no API key needed)
Stage 2: Full pipeline — Claude content generation + PPTX output

Usage:
  python test_proposal.py          # Stage 1 only (template test)
  python test_proposal.py --full   # Stage 1 + Stage 2 (requires ANTHROPIC_API_KEY in .env)
"""

import sys
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

OUTPUT_DIR = Path("test_output")
OUTPUT_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# DUMMY DATA — edit this to match a real prospect for a more meaningful test
# ---------------------------------------------------------------------------

DUMMY_BRIEF = {
    "prospect_name": "Cape Coast Coffee",
    "website_url": "https://capecoastcoffee.co.za",
    "industry": "Food & Beverage",
    "services": ["Shopify Theme Build", "E-Commerce SEO"],
    "contact_name": "Sarah",
    "account_manager": "Brad",
    "account_manager_email": "brad@honeywhale.co.za",
    "sales_notes": (
        "Currently on WooCommerce. Site is slow and hard to manage. "
        "Selling premium single-origin coffee directly to consumers. "
        "Wants to grow organic traffic and improve the online store experience. "
        "Budget is flexible. Looking to launch before the festive season."
    ),
}

DUMMY_PROPOSAL = {
    "prospect_name": "Cape Coast Coffee",
    "start_date": "JULY 2026",
    "brand_summary": (
        "Cape Coast Coffee is a premium single-origin coffee brand selling direct-to-consumer "
        "in South Africa. The brand has a loyal following but is being held back by a slow, "
        "hard-to-manage WooCommerce store that undermines the premium positioning at every touchpoint."
    ),
    "realities": [
        {
            "title": "The Platform",
            "text": (
                "WooCommerce requires ongoing technical maintenance that pulls focus away from the business. "
                "Slow load times and a clunky checkout are costing conversions every day."
            ),
        },
        {
            "title": "The Opportunity",
            "text": (
                "Specialty coffee is a high-intent, high-loyalty category. Shoppers who find the right brand "
                "stick with it. A fast, well-designed store with strong SEO will compound over time."
            ),
        },
        {
            "title": "The Gap",
            "text": (
                "There is no clear organic search presence for Cape Coast Coffee. No product schema, "
                "no collection SEO, no blog content targeting buyers at the top of the funnel."
            ),
        },
    ],
    "plan": [
        {
            "title": "Migration",
            "items": ["WooCommerce audit & data export", "301 redirect mapping", "Product & content migration"],
        },
        {
            "title": "Store Build",
            "items": ["Theme setup & brand config", "Mobile-first responsive build", "Payment gateway & shipping"],
        },
        {
            "title": "SEO Foundation",
            "items": ["Keyword research (20 targets)", "Product title & meta optimisation", "Collection page SEO"],
        },
        {
            "title": "Content",
            "items": ["2 blog posts/month", "AI-friendly product descriptions", "Schema markup (product + FAQ)"],
        },
        {
            "title": "Launch & Handover",
            "items": ["Pre-launch QA", "2-hour CMS training", "30-day post-launch support"],
        },
    ],
    "cost": {
        "line_1_name": "Shopify Theme Build (Standard) + E-Commerce SEO (Lite)",
        "line_1_desc": (
            "Theme build · product & page setup · payment gateway · shipping · QA & launch · "
            "20 keywords · product SEO · 2 blogs/mo · schema markup · backlinks"
        ),
        "line_1_price": "R57,000 once-off + R12,500/mo",
        "total": "R57,000 once-off + R12,500/month (3-month SEO minimum)",
    },
    "deliverables": [
        {
            "title": "Store & Theme",
            "items": [
                "Shopify store on Standard theme",
                "Brand colours, typography & logo",
                "All core pages built & populated",
                "Mobile-first responsive build",
                "PayFast / Peach Payments setup",
                "Shipping & logistics config",
            ],
        },
        {
            "title": "Commerce",
            "items": [
                "All products migrated with variants",
                "Collections & menu structure",
                "Cart & checkout optimisation",
                "Newsletter popup + Omnisend",
                "Branded email notifications",
                "Legal policy pages",
            ],
        },
        {
            "title": "SEO",
            "items": [
                "20 target keywords researched",
                "Product title & meta optimisation (10/mo)",
                "Collection page SEO (2/mo)",
                "Image & alt-text optimisation (30/mo)",
                "2 blog posts/month (800–1,200 words)",
                "5–10 quality backlinks/month",
            ],
        },
        {
            "title": "Technical & Launch",
            "items": [
                "301 redirects from WooCommerce URLs",
                "Product schema markup (10/mo)",
                "Page speed optimisation (>80 PSI)",
                "Cross-browser & device QA",
                "2-hour CMS training session",
                "30-day post-launch support",
            ],
        },
    ],
    "timeline": (
        "4–6 weeks for store build, running concurrently with SEO setup. "
        "SEO results typically visible from month 2 onwards."
    ),
    "out_of_scope": (
        "Copywriting, product photography, logo or brand design, "
        "paid advertising, inventory system development."
    ),
    "to_get_started": [
        {"title": "Brand Assets", "text": "Logo files (SVG/PNG), brand guidelines, approved colour palette and typography."},
        {"title": "Product Data", "text": "Full product list with descriptions, ZAR pricing, high-res imagery, and any variant data."},
        {"title": "WooCommerce Access", "text": "Admin login to your existing WooCommerce store for the pre-migration audit."},
        {"title": "Payment Gateway", "text": "Confirmed SA payment gateway (PayFast, Peach Payments, or Yoco) with account access or setup in progress."},
        {"title": "Domain Access", "text": "DNS login credentials for domain pointing on go-live day."},
        {"title": "Signed Acceptance", "text": "Signed proposal and 50% upfront deposit to confirm your project start date."},
    ],
}


# ---------------------------------------------------------------------------
# STAGE 1 — PPTX generation with dummy data
# ---------------------------------------------------------------------------

def test_pptx_generation():
    print("\n── Stage 1: PPTX generation with dummy data ──────────────────")

    from app.pptx_generator import generate_pptx

    output_path = OUTPUT_DIR / "test_stage1_dummy.pptx"

    try:
        generate_pptx(DUMMY_PROPOSAL, DUMMY_BRIEF, output_path)
        size_kb = output_path.stat().st_size // 1024
        print(f"  ✅ PPTX generated: {output_path} ({size_kb} KB)")
        print(f"  → Open it and check every slide for correct placeholder replacement.")
        return True
    except FileNotFoundError as e:
        print(f"  ❌ Template not found: {e}")
        return False
    except Exception as e:
        print(f"  ❌ Error: {e}")
        raise


# ---------------------------------------------------------------------------
# STAGE 2 — Full pipeline: Claude + PPTX
# ---------------------------------------------------------------------------

def test_full_pipeline():
    print("\n── Stage 2: Full pipeline (Claude API + PPTX) ─────────────────")

    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("  ❌ ANTHROPIC_API_KEY not set in .env — skipping Stage 2.")
        return False

    from app.claude_client import generate_proposal_content
    from app.pptx_generator import generate_pptx

    print("  Calling Claude API...")
    try:
        proposal = generate_proposal_content(DUMMY_BRIEF)
        print("  ✅ Claude returned valid JSON")

        # Save the raw JSON so you can inspect the structure
        json_path = OUTPUT_DIR / "test_stage2_proposal.json"
        json_path.write_text(json.dumps(proposal, indent=2))
        print(f"  → Raw JSON saved to: {json_path}")

        output_path = OUTPUT_DIR / "test_stage2_full.pptx"
        generate_pptx(proposal, DUMMY_BRIEF, output_path)
        size_kb = output_path.stat().st_size // 1024
        print(f"  ✅ PPTX generated: {output_path} ({size_kb} KB)")
        print(f"  → Open it and review the copy quality against your brief.")
        return True

    except Exception as e:
        print(f"  ❌ Error: {e}")
        raise


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    full = "--full" in sys.argv

    print("HW Proposal Generator — Test Script")
    print("=====================================")

    stage1_ok = test_pptx_generation()

    if full:
        if stage1_ok:
            test_full_pipeline()
        else:
            print("\n  Skipping Stage 2 — fix Stage 1 errors first.")
    else:
        print("\n  Run with --full to also test the Claude API pipeline.")

    print("\nDone. Check the test_output/ folder for generated files.")

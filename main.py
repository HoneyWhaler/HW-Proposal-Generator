"""
Honey Whale Proposal Generator
FastAPI entry point.

Uses Server-Sent Events (SSE) to stream live progress updates to the browser
during the two-step generation pipeline:
  1. Fetch & analyse prospect website
  2. Generate diagnosis
  3. Write proposal content
  4. Build PPTX
  5. Upload to Google Drive
"""

import os
import json
import asyncio
from pathlib import Path
from datetime import datetime
from typing import List

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

from app.claude_client import diagnose, generate_proposal_content
from app.pptx_generator import generate_pptx
from app.drive_client import upload_proposal

load_dotenv()

app = FastAPI(title="HW Proposal Generator")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

GENERATED_DIR = Path("generated")
GENERATED_DIR.mkdir(exist_ok=True)


@app.get("/", response_class=HTMLResponse)
async def intake_form(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health():
    """Quick check that env vars and token bootstrap are working. Safe to hit publicly."""
    from pathlib import Path
    import base64
    b64 = os.environ.get("GOOGLE_TOKEN_PICKLE_B64", "")
    token_exists = Path("token.pickle").exists()

    # Attempt bootstrap if not already done
    if b64 and not token_exists:
        try:
            Path("token.pickle").write_bytes(base64.b64decode(b64.strip()))
            token_exists = True
            bootstrap_result = "written now"
        except Exception as ex:
            bootstrap_result = f"decode failed: {ex}"
    elif token_exists:
        bootstrap_result = "already exists"
    else:
        bootstrap_result = "env var not set"

    return {
        "GOOGLE_TOKEN_PICKLE_B64_set": bool(b64),
        "GOOGLE_TOKEN_PICKLE_B64_length": len(b64),
        "GOOGLE_DRIVE_ROOT_FOLDER_ID_set": bool(os.environ.get("GOOGLE_DRIVE_ROOT_FOLDER_ID")),
        "ANTHROPIC_API_KEY_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "token_pickle": bootstrap_result,
    }


@app.post("/generate")
async def generate(
    request: Request,
    prospect_name: str = Form(...),
    website_url: str = Form(""),
    industry: str = Form(""),
    services: List[str] = Form(...),
    contact_name: str = Form(...),
    account_manager: str = Form(...),
    account_manager_email: str = Form(...),
    sales_notes: str = Form(""),
):
    brief = {
        "prospect_name": prospect_name,
        "website_url": website_url,
        "industry": industry,
        "services": services,
        "contact_name": contact_name,
        "account_manager": account_manager,
        "account_manager_email": account_manager_email,
        "sales_notes": sales_notes,
    }

    def event_stream():
        """Generator that yields SSE messages as each pipeline step completes."""

        def send(step: str, message: str, data: dict = None):
            payload = {"step": step, "message": message}
            if data:
                payload["data"] = data
            return f"data: {json.dumps(payload)}\n\n"

        try:
            # Step 1 — Diagnose
            yield send("diagnosing", f"Researching {prospect_name}...")
            diagnosis = diagnose(brief)

            # Step 2 — Generate proposal content
            yield send("writing", "Writing proposal content...")
            proposal = generate_proposal_content(brief, diagnosis)

            # Step 3 — Build PPTX
            yield send("building", "Building the deck...")
            date_str = datetime.now().strftime("%Y-%m-%d")
            filename = f"HW Proposal — {prospect_name} — {date_str}.pptx"
            output_path = GENERATED_DIR / filename
            generate_pptx(proposal, brief, output_path)

            # Step 4 — Upload to Drive
            yield send("uploading", "Uploading to Google Drive...")
            drive_link = upload_proposal(output_path, prospect_name)

            # Clean up local file
            output_path.unlink(missing_ok=True)

            # Done
            yield send("done", "Proposal ready.", {
                "drive_link": drive_link,
                "prospect": prospect_name,
            })

        except Exception as e:
            yield send("error", str(e))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

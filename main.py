"""
Honey Whale Proposal Generator
FastAPI entry point.

Uses Server-Sent Events (SSE) to stream live progress updates to the browser
during the generation pipeline:
  1. Fetch & analyse prospect website  → diagnose()
  2. Write proposal content            → generate_proposal_content()
  3. Build Google Slides deck in Drive → generate_slides()
"""

import os
import io
import json
from typing import List, Optional

from fastapi import FastAPI, Request, Form, File, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

from app.claude_client import diagnose, generate_proposal_content
from app.slides_generator import generate_slides

load_dotenv()

app = FastAPI(title="HW Proposal Generator")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


def _extract_doc_text(file: UploadFile) -> str:
    """
    Extracts plain text from an uploaded PDF or DOCX file.
    Returns an empty string if extraction fails or no file was provided.
    Truncated to ~8,000 chars to stay within reasonable context limits.
    """
    if not file or not file.filename:
        return ""
    try:
        contents = file.file.read()
        filename = file.filename.lower()

        if filename.endswith(".pdf"):
            import pdfplumber
            text_parts = []
            with pdfplumber.open(io.BytesIO(contents)) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)
            return "\n\n".join(text_parts)[:8000]

        elif filename.endswith(".docx"):
            from docx import Document
            doc = Document(io.BytesIO(contents))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            return text[:8000]

        # Unsupported format — skip silently
        return ""
    except Exception as ex:
        print(f"[doc_extract] Failed to extract text from {file.filename}: {ex}", flush=True)
        return ""


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
    brief_doc: Optional[UploadFile] = File(None),
    prospect_logo: Optional[UploadFile] = File(None),
    store_image: Optional[UploadFile] = File(None),
):
    # Extract text from uploaded brief/RFP (if any)
    doc_context = _extract_doc_text(brief_doc) if brief_doc else ""
    if doc_context:
        print(f"[pipeline] Extracted {len(doc_context)} chars from uploaded doc: {brief_doc.filename}", flush=True)

    # Read image bytes upfront — UploadFile streams must be consumed before
    # the SSE generator starts or the request context may be gone.
    logo_bytes: Optional[bytes] = None
    logo_filename: Optional[str] = None
    if prospect_logo and prospect_logo.filename:
        logo_bytes = prospect_logo.file.read()
        logo_filename = prospect_logo.filename
        print(f"[pipeline] Logo uploaded: {logo_filename} ({len(logo_bytes)} bytes)", flush=True)

    store_image_bytes: Optional[bytes] = None
    store_image_filename: Optional[str] = None
    if store_image and store_image.filename:
        store_image_bytes = store_image.file.read()
        store_image_filename = store_image.filename
        print(f"[pipeline] Store image uploaded: {store_image_filename} ({len(store_image_bytes)} bytes)", flush=True)

    brief = {
        "prospect_name": prospect_name,
        "website_url": website_url,
        "industry": industry,
        "services": services,
        "contact_name": contact_name,
        "account_manager": account_manager,
        "account_manager_email": account_manager_email,
        "sales_notes": sales_notes,
        "doc_context": doc_context,
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
            print(f"[pipeline] START diagnose: {prospect_name}", flush=True)
            yield send("diagnosing", f"Researching {prospect_name}...")
            diagnosis = diagnose(brief)
            print(f"[pipeline] DONE diagnose", flush=True)

            # Step 2 — Generate proposal content
            print(f"[pipeline] START generate_proposal_content", flush=True)
            yield send("writing", "Writing proposal content...")
            proposal = generate_proposal_content(brief, diagnosis)
            print(f"[pipeline] DONE generate_proposal_content", flush=True)

            # Step 3 — Build Google Slides deck and save to Drive
            print(f"[pipeline] START generate_slides", flush=True)
            yield send("building", "Building your proposal in Google Slides...")
            slides_link = generate_slides(
                proposal,
                brief,
                logo_bytes=logo_bytes,
                logo_filename=logo_filename,
                store_image_bytes=store_image_bytes,
                store_image_filename=store_image_filename,
            )
            print(f"[pipeline] DONE generate_slides: {slides_link}", flush=True)

            # Done
            yield send("done", "Proposal ready.", {
                "drive_link": slides_link,
                "prospect": prospect_name,
            })

        except Exception as e:
            print(f"[pipeline] ERROR: {e}", flush=True)
            yield send("error", str(e))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

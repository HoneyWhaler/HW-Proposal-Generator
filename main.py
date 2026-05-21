"""
Honey Whale Proposal Generator
FastAPI entry point — serves the intake form and handles proposal generation.
"""

import os
from pathlib import Path
from datetime import datetime
from typing import List

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

from app.claude_client import generate_proposal_content
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

    try:
        # 1. Generate content via Claude
        proposal = generate_proposal_content(brief)

        # 2. Populate PPTX template
        date_str = datetime.now().strftime("%Y-%m-%d")
        filename = f"HW Proposal — {prospect_name} — {date_str}.pptx"
        output_path = GENERATED_DIR / filename
        generate_pptx(proposal, brief, output_path)

        # 3. Upload to Google Drive
        drive_link = upload_proposal(output_path, prospect_name)

        # 4. Clean up local file
        output_path.unlink(missing_ok=True)

        return JSONResponse({
            "success": True,
            "drive_link": drive_link,
            "prospect": prospect_name,
        })

    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

"""
Admin UI Router — serves the server-rendered operations dashboard.
"""

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.onboarding_case import OnboardingCase
from app.api.admin_cases import dashboard_stats

router = APIRouter(prefix="/admin/ui", tags=["admin-ui"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    """Render the main operations dashboard."""
    stats = await dashboard_stats(db)
    
    # Get 10 most recent cases
    result = await db.execute(
        select(OnboardingCase).order_by(OnboardingCase.created_at.desc()).limit(10)
    )
    recent_cases = result.scalars().all()
    
    return templates.TemplateResponse(
        "admin/dashboard.html",
        {
            "request": request,
            "stats": stats,
            "recent_cases": recent_cases,
            "now": datetime.now(timezone.utc),
        }
    )


@router.get("/cases", response_class=HTMLResponse)
async def list_cases_ui(request: Request, db: AsyncSession = Depends(get_db)):
    """Render the full case list view."""
    result = await db.execute(
        select(OnboardingCase).order_by(OnboardingCase.created_at.desc())
    )
    cases = result.scalars().all()
    return templates.TemplateResponse(
        "admin/case_list.html",
        {"request": request, "cases": cases}
    )


@router.get("/cases/{case_id}", response_class=HTMLResponse)
async def case_detail_ui(case_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)):
    """Render the detailed view for a single case."""
    result = await db.execute(select(OnboardingCase).where(OnboardingCase.id == case_id))
    case = result.scalar_one_or_none()
    if not case:
        return HTMLResponse("Case not found", status_code=404)
        
    return templates.TemplateResponse(
        "admin/case_detail.html",
        {"request": request, "case": case}
    )

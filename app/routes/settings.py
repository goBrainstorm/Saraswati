from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.templates_env import templates

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse, include_in_schema=False)
async def settings_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "settings.html", {"active_page": "settings"})

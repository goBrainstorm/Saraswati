from typing import Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.prompts import DEFAULTS, load_prompts, update_prompt

router = APIRouter()


class PromptUpdate(BaseModel):
    text: str


@router.get("/api/prompts")
async def get_prompts() -> Dict[str, str]:
    """Return all current prompt values."""
    return load_prompts()


@router.put("/api/prompts/{name}")
async def put_prompt(name: str, body: PromptUpdate) -> Dict[str, str]:
    """Update a single prompt by name. Returns the full updated prompts dict."""
    if name not in DEFAULTS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown prompt '{name}'. Valid keys: {list(DEFAULTS)}",
        )
    update_prompt(name, body.text)
    return load_prompts()

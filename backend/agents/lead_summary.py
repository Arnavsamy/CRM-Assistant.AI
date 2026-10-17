"""Stateless, one-call lead briefing endpoint."""
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.agents.rag_service import RAGService
from backend.database import db
from backend.factory import get_chat_model

logger = logging.getLogger(__name__)
router = APIRouter(tags=["lead briefing"])


class BriefingCard(BaseModel):
    who_they_are: str
    why_they_match: str
    talking_point: str
    sources_used: int


async def _company_rag(company_id: str) -> list[str]:
    """Retrieve company research without making another LLM call."""
    try:
        collection = RAGService._collection("company_rag")
        result: dict[str, Any] = collection.query(
            query_texts=["company overview business priorities pain points"],
            n_results=3,
            where={"company_id": company_id},
        )
        return result.get("documents", [[]])[0]
    except Exception as exc:
        # The briefing remains useful if Chroma/Gemini embedding setup is unavailable.
        logger.warning("Company RAG retrieval skipped for %s: %s", company_id, exc)
        return []


@router.post("/api/leads/{lead_id}/summary", response_model=BriefingCard)
async def lead_summary(lead_id: str) -> BriefingCard:
    """Return a three-bullet briefing. Stateless: no session or history is stored."""
    lead = await db.get_lead_with_company(lead_id)
    if not lead or not lead.get("company"):
        raise HTTPException(status_code=404, detail="Lead not found")

    company = lead["company"]
    documents = await _company_rag(company["id"])
    company_data = {
        key: company.get(key)
        for key in ("name", "domain", "industry", "description", "website", "match_score", "why_recommended", "pain_points")
    }
    prompt = f"""You create truthful, concise sales-research briefing cards.
Use ONLY the company data and research excerpts below. Do not invent facts. If evidence is missing,
say so plainly. Return exactly three markdown bullets, in this exact order and under 45 words each:
- Who they are: ...
- Why they match: ...
- Talking point: ...

Company data: {company_data}
Research excerpts: {documents or ['No retrieved research documents available.']}"""
    try:
        # This is the endpoint's only Groq/LLM call.
        answer = (await get_chat_model(temperature=0.2).ainvoke(prompt)).content.strip()
    except Exception as exc:
        logger.exception("Lead summary generation failed")
        raise HTTPException(status_code=502, detail="Groq briefing generation failed") from exc

    lines = [line.removeprefix("- ").strip() for line in answer.splitlines() if line.lstrip().startswith("-")]
    if len(lines) != 3:
        # Keep the API shape stable if the model ignores formatting slightly.
        lines = (lines + ["Insufficient evidence to provide this item."] * 3)[:3]
    return BriefingCard(
        who_they_are=lines[0].removeprefix("Who they are:").strip(),
        why_they_match=lines[1].removeprefix("Why they match:").strip(),
        talking_point=lines[2].removeprefix("Talking point:").strip(),
        sources_used=len(documents),
    )

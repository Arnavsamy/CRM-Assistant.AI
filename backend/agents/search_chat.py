"""Search-scoped Groq chat endpoint, seeded from real discovered companies."""
import uuid
from collections import defaultdict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.database import db
from backend.factory import get_chat_model

router = APIRouter(tags=["search chat"])
MAX_HISTORY_MESSAGES = 12
SESSIONS: dict[str, list[dict[str, str]]] = defaultdict(list)


class SearchChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    session_id: str | None = None
    reset: bool = False


class SearchChatResponse(BaseModel):
    session_id: str
    answer: str


def _company_context(companies: list[dict]) -> str:
    # Only fields needed to answer comparison/filter questions are sent to Groq.
    rows = []
    for company in companies:
        rows.append({key: company.get(key) for key in (
            "name", "industry", "description", "website", "match_score",
            "why_recommended", "pain_points",
        )})
    return str(rows)


@router.post("/api/searches/{search_id}/chat", response_model=SearchChatResponse)
async def search_chat(search_id: str, request: SearchChatRequest) -> SearchChatResponse:
    """Chat about one search. The session is in-memory, like Chatbot.py."""
    search = await db.get_search_details(search_id)
    if not search:
        raise HTTPException(status_code=404, detail="Search not found")
    companies = await db.get_companies_by_search(search_id)
    if not companies:
        raise HTTPException(status_code=404, detail="No discovered companies for this search yet")

    session_id = request.session_id or str(uuid.uuid4())
    if request.reset:
        SESSIONS[session_id] = []
    history = SESSIONS[session_id]
    system = f"""You answer questions only about companies discovered for this search.
Use the supplied company records as the source of truth. Never guess or add companies.
If a fact is absent, say it is not available. Be concise (under 150 words).

Search product: {search['product_name']}
Search product description: {search['product_description']}
Discovered company records: {_company_context(companies)}"""
    try:
        result = await get_chat_model(temperature=0.2).ainvoke([
            ("system", system), *[(item["role"], item["content"]) for item in history],
            ("human", request.message.strip()),
        ])
        answer = str(result.content).strip()
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Groq search-chat generation failed") from exc

    history.extend([{"role": "human", "content": request.message.strip()}, {"role": "assistant", "content": answer}])
    SESSIONS[session_id] = history[-MAX_HISTORY_MESSAGES:]
    return SearchChatResponse(session_id=session_id, answer=answer)
